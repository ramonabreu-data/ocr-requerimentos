"""Repositório de documentos e lotes: JSON no armazenamento (fonte da verdade) e índice no Redis.

O bucket guarda os arquivos descritos em `modelos.py`. O Redis guarda só o que dá para refazer a partir
deles: um resumo de cada documento, conjuntos ordenados por data de gravação (geral, por situação, por
lote, por procedimento e por município), os contadores de cada lote e o mapa SHA-256 -> documento.
Se o Redis se perder, `reconstruir_indice` (python -m ocr_requerimentos.ferramentas reconstruir-indice)
refaz tudo lendo o bucket.

Regra de gravação: quem altera um documento segura `travar(uuid)`, relê com `obter`, altera e chama
`salvar`. A trava substitui o SELECT ... FOR UPDATE do banco: dois workers, ou um worker e um revisor,
nunca gravam o mesmo documento ao mesmo tempo, e `requerimento.versao` recusa a edição de quem leu uma
versão antiga."""
from __future__ import annotations

import json
import logging
import re
import uuid as _uuid
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from itertools import islice
from typing import Any

from redis import Redis
from redis.exceptions import LockError

from .armazenamento import Armazenamento, armazenamento
from .config import config
from .extracao.texto import sem_acento
from .modelos import (
    STATUS_DOCUMENTO,
    Documento,
    Lote,
    PaginasDocumento,
    agora,
    atualizar_formato,
)

log = logging.getLogger(__name__)

PENDENTES = ("recebido", "processando")
FINAIS = ("extraido", "revisao", "validado", "erro")
SEPARADOR = "\x1f"  # entre os campos do texto de busca, para um termo não casar entre dois campos
SEPARADOR_BUSCA = "\x1e"  # entre as partes da linha compacta de busca (ver _linha_busca)
CAMPOS_BUSCA = ("_requerente", "_busca", "_cpf", "data_documento")
LEITURA_PARALELA = 16


class TravaOcupada(Exception):
    """Outro processo está gravando o mesmo documento há mais tempo que a espera permitida."""


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def _sem_acento_min(texto: str | None) -> str:
    return sem_acento(texto or "").lower()


def _digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


def resumo_documento(d: Documento) -> dict[str, Any]:
    """Resumo usado nas listas da API e guardado no índice."""
    r = d.requerimento
    return {
        "uuid": d.uuid,
        "nome_original": d.arquivo.nome_original,
        "status": d.status,
        "erro": d.erro,
        "tipo_entrada": d.leitura.tipo_entrada,
        "metodo_extracao": d.leitura.metodo_extracao,
        "paginas": d.leitura.paginas,
        "assinatura_tipo": d.assinatura.tipo,
        "lote_uuid": d.lote_origem_uuid,
        "documento_pai_uuid": d.documento_pai_uuid,
        "requerente_nome": r.requerente_nome if r else None,
        "cpf_cnpj": r.cpf_cnpj if r else None,
        "municipio": r.municipio if r else None,
        "procedimento": r.procedimento if r else None,
        "data_documento": r.data_documento.isoformat() if r and r.data_documento else None,
        "validado_em": _iso(r.validacao.validado_em) if r else None,
        "confianca_geral": r.confianca_geral if r else None,
        "pendencias": list(r.pendencias) if r else [],
        "created_at": _iso(d.criado_em),
        "updated_at": _iso(d.atualizado_em),
        "duracao_ms": d.leitura.duracao_ms,
    }


def _resumo_indice(d: Documento) -> dict[str, Any]:
    """Resumo + campos internos (prefixo _) usados pelos filtros; `publico` os remove antes de responder."""
    r = d.requerimento
    res = resumo_documento(d)
    res["_ts"] = d.criado_em.timestamp()
    res["_lotes"] = d.lote_uuids()
    res["_pagina_inicial"] = d.pagina_inicial
    res["_requerente"] = _sem_acento_min(r.requerente_nome if r else None)
    res["_busca"] = SEPARADOR.join(_sem_acento_min(v) for v in (
        d.arquivo.nome_original, r.requerente_nome if r else None, r.cpf_cnpj if r else None,
        r.municipio if r else None,
    ))
    res["_cpf"] = _digitos(r.cpf_cnpj if r else None)
    return res


def _linha_busca(res: dict[str, Any]) -> str:
    """Só o que os filtros de texto e de data do documento olham, numa string curta: a varredura lê isto
    em vez do resumo inteiro."""
    return SEPARADOR_BUSCA.join(res.get(c) or "" for c in CAMPOS_BUSCA)


def _campos_busca(linha: str) -> dict[str, Any]:
    dados = dict(zip(CAMPOS_BUSCA, linha.split(SEPARADOR_BUSCA)))
    dados["data_documento"] = dados.get("data_documento") or None
    return dados


def publico(res: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in res.items() if not k.startswith("_")}


def _em_blocos(itens: Iterable[str], tamanho: int) -> Iterator[list[str]]:
    it = iter(itens)
    while bloco := list(islice(it, tamanho)):
        yield bloco


class Repositorio:
    def __init__(self, store: Armazenamento, r: Redis, prefixo: str = "ocr", trava_segundos: int = 120,
                 apos_salvar: Callable[[Documento, str | None], None] | None = None):
        self.store = store
        self.r = r
        self.p = prefixo
        self.trava_segundos = trava_segundos
        self.apos_salvar = apos_salvar  # recebe (documento salvo, situação anterior): publicação para o SIGA

    # ------------------------------------------------------------- chaves
    def _k(self, *partes: str) -> str:
        return ":".join((self.p, *partes))

    @staticmethod
    def chave_documento(u: str) -> str:
        return f"dados/documentos/{u}.json"

    @staticmethod
    def chave_paginas(u: str) -> str:
        return f"dados/paginas/{u}.json"

    @staticmethod
    def chave_lote(u: str) -> str:
        return f"dados/lotes/{u}.json"

    # ------------------------------------------------------------- travas
    @contextmanager
    def travar(self, nome: str, espera: float = 60):
        """Trava exclusiva entre processos (Redis). Expira sozinha em `trava_segundos` se o dono cair."""
        trava = self.r.lock(self._k("trava", nome), timeout=self.trava_segundos, blocking_timeout=espera)
        if not trava.acquire():
            raise TravaOcupada(f"'{nome}' está sendo gravado por outro processo; tente de novo")
        try:
            yield
        finally:
            try:
                trava.release()
            except LockError:
                log.warning("a trava '%s' expirou antes de ser liberada", nome)

    def ping(self) -> bool:
        return bool(self.r.ping())

    # ------------------------------------------------------------- documentos
    def obter(self, u: str) -> Documento | None:
        try:
            bruto = self.store.ler(self.chave_documento(u))
        except FileNotFoundError:
            return None
        return Documento.model_validate(atualizar_formato(json.loads(bruto)))

    def obter_varios(self, uuids: list[str]) -> list[Documento]:
        """Lê vários documentos em paralelo, na ordem pedida (os que não existirem ficam de fora)."""
        if len(uuids) <= 1:
            return [d for d in map(self.obter, uuids) if d is not None]
        with ThreadPoolExecutor(min(LEITURA_PARALELA, len(uuids))) as ex:
            return [d for d in ex.map(self.obter, uuids) if d is not None]

    def salvar(self, doc: Documento) -> Documento:
        """Valida pelo contrato, grava o JSON e atualiza o índice. Quem chama deve segurar `travar(uuid)`."""
        doc.atualizado_em = agora()
        valido = Documento.model_validate(doc.model_dump())  # reaplica as regras do contrato
        self.store.salvar(self.chave_documento(valido.uuid), valido.model_dump_json(indent=2).encode(),
                          "application/json")
        anterior = self.indexar(valido)
        if self.apos_salvar is not None:
            try:
                self.apos_salvar(valido, anterior)
            except Exception:  # noqa: BLE001 - a gravação já aconteceu; a publicação pode ser refeita
                log.exception("falha ao agendar a publicação de %s para o SIGA", valido.uuid)
        return valido

    def salvar_paginas(self, paginas: PaginasDocumento) -> None:
        self.store.salvar(self.chave_paginas(paginas.documento_uuid), paginas.model_dump_json().encode(),
                          "application/json")

    def obter_paginas(self, u: str) -> PaginasDocumento | None:
        try:
            return PaginasDocumento.model_validate(atualizar_formato(json.loads(self.store.ler(self.chave_paginas(u)))))
        except FileNotFoundError:
            return None

    def uuid_por_sha256(self, h: str) -> str | None:
        return self.r.hget(self._k("sha256"), h)

    # ------------------------------------------------------------- lotes
    def salvar_lote(self, lote: Lote) -> None:
        valido = Lote.model_validate(lote.model_dump())
        self.store.salvar(self.chave_lote(valido.uuid), valido.model_dump_json(indent=2).encode(), "application/json")
        self._indexar_lote(valido)

    def _indexar_lote(self, lote: Lote) -> None:
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(self._k("lote_dados"), lote.uuid, lote.model_dump_json())
        pipe.zadd(self._k("lotes"), {lote.uuid: lote.criado_em.timestamp()})
        if lote.origem == "pasta_monitorada" and lote.nome:
            pipe.hset(self._k("lote_pasta"), lote.nome, lote.uuid)
        pipe.execute()

    def obter_lote(self, u: str) -> Lote | None:
        bruto = self.r.hget(self._k("lote_dados"), u)
        if bruto:
            return Lote.model_validate_json(bruto)
        try:
            return Lote.model_validate(atualizar_formato(json.loads(self.store.ler(self.chave_lote(u)))))
        except FileNotFoundError:
            return None

    def lote_da_pasta(self, nome: str) -> str | None:
        return self.r.hget(self._k("lote_pasta"), nome)

    def listar_lotes(self, pagina: int, tamanho: int) -> tuple[int, list[Lote]]:
        total = self.r.zcard(self._k("lotes"))
        uuids = self.r.zrevrange(self._k("lotes"), (pagina - 1) * tamanho, pagina * tamanho - 1)
        brutos = self.r.hmget(self._k("lote_dados"), uuids) if uuids else []
        return total, [Lote.model_validate_json(b) for b in brutos if b]

    def total_lotes(self) -> int:
        return self.r.zcard(self._k("lotes"))

    def contagem_lote(self, u: str) -> dict[str, int]:
        return {s: int(n) for s, n in self.r.hgetall(self._k("lote", u, "cont")).items() if int(n) > 0}

    def finalizado_em(self, u: str) -> str | None:
        return self.r.get(self._k("lote", u, "fim"))

    def uuids_do_lote(self, u: str) -> list[str]:
        return self.r.zrange(self._k("lote", u, "docs"), 0, -1)

    def _atualizar_fim_lote(self, u: str, momento: datetime | None = None) -> None:
        cont = self.contagem_lote(u)
        if any(cont.get(s, 0) for s in PENDENTES):
            self.r.delete(self._k("lote", u, "fim"))
        else:
            self.r.set(self._k("lote", u, "fim"), (momento or agora()).isoformat(), nx=True)

    # ------------------------------------------------------------- índice
    def indexar(self, doc: Documento, atualizar_fim: bool = True) -> str | None:
        """Atualiza o índice; devolve a situação que o documento tinha antes (None se é novo)."""
        k, u = self._k, doc.uuid
        bruto = self.r.hget(k("resumo"), u)
        antigo = json.loads(bruto) if bruto else None
        novo = _resumo_indice(doc)
        ts = novo["_ts"]
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(k("resumo"), u, json.dumps(novo, ensure_ascii=False))
        pipe.hset(k("busca"), u, _linha_busca(novo))
        pipe.hset(k("sha256"), doc.arquivo.sha256, u)
        if antigo and antigo["status"] != novo["status"]:
            pipe.zrem(k("status", antigo["status"]), u)
        pipe.zadd(k("status", novo["status"]), {u: ts})
        # lista geral e filtros: sem o arquivo dividido, que só agrupa as partes
        listavel = novo["status"] != "dividido"
        if listavel:
            pipe.zadd(k("docs"), {u: ts})
        else:
            pipe.zrem(k("docs"), u)
        for campo, nome in (("procedimento", "proc"), ("municipio", "mun")):
            va = antigo.get(campo) if antigo and antigo["status"] != "dividido" else None
            vn = novo.get(campo) if listavel else None
            if va == vn:
                continue
            if va:
                pipe.zrem(k(nome, va), u)
                pipe.hincrby(k("opcoes", nome), va, -1)
            if vn:
                pipe.zadd(k(nome, vn), {u: ts})
                pipe.hincrby(k("opcoes", nome), vn, 1)
        lotes_antigos = set(antigo["_lotes"]) if antigo else set()
        for lote in novo["_lotes"]:
            pipe.zadd(k("lote", lote, "docs"), {u: ts})
            if lote not in lotes_antigos:
                pipe.hincrby(k("lote", lote, "cont"), novo["status"], 1)
            elif antigo["status"] != novo["status"]:
                pipe.hincrby(k("lote", lote, "cont"), antigo["status"], -1)
                pipe.hincrby(k("lote", lote, "cont"), novo["status"], 1)
        pipe.execute()
        if atualizar_fim:
            for lote in novo["_lotes"]:
                self._atualizar_fim_lote(lote)
        return antigo["status"] if antigo else None

    def resumos(self, uuids: list[str]) -> list[dict[str, Any]]:
        if not uuids:
            return []
        return [json.loads(b) for b in self.r.hmget(self._k("resumo"), uuids) if b]

    def resumo(self, u: str) -> dict[str, Any] | None:
        b = self.r.hget(self._k("resumo"), u)
        return json.loads(b) if b else None

    def consultar(
        self,
        *,
        status: list[str] | None = None,
        procedimento: str | None = None,
        municipio: str | None = None,
        ts_de: float | None = None,
        ts_ate: float | None = None,
        filtro: Callable[[dict[str, Any]], bool] | None = None,
        pagina: int = 1,
        tamanho: int = 25,
        crescente: bool = False,
        bloco: int = 2000,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Documentos (sem os divididos) por data de gravação. Situação, procedimento, município e período de
        gravação saem direto dos conjuntos do índice; `filtro` (texto, data do documento) percorre só os
        candidatos que sobraram, em blocos, recebendo {_requerente, _busca, _cpf, data_documento}."""
        k = self._k
        temporarios: list[str] = []

        def temporario() -> str:
            nome = k("tmp", _uuid.uuid4().hex)
            temporarios.append(nome)
            return nome

        try:
            if status is not None:
                status = [s for s in status if s in STATUS_DOCUMENTO and s != "dividido"]
                if not status:
                    return 0, []
                if len(status) == 1:
                    base = k("status", status[0])
                else:
                    base = temporario()
                    self.r.zunionstore(base, [k("status", s) for s in status])
            else:
                base = k("docs")
            extras = ([k("proc", procedimento)] if procedimento else []) + ([k("mun", municipio)] if municipio else [])
            if extras:
                inter = temporario()
                self.r.zinterstore(inter, {base: 1, **{e: 0 for e in extras}})
                base = inter
            for t in temporarios:
                self.r.expire(t, 60)
            mn = ts_de if ts_de is not None else "-inf"
            mx = ts_ate if ts_ate is not None else "+inf"
            # posições (rank) do período no conjunto: ZRANGE por posição é O(log N), enquanto LIMIT com
            # deslocamento faria o Redis pular os elementos um a um
            n = self.r.zcount(base, mn, mx)
            if crescente:
                antes = self.r.zcount(base, "-inf", f"({mn}") if ts_de is not None else 0
            else:
                antes = self.r.zcount(base, f"({mx}", "+inf") if ts_ate is not None else 0
            inicio = (pagina - 1) * tamanho

            def faixa(desloc: int, num: int) -> list[str]:
                num = min(num, n - desloc)
                if num <= 0:
                    return []
                ini, fim = antes + desloc, antes + desloc + num - 1
                return self.r.zrange(base, ini, fim) if crescente else self.r.zrevrange(base, ini, fim)

            if filtro is None:
                return n, self.resumos(faixa(inicio, tamanho))
            total, pagina_uuids, desloc = 0, [], 0
            while uuids := faixa(desloc, bloco):
                desloc += len(uuids)
                for u, linha in zip(uuids, self.r.hmget(k("busca"), uuids)):
                    if linha is not None and filtro(_campos_busca(linha)):
                        if inicio <= total < inicio + tamanho:
                            pagina_uuids.append(u)
                        total += 1
            return total, self.resumos(pagina_uuids)
        finally:
            if temporarios:
                self.r.delete(*temporarios)

    def por_status(self) -> dict[str, int]:
        pipe = self.r.pipeline()
        for s in STATUS_DOCUMENTO:
            pipe.zcard(self._k("status", s))
        return {s: n for s, n in zip(STATUS_DOCUMENTO, pipe.execute()) if n}

    def opcoes(self, nome: str) -> list[dict[str, Any]]:
        """Valores de procedimento ('proc') ou município ('mun') presentes, com a quantidade de cada."""
        return [{"nome": n, "total": int(t)} for n, t in sorted(self.r.hgetall(self._k("opcoes", nome)).items())
                if int(t) > 0]

    # ------------------------------------------------------------- manutenção
    def documentos_no_bucket(self) -> Iterator[str]:
        for chave in self.store.listar("dados/documentos/"):
            if chave.endswith(".json"):
                yield chave.rsplit("/", 1)[-1][: -len(".json")]

    def iterar_documentos(self, paralelismo: int = LEITURA_PARALELA) -> Iterator[Documento]:
        """Todos os documentos do bucket, lidos em paralelo e em blocos (memória constante)."""
        with ThreadPoolExecutor(paralelismo) as ex:
            for uuids in _em_blocos(self.documentos_no_bucket(), paralelismo * 64):
                for doc in ex.map(self.obter, uuids):
                    if doc is not None:
                        yield doc

    def reconstruir_indice(self, paralelismo: int = LEITURA_PARALELA) -> dict[str, int]:
        """Apaga o índice (as travas ficam) e o refaz a partir do bucket."""
        apagar = [c for c in self.r.scan_iter(match=f"{self.p}:*", count=1000)
                  if not c.startswith(f"{self.p}:trava:")]
        for bloco in _em_blocos(apagar, 1000):
            self.r.delete(*bloco)
        lotes = 0
        for chave in self.store.listar("dados/lotes/"):
            if chave.endswith(".json"):
                self._indexar_lote(Lote.model_validate(atualizar_formato(json.loads(self.store.ler(chave)))))
                lotes += 1
        docs = 0
        ultimo: dict[str, datetime] = {}
        for doc in self.iterar_documentos(paralelismo):
            self.indexar(doc, atualizar_fim=False)
            for lote in doc.lote_uuids():
                ultimo[lote] = max(ultimo.get(lote, doc.atualizado_em), doc.atualizado_em)
            docs += 1
        for lote, momento in ultimo.items():
            self._atualizar_fim_lote(lote, momento)
        return {"lotes": lotes, "documentos": docs}


def conectar_redis(url: str) -> Redis:
    if url.startswith("memoria://"):  # testes e desenvolvimento sem Redis (mesmo processo)
        import fakeredis

        return fakeredis.FakeRedis(decode_responses=True)
    return Redis.from_url(url, decode_responses=True)


@lru_cache
def repositorio() -> Repositorio:
    from .publicacao import apos_salvar

    cfg = config()
    return Repositorio(armazenamento(), conectar_redis(cfg.redis_url), cfg.redis_prefixo, cfg.trava_segundos,
                       apos_salvar=apos_salvar)
