"""Liga o pipeline ao repositório de JSON: processa um documento, grava resultados, divide PDFs com vários
requerimentos e reaplica a validação depois de correções manuais.

As funções que alteram um documento em memória (`gravar_resultado`, `aplicar_correcoes`,
`validar_documento`) não gravam: quem chama segura `repo.travar(uuid)`, relê o documento e chama
`repo.salvar` no fim (ver api/main.py). `registrar_documento`, `vincular_lote` e `processar_documento`
cuidam das próprias travas."""
from __future__ import annotations

import hashlib
import logging
import time
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import lru_cache
from typing import Any

import pymupdf

from ..armazenamento import Armazenamento
from ..config import config
from ..extracao.finalidades import POR_CHAVE
from ..extracao.parser import BlocoFinalidade, ExtracaoBruta, LinhaIrrigacao
from ..extracao.referencias import ReferenciasEstaticas, SigaReferencias, referencias_dominio
from ..extracao.tipos import CampoBruto
from ..extracao.validacao import CampoValidado, Referencias, Resultado, validar
from ..imagem.ocr import criar_motor
from ..modelos import (
    ArquivoOriginal,
    Assinatura,
    Campo,
    Documento,
    Finalidade,
    LeituraOriginalOcr,
    LinhaIrrigacao as LinhaIrrigacaoJson,
    LocalNaFolha,
    PaginaLida,
    PaginasDocumento,
    QrCode,
    Requerimento,
    Revisao,
    TextoPagina,
    Validacao,
    ValidacaoCampo,
    VinculoLote,
    agora,
)
from ..repositorio import Repositorio, repositorio
from . import VERSAO_PIPELINE
from .extracao import ResultadoArquivo, Segmento, imagem_jpeg, palavras_json, processar_arquivo
from .leitura import ArquivoInvalido

log = logging.getLogger(__name__)
FUSO = ZoneInfo("America/Fortaleza")  # o ano do número de registro é o do recebimento no Piauí


class ConflitoVersao(Exception):
    """O requerimento mudou (outra revisão, validação ou releitura) depois de lido por quem está gravando."""


CAMPOS_SIMPLES = (
    "requerente_nome", "cpf_cnpj", "procedimento", "tipo_intervencao", "municipio", "localidade",
    "latitude", "longitude", "descricao_usos", "assinante_nome", "data_documento",
)


@lru_cache
def referencias_padrao() -> Referencias:
    if config().referencias == "estaticas":
        return ReferenciasEstaticas(**referencias_dominio())
    from sqlalchemy import create_engine

    eng = create_engine(config().siga_database_url, pool_pre_ping=True, future=True)
    return SigaReferencias(eng, uf=config().uf, srid_entrada=config().srid)


def sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def extensao(nome: str, content_type: str) -> str:
    nome = nome.lower()
    for ext in (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif"):
        if nome.endswith(ext):
            return ext
    return {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/tiff": ".tif"}.get(
        content_type, ".bin"
    )


@dataclass
class ResultadoRegistro:
    documento: Documento
    duplicado: bool


def registrar_documento(
    conteudo: bytes,
    nome: str,
    content_type: str,
    *,
    lote_uuid: str | None = None,
    usuario_id: int | None = None,
    pai_uuid: str | None = None,
    pagina_inicial: int | None = None,
    validar_ao_ler: bool = False,
    numero: str | None = None,
    repo: Repositorio | None = None,
) -> ResultadoRegistro:
    """Grava o arquivo no armazenamento e cria o documento. Arquivo repetido (mesmo SHA-256) não é
    duplicado: devolve o documento existente, que passa a fazer parte também de `lote_uuid` sem mudar de
    situação nem de número (`validar_ao_ler` só vale para documentos novos).

    O documento novo recebe o próximo número de registro do ano, ou `numero` (as partes de um arquivo
    dividido levam o número dele com -1, -2...)."""
    repo = repo or repositorio()
    h = sha256(conteudo)
    with repo.travar(f"sha256:{h}"):  # dois envios simultâneos do mesmo arquivo viram um documento só
        existente = repo.uuid_por_sha256(h)
        doc = repo.obter(existente) if existente else None
        if doc is not None:
            if lote_uuid is not None:
                doc = vincular_lote(lote_uuid, doc.uuid, nome, repo=repo)
            return ResultadoRegistro(doc, True)
        u = str(_uuid.uuid4())
        chave = f"documentos/{u}/original{extensao(nome, content_type)}"
        ct = content_type or "application/octet-stream"
        repo.store.salvar(chave, conteudo, ct)
        doc = Documento(
            uuid=u, status="recebido",
            arquivo=ArquivoOriginal(nome_original=nome, chave=chave, content_type=ct, tamanho_bytes=len(conteudo),
                                    sha256=h),
            lote_origem_uuid=lote_uuid,
            lotes=[VinculoLote(lote_uuid=lote_uuid, nome_arquivo=nome)] if lote_uuid else [],
            documento_pai_uuid=pai_uuid, pagina_inicial=pagina_inicial, criado_por_id=usuario_id,
            validar_ao_ler=validar_ao_ler,
            numero=numero or repo.proximo_numero(datetime.now(FUSO).year),
        )
        with repo.travar(u):
            doc = repo.salvar(doc)
        return ResultadoRegistro(doc, False)


def vincular_lote(lote_uuid: str, documento_uuid: str, nome: str | None = None,
                  repo: Repositorio | None = None) -> Documento:
    """Põe o documento no lote, com as partes dele se já foi dividido."""
    repo = repo or repositorio()
    with repo.travar(documento_uuid):
        doc = repo.obter(documento_uuid)
        if lote_uuid not in doc.lote_uuids():
            doc.lotes.append(VinculoLote(lote_uuid=lote_uuid, nome_arquivo=nome or doc.arquivo.nome_original))
            doc = repo.salvar(doc)
    for parte in doc.partes:
        vincular_lote(lote_uuid, parte, repo=repo)
    return doc


# ----------------------------------------------------------------- gravação do resultado
def _r(v: float | None, casas: int) -> float | None:
    return None if v is None else round(float(v), casas)


Chave = tuple[str, int | None]
LeituraOcr = dict[Chave, LeituraOriginalOcr | None]


def _campo(cv: CampoValidado, indice: int | None = None, manual: bool = False, ocr: LeituraOcr | None = None) -> Campo:
    """`ocr`: leitura original dos campos já gravados (correção manual); sem ela, cv é a própria leitura."""
    if ocr is not None and (cv.campo, indice) in ocr:
        original = ocr[(cv.campo, indice)]
    elif manual:
        original = None  # incluído na revisão: o OCR não leu nada aqui
    else:
        original = LeituraOriginalOcr(valor_lido=cv.valor_bruto, confianca_ocr=_r(cv.confianca, 2))
    return Campo(
        campo=cv.campo, indice=indice, valor_atual=cv.valor_bruto, valor_atual_normalizado=cv.valor_normalizado,
        confianca_atual=_r(cv.confianca, 2), corrigido_manualmente=manual, leitura_original_ocr=original,
        local_na_folha=LocalNaFolha(pagina=cv.pagina, caixa=[round(v, 1) for v in cv.bbox] if cv.bbox else None),
        validacao=ValidacaoCampo(valido=cv.valido, obrigatorio=cv.obrigatorio, mensagem=cv.mensagem),
    )


def gravar_resultado(
    doc: Documento, r: Resultado, manuais: set[Chave] | None = None, preservar_ocr: bool = False,
) -> Requerimento:
    """Põe a extração validada no documento. `preservar_ocr=True` (correções) mantém a leitura original dos
    campos já existentes; False (leitura nova) usa o próprio resultado como leitura original."""
    manuais = manuais or set()
    antigo = doc.requerimento
    ocr: LeituraOcr | None = (
        {(c.campo, c.indice): c.leitura_original_ocr for c in antigo.campos} if preservar_ocr and antigo else None
    )
    c = r.campos
    campos = [_campo(c[nome], manual=(nome, None) in manuais, ocr=ocr) for nome in CAMPOS_SIMPLES]
    detalhes = {d.indice: d for d in r.detalhes}
    finalidades = []
    for i, f in enumerate(r.finalidades):
        campos.append(_campo(f, i, ("finalidade", i) in manuais, ocr))
        det = detalhes.get(i)
        finalidades.append(Finalidade(
            texto=f.valor_normalizado or "", tipo_finalidade_id=f.ref_id, confianca=_r(f.confianca, 2),
            valido=f.valido, chave=det.chave if det else None, detalhes=det.dados if det else None,
        ))
    for det in r.detalhes:
        for cv in det.campos:
            campos.append(_campo(cv, cv.item, (cv.campo, cv.item) in manuais, ocr))
    irrigacao = []
    for it in r.irrigacao:
        for sub in (it.sistema, it.area, it.cultura):
            campos.append(_campo(sub, it.ordem, (sub.campo, it.ordem) in manuais, ocr))
        irrigacao.append(LinhaIrrigacaoJson(
            ordem=it.ordem, sistema=it.sistema.valor_normalizado or "", sistema_id=it.sistema.ref_id,
            area_ha=_r(it.area_ha, 4), cultura=it.cultura.valor_normalizado or "", cultura_id=it.cultura.ref_id,
            confianca=_r(it.confianca, 2), valido=it.valido,
        ))
    validado = antigo is not None and antigo.validacao.situacao == "validado"
    req = Requerimento(
        requerente_nome=c["requerente_nome"].valor_normalizado,
        cpf_cnpj=c["cpf_cnpj"].valor_normalizado,
        tipo_pessoa=r.tipo_pessoa,
        pessoa_id=r.pessoa_id,
        procedimento=c["procedimento"].valor_normalizado,
        procedimento_id=c["procedimento"].ref_id,
        tipo_intervencao=c["tipo_intervencao"].valor_normalizado,
        tipo_intervencao_id=c["tipo_intervencao"].ref_id,
        municipio=c["municipio"].valor_normalizado,
        municipio_id=c["municipio"].ref_id,
        localidade=c["localidade"].valor_normalizado or None,
        latitude_texto=c["latitude"].valor_bruto or None,
        longitude_texto=c["longitude"].valor_bruto or None,
        latitude=_r(r.latitude, 7),
        longitude=_r(r.longitude, 7),
        descricao_usos=c["descricao_usos"].valor_normalizado,
        assinante_nome=c["assinante_nome"].valor_normalizado,
        data_documento=r.data_documento,
        finalidades=finalidades,
        irrigacao=irrigacao,
        confianca_geral=_r(r.confianca_geral, 2),
        pendencias=list(r.pendencias),
        avisos=list(r.avisos),
        validacao=antigo.validacao if validado else Validacao(),
        versao=(antigo.versao if antigo else 0) + 1,
        campos=campos,
        criado_em=antigo.criado_em if antigo else agora(),
    )
    doc.requerimento = req
    if doc.status != "validado":
        # conferência obrigatória: segue na revisão até uma pessoa validar, mesmo depois de corrigido
        doc.status = "revisao" if doc.conferencia_obrigatoria else r.status
    return req


def config_extracao() -> dict[str, Any]:
    cfg = config()
    return {
        "motor_ocr": cfg.motor_ocr, "idioma_tesseract": cfg.idioma_tesseract, "limiar_confianca": cfg.limiar_confianca,
        "remover_tinta_azul": cfg.remover_tinta_azul, "confiar_texto_scanner": cfg.confiar_texto_scanner,
        "conferir_numeros": cfg.conferir_numeros, "referencias": cfg.referencias,
    }


def _gravar_segmento(doc: Documento, seg: Segmento, res: ResultadoArquivo, repo: Repositorio) -> None:
    store: Armazenamento = repo.store
    doc.leitura.versao_pipeline = VERSAO_PIPELINE
    doc.leitura.configuracao = config_extracao()
    doc.leitura.tipo_entrada = res.leitura.tipo_entrada
    metodo = "ocr" if any(p.metodo == "ocr" for p in seg.paginas) else "texto_nativo"
    doc.leitura.paginas = len(seg.paginas)
    doc.assinatura = Assinatura(tipo=seg.assinatura.tipo, detalhes=seg.assinatura.detalhes)
    doc.qr_code = None
    if seg.qrcodes:
        q = seg.qrcodes[0]
        doc.qr_code = QrCode(conteudo=q.bruto)
        if q.processo_uuid:
            try:
                doc.qr_code.processo_uuid = str(_uuid.UUID(q.processo_uuid))
            except ValueError:
                pass
            refs = referencias_padrao()
            ref = refs.processo_por_uuid(q.processo_uuid) if hasattr(refs, "processo_por_uuid") else None
            doc.qr_code.processo_id = ref.id if ref else None
        metodo = "qrcode+" + metodo
    doc.leitura.metodo_extracao = metodo

    doc.paginas_lidas = []
    textos = []
    for k, p in enumerate(seg.paginas, start=1):
        chave = f"documentos/{doc.uuid}/paginas/{k}.jpg"
        if p.imagem is not None:
            store.salvar(chave, imagem_jpeg(p.imagem), "image/jpeg")
        doc.paginas_lidas.append(PaginaLida(
            numero=k, largura=p.largura, altura=p.altura, imagem_chave=chave if p.imagem is not None else None,
            angulo_correcao=round(p.angulo_correcao, 2), metodo=p.metodo, motor_ocr=p.motor,
            confianca_media=_r(p.confianca_media, 2),
        ))
        textos.append(TextoPagina(numero=k, texto=p.texto, palavras=[{**w, "p": k} for w in palavras_json(p)]))
    repo.salvar_paginas(PaginasDocumento(documento_uuid=doc.uuid, paginas=textos))
    doc.conferencia_obrigatoria = False  # recalculada para a leitura nova
    gravar_resultado(doc, seg.resultado)
    marcar_conferencia_obrigatoria(doc)
    # páginas do segmento renumeradas a partir de 1 no documento filho
    offset = seg.paginas[0].numero - 1
    if offset and doc.requerimento:
        for c in doc.requerimento.campos:
            if c.local_na_folha.pagina:
                c.local_na_folha.pagina -= offset


def _sub_arquivo(conteudo: bytes, tipo_entrada: str, numeros: list[int], seg: Segmento) -> tuple[bytes, str]:
    if tipo_entrada.startswith("pdf"):
        orig = pymupdf.open(stream=conteudo, filetype="pdf")
        novo = pymupdf.open()
        for n in numeros:
            novo.insert_pdf(orig, from_page=n - 1, to_page=n - 1)
        return novo.tobytes(garbage=3, deflate=True), "application/pdf"
    novo = pymupdf.open()
    for p in seg.paginas:
        jpg = imagem_jpeg(p.imagem, 90)
        pag = novo.new_page(width=p.largura * 72 / 300, height=p.altura * 72 / 300)
        pag.insert_image(pag.rect, stream=jpg)
    return novo.tobytes(), "application/pdf"


def _marcar_erro(repo: Repositorio, u: str, erro: str, inicio: float) -> Documento:
    with repo.travar(u):
        doc = repo.obter(u)
        doc.status, doc.erro = "erro", erro
        doc.leitura.duracao_ms = int((time.monotonic() - inicio) * 1000)
        return repo.salvar(doc)


def processar_documento(documento_uuid: str, repo: Repositorio | None = None) -> Documento:
    """Lê o documento. O OCR roda sem trava; a trava só cobre as gravações, e o documento é relido antes
    de gravar o resultado (um reenvio pode tê-lo posto em outro lote enquanto o OCR rodava)."""
    repo = repo or repositorio()
    cfg = config()
    with repo.travar(documento_uuid):
        doc = repo.obter(documento_uuid)
        if doc is None:
            raise ValueError(f"documento {documento_uuid} não existe")
        doc.status = "processando"
        doc.leitura.tentativas += 1
        doc.erro = None
        doc = repo.salvar(doc)
    inicio = time.monotonic()
    try:
        conteudo = repo.store.ler(doc.arquivo.chave)
        res = processar_arquivo(
            conteudo, criar_motor(cfg.motor_ocr, cfg.idioma_tesseract), referencias_padrao(),
            doc.arquivo.nome_original, doc.arquivo.content_type, limiar=cfg.limiar_confianca,
            conferir_numeros=cfg.conferir_numeros, remover_azul=cfg.remover_tinta_azul,
            confiar_texto_scanner=cfg.confiar_texto_scanner, dividir=doc.documento_pai_uuid is None,
        )
        with repo.travar(documento_uuid):
            doc = repo.obter(documento_uuid)
            if len(res.segmentos) == 1:
                anteriores = _correcoes_anteriores(doc)
                _gravar_segmento(doc, res.segmentos[0], res, repo)
                if anteriores:
                    _reaplicar_correcoes(doc, anteriores)
                validar_no_envio(doc)
            else:
                _dividir(doc, conteudo, res, repo, inicio)
            doc.leitura.duracao_ms = int((time.monotonic() - inicio) * 1000)
            return repo.salvar(doc)
    except ArquivoInvalido as e:
        return _marcar_erro(repo, documento_uuid, str(e), inicio)
    except Exception as e:  # noqa: BLE001
        log.exception("falha ao processar documento %s", documento_uuid)
        return _marcar_erro(repo, documento_uuid, f"{type(e).__name__}: {e}", inicio)


def _dividir(doc: Documento, conteudo: bytes, res: ResultadoArquivo, repo: Repositorio, inicio: float) -> None:
    """Arquivo com vários requerimentos: cada um vira um documento (parte), nos mesmos lotes do original."""
    doc.leitura.versao_pipeline = VERSAO_PIPELINE
    doc.leitura.configuracao = config_extracao()
    doc.leitura.tipo_entrada = res.leitura.tipo_entrada
    doc.leitura.paginas = len(res.leitura.paginas)
    doc.status = "dividido"
    base = doc.arquivo.nome_original.rsplit(".", 1)[0]
    for i, seg in enumerate(res.segmentos, start=1):
        numeros = [p.numero for p in seg.paginas]
        sub, ct = _sub_arquivo(conteudo, res.leitura.tipo_entrada, numeros, seg)
        nome = f"{base} - parte {i} (pág. {numeros[0]}{'-' + str(numeros[-1]) if len(numeros) > 1 else ''}).pdf"
        reg = registrar_documento(
            sub, nome, ct, lote_uuid=doc.lote_origem_uuid, usuario_id=doc.criado_por_id, pai_uuid=doc.uuid,
            pagina_inicial=numeros[0], validar_ao_ler=doc.validar_ao_ler,
            numero=f"{doc.numero}-{i}" if doc.numero else None, repo=repo,
        )
        for lote in doc.lote_uuids():  # as partes acompanham o original em todos os lotes
            vincular_lote(lote, reg.documento.uuid, nome, repo=repo)
        if reg.documento.uuid not in doc.partes:
            doc.partes.append(reg.documento.uuid)
        if reg.duplicado:
            continue
        with repo.travar(reg.documento.uuid):
            filho = repo.obter(reg.documento.uuid)
            filho.status = "processando"
            filho.leitura.tentativas = 1
            _gravar_segmento(filho, seg, res, repo)
            validar_no_envio(filho)
            filho.leitura.duracao_ms = int((time.monotonic() - inicio) * 1000)
            repo.salvar(filho)


def _correcoes_anteriores(doc: Documento) -> tuple[dict[Chave, str], set[Chave]] | None:
    """Valores gravados antes da releitura e quais foram corrigidos na revisão (None se nenhum). O documento
    foi relido sob trava, então uma correção salva enquanto o OCR rodava não se perde."""
    req = doc.requerimento
    if req is None:
        return None
    manuais = {(c.campo, c.indice) for c in req.campos if c.corrigido_manualmente}
    if not manuais:
        return None
    return {(c.campo, c.indice): c.valor_atual or "" for c in req.campos}, manuais


def _reaplicar_correcoes(doc: Documento, anteriores: tuple[dict[Chave, str], set[Chave]]) -> None:
    """Depois de reler o documento, devolve o que o revisor tinha corrigido. Grupos em lista (finalidades,
    irrigação, itens de cada finalidade) voltam inteiros como estavam, já que a correção pode ter incluído,
    removido ou reordenado linhas."""
    valores, manuais = anteriores
    correcoes: dict[str, Any] = {"campos": {k[0]: valores[k] for k in manuais if k[0] in CAMPOS_SIMPLES},
                                 "detalhes": {}}
    if any(k[0] == "finalidade" for k in manuais):
        correcoes["finalidades"] = [valores[k] for k in sorted((k for k in valores if k[0] == "finalidade"),
                                                               key=lambda k: k[1])]
    if any(k[0].startswith("irrigacao_") for k in manuais):
        ordens = sorted({k[1] for k in valores if k[0].startswith("irrigacao_")})
        correcoes["irrigacao"] = [
            {sub: valores.get((f"irrigacao_{sub}", o), "") for sub in ("sistema", "area", "cultura")} for o in ordens
        ]
    fins = {k[0].split(".", 1)[0] for k in manuais if "." in k[0]}
    novos = {(c.campo, c.indice) for c in doc.requerimento.campos}
    for nome, indice in sorted({k for k in valores.keys() | novos if k[0].split(".", 1)[0] in fins},
                               key=lambda k: (k[0], k[1] or 0)):
        texto = nome if indice is None else f"{nome}#{indice}"
        try:
            chave_detalhe(texto)
        except ValueError:  # definição da finalidade mudou desde a correção
            continue
        # item que só existe na leitura nova fica vazio e é removido, como estava na revisão
        correcoes["detalhes"][texto] = valores.get((nome, indice), "")

    aplicar_correcoes(doc, correcoes, None, auditar=False)
    doc.historico_de_revisoes.append(Revisao(
        tipo="reprocessamento",
        valor_novo=f"{len(manuais)} correção(ões) manual(is) reaplicada(s) após nova leitura",
    ))


# ----------------------------------------------------------------- correções manuais
def _bruto_de(c: Campo | None, novo: str | None = None) -> CampoBruto:
    if c is None:
        return CampoBruto(novo, conf_fixa=100.0 if novo is not None else None)
    bbox = tuple(c.local_na_folha.caixa) if c.local_na_folha.caixa else None
    pagina = c.local_na_folha.pagina
    if novo is not None:
        return CampoBruto(novo or None, conf_fixa=100.0, pagina_fixa=pagina, bbox_fixa=bbox)
    return CampoBruto(
        c.valor_atual, conf_fixa=float(c.confianca_atual or 0) if not c.corrigido_manualmente else 100.0,
        pagina_fixa=pagina, bbox_fixa=bbox,
    )


def conferir_versao(req: Requerimento, esperada: int | None) -> None:
    """Recusa a gravação de quem leu uma versão anterior (`esperada`; sem ela, aceita)."""
    if esperada is not None and req.versao != esperada:
        raise ConflitoVersao(
            "este documento foi alterado (por outra pessoa ou por uma nova leitura) depois que você o abriu; "
            "recarregue a página para ver a versão atual"
        )


def aplicar_correcoes(
    doc: Documento, correcoes: dict[str, Any], usuario_id: int | None, refs: Referencias | None = None,
    versao: int | None = None, auditar: bool = True,
) -> Requerimento:
    """correcoes = {"campos": {nome: valor}, "finalidades": [..] | None, "irrigacao": [{sistema, area, cultura}] | None}

    O valor corrigido passa pela mesma validação do OCR (com confiança 100) e cada alteração entra no
    histórico (`auditar=False` só ao reaplicar correções já registradas). ConflitoVersao se `versao` não
    for a atual. Só altera `doc` em memória: quem chama segura a trava e salva."""
    refs = refs or referencias_padrao()
    req = doc.requerimento
    if req is None:
        raise ValueError("documento ainda não tem extração")
    conferir_versao(req, versao)
    por_chave = {(c.campo, c.indice): c for c in req.campos}
    manuais = {k for k, c in por_chave.items() if c.corrigido_manualmente}
    ex = ExtracaoBruta()
    alteracoes: list[tuple[str, str | None, str | None]] = []

    novos = correcoes.get("campos") or {}
    for nome in CAMPOS_SIMPLES:
        c = por_chave.get((nome, None))
        if nome in novos and (c is None or (novos[nome] or None) != c.valor_atual):
            alteracoes.append((nome, c.valor_atual if c else None, novos[nome]))
            setattr(ex, nome, _bruto_de(c, novos[nome] or ""))
            manuais.add((nome, None))
        else:
            setattr(ex, nome, _bruto_de(c))

    antigas_fin = [por_chave[k] for k in sorted((k for k in por_chave if k[0] == "finalidade"), key=lambda k: k[1])]
    if correcoes.get("finalidades") is not None:
        manuais = {m for m in manuais if m[0] != "finalidade"}
        lista = [v for v in correcoes["finalidades"] if v and v.strip()]
        for i, v in enumerate(lista):
            antiga = antigas_fin[i] if i < len(antigas_fin) else None
            if antiga is not None and antiga.valor_atual == v:
                ex.finalidades.append(_bruto_de(antiga))
                if antiga.corrigido_manualmente:
                    manuais.add(("finalidade", i))
            else:
                ex.finalidades.append(_bruto_de(antiga, v))
                manuais.add(("finalidade", i))
        antes = " | ".join(c.valor_atual or "" for c in antigas_fin)
        depois = " | ".join(lista)
        if antes != depois:
            alteracoes.append(("finalidades", antes, depois))
    else:
        ex.finalidades = [_bruto_de(c) for c in antigas_fin]

    def linhas_atuais() -> list[LinhaIrrigacao]:
        ordens = sorted({k[1] for k in por_chave if k[0].startswith("irrigacao_")})
        return [
            LinhaIrrigacao(
                _bruto_de(por_chave.get(("irrigacao_sistema", o))),
                _bruto_de(por_chave.get(("irrigacao_area", o))),
                _bruto_de(por_chave.get(("irrigacao_cultura", o))),
                "",
            )
            for o in ordens
        ]

    if correcoes.get("irrigacao") is not None:
        manuais = {m for m in manuais if not m[0].startswith("irrigacao_")}
        atuais = linhas_atuais()
        ordens = sorted({k[1] for k in por_chave if k[0].startswith("irrigacao_")})
        for i, item in enumerate(correcoes["irrigacao"], start=1):
            if not any(str(item.get(k) or "").strip() for k in ("sistema", "area", "cultura")):
                continue
            o = ordens[i - 1] if i - 1 < len(ordens) else None
            ordem_nova = len(ex.irrigacao) + 1
            partes = []
            for sub in ("sistema", "area", "cultura"):
                novo = str(item.get(sub) or "").strip()
                c = por_chave.get((f"irrigacao_{sub}", o)) if o is not None else None
                if c is not None and c.valor_atual == novo:
                    partes.append(_bruto_de(c))
                    if c.corrigido_manualmente:
                        manuais.add((f"irrigacao_{sub}", ordem_nova))
                else:
                    partes.append(_bruto_de(c, novo))
                    manuais.add((f"irrigacao_{sub}", ordem_nova))
            ex.irrigacao.append(LinhaIrrigacao(*partes, ""))
        fmt = lambda ls: " | ".join(f"{l.sistema.valor}; {l.area.valor}; {l.cultura.valor}" for l in ls)  # noqa: E731
        if fmt(atuais) != fmt(ex.irrigacao):
            alteracoes.append(("irrigacao", fmt(atuais), fmt(ex.irrigacao)))
    else:
        ex.irrigacao = linhas_atuais()

    ex.blocos, manuais = _blocos_corrigidos(por_chave, correcoes.get("detalhes") or {}, manuais, alteracoes)

    r = validar(ex, refs, config().limiar_confianca)
    if auditar:
        for campo, antes, depois in alteracoes:
            doc.historico_de_revisoes.append(Revisao(tipo="correcao", campo=campo, valor_anterior=antes,
                                                     valor_novo=depois, usuario_id=usuario_id))
    if doc.status == "validado" and alteracoes:
        doc.status = r.status
        req.validacao = Validacao()
    return gravar_resultado(doc, r, manuais, preservar_ocr=True)


def validar_documento(doc: Documento, usuario_id: int | None, forcar: bool = False,
                      justificativa: str | None = None, versao: int | None = None,
                      modo: str = "conferencia") -> Requerimento:
    """Marca como validado (em memória; quem chama segura a trava e salva)."""
    req = doc.requerimento
    if req is None:
        raise ValueError("documento ainda não tem extração")
    conferir_versao(req, versao)
    if req.pendencias and not forcar:
        raise PermissionError("há pendências; corrija os campos ou valide com justificativa")
    if forcar and req.pendencias:
        if not (justificativa and justificativa.strip()):
            raise PermissionError("justificativa obrigatória para validar com pendências")
        doc.historico_de_revisoes.append(Revisao(
            tipo="validacao_com_pendencias", valor_anterior="; ".join(req.pendencias), valor_novo=justificativa,
            usuario_id=usuario_id,
        ))
    req.validacao = Validacao(situacao="validado", validado_por_id=usuario_id, validado_em=agora(), modo=modo)
    req.versao += 1
    req.atualizado_em = agora()
    doc.status = "validado"
    return req


JUSTIFICATIVA_ENVIO = "Enviado como já conferido: validado automaticamente ao fim da leitura."


def desconsiderar_documento(doc: Documento, usuario_id: int | None, motivo: str | None) -> None:
    """Descarta o documento na revisão: não é validado, sai das filas e não vai ao SIGA. O motivo fica no
    histórico, e `reconsiderar_documento` desfaz. Em memória, como `validar_documento`."""
    if not (motivo or "").strip():
        raise ValueError("informe o motivo para desconsiderar o documento")
    if doc.status == "validado":
        raise PermissionError("documento já validado; não pode ser desconsiderado")
    if doc.status not in ("extraido", "revisao", "erro"):
        raise ValueError(f"documento em situação '{doc.status}' não pode ser desconsiderado")
    doc.historico_de_revisoes.append(Revisao(
        tipo="desconsideracao", valor_anterior=doc.status, valor_novo=motivo.strip(), usuario_id=usuario_id,
    ))
    doc.status = "desconsiderado"
    doc.validar_ao_ler = False


def reconsiderar_documento(doc: Documento, usuario_id: int | None) -> None:
    """Devolve um documento desconsiderado à revisão, com a situação que a leitura dá (ou ao erro de leitura)."""
    if doc.status != "desconsiderado":
        raise ValueError("documento não está desconsiderado")
    req = doc.requerimento
    if req is None:
        doc.status = "erro"
    else:
        doc.status = "revisao" if req.pendencias or doc.conferencia_obrigatoria else "extraido"
    doc.historico_de_revisoes.append(Revisao(tipo="reconsideracao", valor_novo=doc.status, usuario_id=usuario_id))


def marcar_conferencia_obrigatoria(doc: Documento) -> bool:
    """Leitura com confiança geral abaixo de LIMIAR_CONFERENCIA_OBRIGATORIA: o documento vai para a revisão
    (mesmo sem pendências) e só sai de lá validado por uma pessoa na conferência. Vale para cada leitura nova;
    as correções não mudam a marca."""
    req = doc.requerimento
    doc.conferencia_obrigatoria = req is not None and (req.confianca_geral or 0) < config().limiar_conferencia_obrigatoria
    if doc.conferencia_obrigatoria and doc.status == "extraido":
        doc.status = "revisao"
    return doc.conferencia_obrigatoria


def validar_no_envio(doc: Documento) -> bool:
    """Documento enviado como já conferido (`validar_ao_ler`): valida assim que a leitura termina, sem passar
    pela conferência, em nome de quem enviou. Pendências da leitura não impedem: ficam no histórico com a
    justificativa automática. Leitura com conferência obrigatória não é validada: fica na revisão, com um aviso.
    Em memória, como `validar_documento`; devolve se validou."""
    if not doc.validar_ao_ler or doc.requerimento is None or doc.status not in ("extraido", "revisao"):
        return False
    doc.validar_ao_ler = False
    if doc.conferencia_obrigatoria:
        doc.requerimento.avisos.append(
            f"Enviado como já conferido, mas a leitura ficou com {doc.requerimento.confianca_geral or 0:.0f}% de "
            f"confiança (abaixo de {config().limiar_conferencia_obrigatoria:.0f}%): conferência obrigatória na tela "
            "antes de validar."
        )
        return False
    validar_documento(doc, doc.criado_por_id, forcar=True, justificativa=JUSTIFICATIVA_ENVIO, modo="envio")
    return True


def chave_detalhe(texto: str) -> tuple[str, str, int | None]:
    """'criacao_animal.cabecas#2' -> ('criacao_animal', 'cabecas', 2). ValueError se não existir."""
    nome, _, item = texto.partition("#")
    fin, _, campo = nome.partition(".")
    fdef = POR_CHAVE.get(fin)
    cdef = fdef.campo(campo) if fdef else None
    if cdef is None or fin == "irrigacao":
        raise ValueError(f"campo de detalhe desconhecido: {texto}")
    eh_linha = cdef in fdef.colunas
    if eh_linha != bool(item):
        raise ValueError(f"'{texto}': {'informe o item (#n)' if eh_linha else 'campo sem item'}")
    n = int(item) if item else None
    if n is not None and not 1 <= n <= 200:
        raise ValueError(f"'{texto}': item fora do intervalo")
    return fin, campo, n


def _blocos_corrigidos(
    por_chave: dict[Chave, Campo],
    novos: dict[str, str | None],
    manuais: set[Chave],
    alteracoes: list[tuple[str, str | None, str | None]],
) -> tuple[list[BlocoFinalidade], set[Chave]]:
    """Remonta os detalhes das finalidades a partir dos campos gravados e aplica as correções.

    Itens que ficarem com todas as colunas vazias são removidos e os seguintes renumerados."""
    blocos: dict[str, BlocoFinalidade] = {}

    def bloco(fin: str) -> BlocoFinalidade:
        if fin not in blocos:
            fdef = POR_CHAVE[fin]
            blocos[fin] = BlocoFinalidade(CampoBruto(fdef.nome), fdef)
        return blocos[fin]

    linhas: dict[str, dict[int, dict[str, CampoBruto]]] = {}
    for (nome, indice), c in por_chave.items():
        if "." not in nome:
            continue
        fin, campo = nome.split(".", 1)
        if fin not in POR_CHAVE:
            continue
        if indice is None:
            bloco(fin).valores[campo] = _bruto_de(c)
        else:
            bloco(fin)
            linhas.setdefault(fin, {}).setdefault(indice, {})[campo] = _bruto_de(c)

    for texto, valor in novos.items():
        fin, campo, n = chave_detalhe(texto)
        nome = f"{fin}.{campo}"
        c = por_chave.get((nome, n))
        valor = (valor or "").strip()
        if c is not None and (c.valor_atual or "") == valor:
            continue
        alteracoes.append((texto, c.valor_atual if c else None, valor or None))
        manuais.add((nome, n))
        if n is None:
            bloco(fin).valores[campo] = _bruto_de(c, valor)
        else:
            bloco(fin)
            linhas.setdefault(fin, {}).setdefault(n, {})[campo] = _bruto_de(c, valor)

    for fin, por_item in linhas.items():
        novo_n = 0
        for n in sorted(por_item):
            item = por_item[n]
            if not any(c.valor for c in item.values()):
                manuais = {m for m in manuais if not (m[0].startswith(fin + ".") and m[1] == n)}
                continue
            novo_n += 1
            if novo_n != n:
                manuais = {(m[0], novo_n) if m[0].startswith(fin + ".") and m[1] == n else m for m in manuais}
            blocos[fin].linhas.append(item)
    return list(blocos.values()), manuais
