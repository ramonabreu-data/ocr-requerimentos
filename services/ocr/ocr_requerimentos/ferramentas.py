"""Ferramentas de manutenção. Uso: python -m ocr_requerimentos.ferramentas <comando>

  reconstruir-indice        refaz o índice do Redis lendo todos os JSONs do bucket
  acuracia [--saida PASTA]  análises de acurácia do OCR sobre os requerimentos validados (CSV)
  json-schema PASTA         grava o JSON Schema dos arquivos (documento, páginas, lote, padrão do SIGA)
  publicar-siga             reenvia ao bucket do SIGA todos os validados e regera o consolidado
  carga-sintetica N         grava N documentos sintéticos e mede as consultas da API (só em ambiente de teste)
  numerar                   dá número de registro (REQ-AAAA-NNNNNN) aos documentos gravados antes da numeração"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
import time
import uuid as _uuid
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from .modelos import (
    ArquivoOriginal,
    Campo,
    Documento,
    LeituraOriginalOcr,
    Lote,
    PaginasDocumento,
    Requerimento,
    Validacao,
    VinculoLote,
    agora,
)
from .repositorio import Repositorio, repositorio


# ----------------------------------------------------------------- acurácia (antes: views do banco)
COLUNAS_CAMPO = ["versao_pipeline", "campo", "conferidos", "corrigidos", "nao_lidos", "pct_acerto",
                 "confianca_media_acertos", "confianca_media_corrigidos"]
COLUNAS_FAIXA = ["versao_pipeline", "faixa_confianca", "conferidos", "corrigidos", "pct_acerto"]


def _faixa(conf: float) -> str:
    if conf < 50:
        return "00-49"
    if conf < 70:
        return "50-69"
    if conf < 80:
        return "70-79"
    if conf < 90:
        return "80-89"
    return "90-100"


def _media(v: list[float]) -> float | None:
    return round(sum(v) / len(v), 1) if v else None


def acuracia(docs: Iterable[Documento]) -> tuple[list[dict], list[dict]]:
    """Sobre requerimentos validados, compara a leitura original do OCR com o valor final de cada campo:
    (1) quanto cada campo precisa de correção, por versão do pipeline; (2) acerto por faixa de confiança,
    base para ajustar LIMIAR_CONFIANCA. Conta os campos lidos pelo OCR e os incluídos na revisão."""
    por_campo: dict[tuple[str, str], dict] = defaultdict(lambda: {"n": 0, "corr": 0, "nao_lidos": 0,
                                                                   "conf_ok": [], "conf_corr": []})
    por_faixa: dict[tuple[str, str], dict] = defaultdict(lambda: {"n": 0, "corr": 0})
    for d in docs:
        r, versao = d.requerimento, d.leitura.versao_pipeline
        if r is None or versao is None or r.validacao.situacao != "validado":
            continue
        for c in r.campos:
            original = c.leitura_original_ocr
            valor_ocr = original.valor_lido if original else None
            conf_ocr = original.confianca_ocr if original else None
            if valor_ocr is None and not c.corrigido_manualmente:
                continue
            g = por_campo[(versao, c.campo)]
            g["n"] += 1
            if c.corrigido_manualmente:
                g["corr"] += 1
                g["nao_lidos"] += valor_ocr is None
                if conf_ocr is not None:
                    g["conf_corr"].append(conf_ocr)
            elif conf_ocr is not None:
                g["conf_ok"].append(conf_ocr)
            if conf_ocr is not None:
                f = por_faixa[(versao, _faixa(conf_ocr))]
                f["n"] += 1
                f["corr"] += c.corrigido_manualmente
    campos = [
        {"versao_pipeline": v, "campo": campo, "conferidos": g["n"], "corrigidos": g["corr"],
         "nao_lidos": g["nao_lidos"], "pct_acerto": round(100 * (g["n"] - g["corr"]) / g["n"], 1),
         "confianca_media_acertos": _media(g["conf_ok"]), "confianca_media_corrigidos": _media(g["conf_corr"])}
        for (v, campo), g in sorted(por_campo.items())
    ]
    faixas = [
        {"versao_pipeline": v, "faixa_confianca": faixa, "conferidos": f["n"], "corrigidos": f["corr"],
         "pct_acerto": round(100 * (f["n"] - f["corr"]) / f["n"], 1)}
        for (v, faixa), f in sorted(por_faixa.items())
    ]
    return campos, faixas


def _csv(linhas: list[dict], colunas: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, colunas, delimiter=";")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue()


# ----------------------------------------------------------------- JSON Schema
def gravar_json_schema(pasta: Path) -> list[Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    saida = []
    from .publicacao import ConsolidadoSiga, RequerimentoSiga

    for nome, modelo in (("documento", Documento), ("paginas", PaginasDocumento), ("lote", Lote),
                         ("siga-requerimento", RequerimentoSiga), ("siga-requerimentos", ConsolidadoSiga)):
        p = pasta / f"{nome}.schema.json"
        p.write_text(json.dumps(modelo.model_json_schema(by_alias=True), ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
        saida.append(p)
    return saida


# ----------------------------------------------------------------- carga sintética
NOMES = ["Maria das Graças Sousa", "José Pereira Lima", "João da Silva", "Ana Beatriz Rocha", "Francisco Alves",
         "Antônia Ferreira", "Raimundo Nonato Costa", "Luíza Carvalho", "Pedro Henrique Araújo", "Cícera Gomes"]
MUNICIPIOS = ["Teresina", "Altos", "Campo Maior", "Picos", "Parnaíba", "Floriano", "Uruçuí", "Bom Jesus",
              "Corrente", "Piripiri", "Oeiras", "São Raimundo Nonato"]
PROCEDIMENTOS = ["Regularização de Poço Tubular", "Outorga de Direito de Uso", "Outorga Preventiva",
                 "Renovação de Outorga de Direito de Uso"]
STATUS_CARGA = ["extraido"] * 4 + ["revisao"] * 3 + ["validado"] * 2 + ["erro"]


def _documento_sintetico(i: int, lote_uuid: str, rnd: random.Random) -> Documento:
    status = rnd.choice(STATUS_CARGA)
    cpf = "".join(str(rnd.randint(0, 9)) for _ in range(11))
    cpf_fmt = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
    conf = round(rnd.uniform(40, 100), 2)
    req = None
    if status != "erro":
        req = Requerimento(
            requerente_nome=rnd.choice(NOMES), cpf_cnpj=cpf_fmt, tipo_pessoa="F",
            procedimento=rnd.choice(PROCEDIMENTOS), municipio=rnd.choice(MUNICIPIOS), localidade="Zona rural",
            latitude=-rnd.uniform(3, 10), longitude=-rnd.uniform(41, 45),
            data_documento=date(2026, 1, 1) + timedelta(days=rnd.randint(0, 280)),
            confianca_geral=conf, pendencias=["Latitude: conferir"] if status == "revisao" else [],
            validacao=Validacao(situacao="validado", validado_em=agora()) if status == "validado" else Validacao(),
            campos=[Campo(campo="cpf_cnpj", valor_atual=cpf_fmt, valor_atual_normalizado=cpf_fmt, confianca_atual=conf,
                          leitura_original_ocr=LeituraOriginalOcr(valor_lido=cpf_fmt, confianca_ocr=conf))],
        )
    sha = _uuid.uuid4().hex + _uuid.uuid4().hex
    u = str(_uuid.uuid4())
    return Documento(
        uuid=u, status=status, erro="formato não suportado" if status == "erro" else None,
        arquivo=ArquivoOriginal(nome_original=f"sintetico-{i:07d}.pdf", chave=f"documentos/{u}/original.pdf",
                                content_type="application/pdf", tamanho_bytes=0, sha256=sha),
        lote_origem_uuid=lote_uuid, lotes=[VinculoLote(lote_uuid=lote_uuid)], requerimento=req,
    )


def carga_sintetica(repo: Repositorio, n: int, por_lote: int = 1000, paralelismo: int = 16, semente: int = 1) -> dict:
    rnd = random.Random(semente)
    inicio = time.monotonic()
    lotes: list[str] = []
    docs = []
    for i in range(n):
        if i % por_lote == 0:
            lote = Lote(uuid=str(_uuid.uuid4()), nome=f"Carga sintética {len(lotes) + 1}", origem="upload")
            repo.salvar_lote(lote)
            lotes.append(lote.uuid)
        docs.append(_documento_sintetico(i, lotes[-1], rnd))

    def gravar(d: Documento) -> None:
        with repo.travar(d.uuid):
            repo.salvar(d)

    with ThreadPoolExecutor(paralelismo) as ex:
        list(ex.map(gravar, docs))
    gravacao = time.monotonic() - inicio

    def medir(rotulo: str, **kw) -> tuple[str, float, int]:
        t = time.monotonic()
        total, _ = repo.consultar(**kw)
        return rotulo, round((time.monotonic() - t) * 1000, 1), total

    medidas = [
        medir("lista geral, página 1"),
        medir("situação = revisao", status=["revisao"]),
        medir("município + procedimento", municipio="Teresina", procedimento="Outorga Preventiva"),
        medir("busca por nome (varre candidatos)", filtro=lambda r: "jose" in r["_requerente"]),
        medir("busca por CPF parcial (varre tudo)", filtro=lambda r: "123" in r["_cpf"]),
    ]
    t = time.monotonic()
    repo.contagem_lote(lotes[0])
    medidas.append(("contadores de um lote", round((time.monotonic() - t) * 1000, 1), 0))
    return {"documentos": n, "lotes": len(lotes), "gravacao_s": round(gravacao, 1),
            "docs_por_segundo": round(n / gravacao, 1) if gravacao else None,
            "consultas_ms": [{"consulta": c, "ms": ms, "total": tot} for c, ms, tot in medidas]}


def _validados(repo: Repositorio, bloco: int = 1000):
    pagina = 1
    while True:
        _, itens = repo.consultar(status=["validado"], crescente=True, pagina=pagina, tamanho=bloco)
        if itens:
            yield [r["uuid"] for r in itens]
        if len(itens) < bloco:
            return
        pagina += 1


# ----------------------------------------------------------------- numeração de documentos antigos
def numerar(repo: Repositorio) -> dict[str, int]:
    """Dá número de registro aos documentos gravados antes da numeração, do mais antigo ao mais novo, pelo
    ano em que chegaram. As partes de um arquivo dividido levam o número dele com -1, -2... (na ordem das
    partes). Os que já têm número ficam como estão; pode rodar de novo sem efeito."""
    from .pipeline.persistencia import FUSO

    # só o necessário de cada documento sem número (memória pequena mesmo com muitos documentos)
    sem: list[tuple[datetime, str, str | None]] = sorted(
        (d.criado_em, d.uuid, d.documento_pai_uuid) for d in repo.iterar_documentos() if not d.numero
    )
    numerados = {"documentos": 0, "partes": 0}
    for partes in (False, True):  # os arquivos primeiro: as partes dependem do número deles
        for criado_em, u, pai in sem:
            if (pai is not None) != partes:
                continue
            with repo.travar(u):
                d = repo.obter(u)
                if d is None or d.numero:
                    continue
                origem = repo.obter(pai) if pai else None
                if origem is not None and origem.numero and u in origem.partes:
                    d.numero = f"{origem.numero}-{origem.partes.index(u) + 1}"
                else:
                    d.numero = repo.proximo_numero(criado_em.astimezone(FUSO).year)
                repo.salvar(d)
            numerados["partes" if partes else "documentos"] += 1
    return numerados


# ----------------------------------------------------------------- linha de comando
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ocr_requerimentos.ferramentas", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="comando", required=True)
    sub.add_parser("reconstruir-indice")
    sub.add_parser("publicar-siga")
    a = sub.add_parser("acuracia")
    a.add_argument("--saida", type=Path, help="pasta para acuracia_campo.csv e calibracao_confianca.csv")
    j = sub.add_parser("json-schema")
    j.add_argument("pasta", type=Path)
    sub.add_parser("numerar")
    c = sub.add_parser("carga-sintetica")
    c.add_argument("n", type=int)
    c.add_argument("--paralelismo", type=int, default=16)
    c.add_argument("--confirmo-ambiente-de-teste", action="store_true",
                   help="obrigatório: grava documentos falsos no bucket e no índice configurados")
    args = ap.parse_args(argv)

    if args.comando == "reconstruir-indice":
        t = time.monotonic()
        res = repositorio().reconstruir_indice()
        print(json.dumps({**res, "segundos": round(time.monotonic() - t, 1)}, ensure_ascii=False))
    elif args.comando == "publicar-siga":
        from .publicacao import destino, gravar_consolidado, publicar_documento

        if destino() is None:
            print("publicação para o SIGA desligada: defina SIGA_S3_BUCKET", file=sys.stderr)
            return 2
        repo = repositorio()
        n = 0
        for uuids in _validados(repo):
            for u in uuids:
                publicar_documento(u, repo)
                n += 1
        print(json.dumps({"publicados": n, "consolidado": gravar_consolidado(repo)}, ensure_ascii=False))
    elif args.comando == "acuracia":
        campos, faixas = acuracia(repositorio().iterar_documentos())
        if args.saida:
            args.saida.mkdir(parents=True, exist_ok=True)
            (args.saida / "acuracia_campo.csv").write_text(_csv(campos, COLUNAS_CAMPO), encoding="utf-8")
            (args.saida / "calibracao_confianca.csv").write_text(_csv(faixas, COLUNAS_FAIXA), encoding="utf-8")
            print(f"gravado em {args.saida}")
        else:
            print(_csv(campos, COLUNAS_CAMPO))
            print(_csv(faixas, COLUNAS_FAIXA))
    elif args.comando == "numerar":
        print(json.dumps(numerar(repositorio()), ensure_ascii=False))
    elif args.comando == "json-schema":
        for p in gravar_json_schema(args.pasta):
            print(p)
    elif args.comando == "carga-sintetica":
        if not args.confirmo_ambiente_de_teste:
            print("recusado: grava documentos falsos. Rode só em ambiente de teste, com "
                  "--confirmo-ambiente-de-teste.", file=sys.stderr)
            return 2
        print(json.dumps(carga_sintetica(repositorio(), args.n, paralelismo=args.paralelismo),
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
