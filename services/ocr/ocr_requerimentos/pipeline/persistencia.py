"""Liga o pipeline ao banco: processa um `ocr.documento`, grava resultados, divide PDFs com vários
requerimentos e reaplica a validação depois de correções manuais."""
from __future__ import annotations

import hashlib
import logging
import time
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any

import pymupdf
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..armazenamento import Armazenamento, armazenamento
from ..config import config
from ..extracao.finalidades import POR_CHAVE, definicao_por_titulo
from ..extracao.parser import BlocoFinalidade, ExtracaoBruta, LinhaIrrigacao
from ..extracao.referencias import ReferenciasEstaticas, SigaReferencias
from ..extracao.texto import Ref
from ..extracao.tipos import CampoBruto
from ..extracao.validacao import CampoValidado, Referencias, Resultado, validar
from ..imagem.ocr import criar_motor
from ..modelos import (
    CampoExtraido,
    Documento,
    Lote,
    LoteDocumento,
    Pagina,
    Requerimento,
    RequerimentoFinalidade,
    RequerimentoIrrigacao,
    Revisao,
    engine,
)
from . import VERSAO_PIPELINE
from .extracao import ResultadoArquivo, Segmento, imagem_jpeg, palavras_json, processar_arquivo
from .leitura import ArquivoInvalido

log = logging.getLogger(__name__)


class ConflitoVersao(Exception):
    """O requerimento mudou (outra revisão, validação ou releitura) depois de lido por quem está gravando."""

STATUS_FINAIS = ("extraido", "revisao", "validado", "erro")
CAMPOS_SIMPLES = (
    "requerente_nome", "cpf_cnpj", "procedimento", "tipo_intervencao", "municipio", "localidade",
    "latitude", "longitude", "descricao_usos", "assinante_nome", "data_documento",
)


@lru_cache
def referencias_padrao() -> Referencias:
    if config().referencias == "estaticas":
        from ..dados_referencia import CULTURAS, DOMINIOS, SISTEMAS_IRRIGACAO

        return ReferenciasEstaticas(
            sistemas_irrigacao=[Ref(None, n, s) for n, s in SISTEMAS_IRRIGACAO],
            culturas=[Ref(None, n, s) for n, s in CULTURAS],
            dominios={t: [Ref(None, n, s) for n, s in v] for t, v in DOMINIOS.items()},
        )
    return SigaReferencias(engine(), uf=config().uf, srid_entrada=config().srid)


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
    s: Session,
    conteudo: bytes,
    nome: str,
    content_type: str,
    *,
    lote: Lote | None = None,
    usuario_id: int | None = None,
    pai: Documento | None = None,
    pagina_inicial: int | None = None,
    store: Armazenamento | None = None,
) -> ResultadoRegistro:
    """Grava o arquivo no armazenamento e cria o registro. Arquivo repetido (mesmo SHA-256) não é
    duplicado: devolve o documento existente, que passa a fazer parte também de `lote`."""
    store = store or armazenamento()
    h = sha256(conteudo)
    existente = s.scalar(select(Documento).where(Documento.sha256 == h))
    if existente:
        if lote is not None:
            vincular_lote(s, lote, existente, nome)
        return ResultadoRegistro(existente, True)
    u = _uuid.uuid4()
    chave = f"documentos/{u}/original{extensao(nome, content_type)}"
    store.salvar(chave, conteudo, content_type)
    doc = Documento(
        uuid=u, lote=lote, nome_original=nome[:255], storage_key=chave, content_type=content_type or "application/octet-stream",
        tamanho_bytes=len(conteudo), sha256=h, status="recebido", criado_por_id=usuario_id,
        documento_pai_id=pai.id if pai else None, pagina_inicial=pagina_inicial,
    )
    s.add(doc)
    s.flush()
    if lote is not None:
        vincular_lote(s, lote, doc, nome)
    return ResultadoRegistro(doc, False)


def vincular_lote(s: Session, lote: Lote | int, doc: Documento, nome: str | None = None) -> None:
    """Põe o documento no lote, com as partes dele se já foi dividido."""
    lote_id = lote if isinstance(lote, int) else lote.id
    s.execute(
        pg_insert(LoteDocumento)
        .values(lote_id=lote_id, documento_id=doc.id, nome_arquivo=(nome or doc.nome_original)[:255])
        .on_conflict_do_nothing()
    )
    filhos = select(func.cast(lote_id, LoteDocumento.lote_id.type), Documento.id, Documento.nome_original).where(
        Documento.documento_pai_id == doc.id
    )
    s.execute(
        pg_insert(LoteDocumento)
        .from_select(["lote_id", "documento_id", "nome_arquivo"], filhos)
        .on_conflict_do_nothing()
    )


def lotes_do_documento(s: Session, documento_id: int) -> list[int]:
    return list(s.scalars(select(LoteDocumento.lote_id).where(LoteDocumento.documento_id == documento_id)))


def atualizar_lotes_do_documento(s: Session, documento_id: int) -> None:
    for lote_id in lotes_do_documento(s, documento_id):
        atualizar_lote(s, lote_id)


# ----------------------------------------------------------------- gravação do resultado
def _num(v: float | str | None) -> Decimal | None:
    return None if v is None or v == "" else Decimal(str(v))


LeituraOcr = dict[tuple[str, int | None], tuple[str | None, Decimal | None]]


def _campo_db(
    cv: CampoValidado, indice: int | None = None, manual: bool = False, ocr: LeituraOcr | None = None
) -> CampoExtraido:
    """`ocr`: leitura original dos campos já gravados (correção manual); sem ela, cv é a própria leitura."""
    if ocr is not None and (cv.campo, indice) in ocr:
        valor_ocr, conf_ocr = ocr[(cv.campo, indice)]
    elif manual:
        valor_ocr = conf_ocr = None  # incluído na revisão: o OCR não leu nada aqui
    else:
        valor_ocr, conf_ocr = cv.valor_bruto, _num(cv.confianca)
    return CampoExtraido(
        campo=cv.campo, indice=indice, valor_bruto=cv.valor_bruto, valor_normalizado=cv.valor_normalizado,
        confianca=_num(cv.confianca), pagina=cv.pagina, bbox=list(cv.bbox) if cv.bbox else None,
        valido=cv.valido, obrigatorio=cv.obrigatorio, corrigido_manual=manual, mensagem=cv.mensagem,
        valor_ocr=valor_ocr, confianca_ocr=conf_ocr,
    )


def gravar_resultado(
    s: Session, doc: Documento, r: Resultado, manuais: set[tuple[str, int | None]] | None = None,
    preservar_ocr: bool = False,
) -> Requerimento:
    """Grava a extração validada. `preservar_ocr=True` (correções) mantém valor_ocr/confianca_ocr dos campos
    já existentes; False (leitura nova) usa o próprio resultado como leitura original."""
    manuais = manuais or set()
    req = doc.requerimento or Requerimento(documento_id=doc.id)
    if doc.requerimento is None:
        s.add(req)
        doc.requerimento = req
    req.versao = (req.versao or 0) + 1
    ocr: LeituraOcr | None = (
        {(c.campo, c.indice): (c.valor_ocr, c.confianca_ocr) for c in req.campos} if preservar_ocr else None
    )
    c = r.campos
    req.requerente_nome = c["requerente_nome"].valor_normalizado
    req.cpf_cnpj = c["cpf_cnpj"].valor_normalizado
    req.tipo_pessoa = r.tipo_pessoa
    req.pessoa_id = r.pessoa_id
    req.procedimento_texto = c["procedimento"].valor_normalizado
    req.procedimento_id = c["procedimento"].ref_id
    req.tipo_intervencao_texto = c["tipo_intervencao"].valor_normalizado
    req.tipo_intervencao_id = c["tipo_intervencao"].ref_id
    req.municipio_texto = c["municipio"].valor_normalizado
    req.municipio_id = c["municipio"].ref_id
    req.localidade = (c["localidade"].valor_normalizado or None) and c["localidade"].valor_normalizado[:100]
    req.latitude_texto = (c["latitude"].valor_bruto or "")[:40] or None
    req.longitude_texto = (c["longitude"].valor_bruto or "")[:40] or None
    req.latitude = _num(r.latitude)
    req.longitude = _num(r.longitude)
    req.geom = (
        WKTElement(f"POINT({r.longitude} {r.latitude})", srid=4674)
        if r.latitude is not None and r.longitude is not None else None
    )
    req.descricao_usos = c["descricao_usos"].valor_normalizado
    req.assinante_nome = c["assinante_nome"].valor_normalizado
    req.data_documento = r.data_documento
    req.confianca_geral = _num(r.confianca_geral)
    req.pendencias = r.pendencias
    req.avisos = r.avisos
    if req.status_validacao != "validado":
        req.status_validacao = "pendente"

    req.campos.clear()
    req.finalidades.clear()
    req.irrigacao.clear()
    s.flush()
    for nome in CAMPOS_SIMPLES:
        req.campos.append(_campo_db(c[nome], manual=(nome, None) in manuais, ocr=ocr))
    detalhes = {d.indice: d for d in r.detalhes}
    for i, f in enumerate(r.finalidades):
        req.campos.append(_campo_db(f, i, ("finalidade", i) in manuais, ocr))
        det = detalhes.get(i)
        req.finalidades.append(RequerimentoFinalidade(
            finalidade_texto=(f.valor_normalizado or "")[:250], tipo_finalidade_id=f.ref_id,
            confianca=_num(f.confianca), valido=f.valido,
            chave=det.chave if det else None, detalhes=det.dados if det else None,
        ))
    for det in r.detalhes:
        for cv in det.campos:
            req.campos.append(_campo_db(cv, cv.item, (cv.campo, cv.item) in manuais, ocr))
    for it in r.irrigacao:
        for sub in (it.sistema, it.area, it.cultura):
            req.campos.append(_campo_db(sub, it.ordem, (sub.campo, it.ordem) in manuais, ocr))
        req.irrigacao.append(RequerimentoIrrigacao(
            ordem=it.ordem, sistema_texto=(it.sistema.valor_normalizado or "")[:150], sistema_id=it.sistema.ref_id,
            area_ha=_num(it.area_ha), cultura_texto=(it.cultura.valor_normalizado or "")[:150],
            cultura_id=it.cultura.ref_id, confianca=_num(it.confianca), valido=it.valido,
        ))
    if doc.status != "validado":
        doc.status = r.status
    return req


def config_extracao() -> dict[str, Any]:
    cfg = config()
    return {
        "motor_ocr": cfg.motor_ocr, "idioma_tesseract": cfg.idioma_tesseract, "limiar_confianca": cfg.limiar_confianca,
        "remover_tinta_azul": cfg.remover_tinta_azul, "confiar_texto_scanner": cfg.confiar_texto_scanner,
        "conferir_numeros": cfg.conferir_numeros, "referencias": cfg.referencias,
    }


def _gravar_segmento(s: Session, doc: Documento, seg: Segmento, res: ResultadoArquivo, store: Armazenamento) -> None:
    doc.versao_pipeline = VERSAO_PIPELINE
    doc.config_extracao = config_extracao()
    doc.tipo_entrada = res.leitura.tipo_entrada
    doc.metodo_extracao = "ocr" if any(p.metodo == "ocr" for p in seg.paginas) else "texto_nativo"
    doc.paginas = len(seg.paginas)
    doc.assinatura_tipo = seg.assinatura.tipo
    doc.assinatura_detalhes = seg.assinatura.detalhes
    if seg.qrcodes:
        q = seg.qrcodes[0]
        doc.qr_conteudo = q.bruto
        if q.processo_uuid:
            try:
                doc.processo_uuid = _uuid.UUID(q.processo_uuid)
            except ValueError:
                pass
            refs = referencias_padrao()
            ref = refs.processo_por_uuid(q.processo_uuid) if hasattr(refs, "processo_por_uuid") else None
            doc.processo_id = ref.id if ref else None
        doc.metodo_extracao = "qrcode+" + doc.metodo_extracao

    doc.paginas_lidas.clear()
    s.flush()
    for k, p in enumerate(seg.paginas, start=1):
        chave = f"documentos/{doc.uuid}/paginas/{k}.jpg"
        if p.imagem is not None:
            store.salvar(chave, imagem_jpeg(p.imagem), "image/jpeg")
        doc.paginas_lidas.append(Pagina(
            numero=k, largura=p.largura, altura=p.altura, imagem_key=chave if p.imagem is not None else None,
            angulo_correcao=_num(round(p.angulo_correcao, 2)), metodo=p.metodo, motor_ocr=p.motor,
            texto_bruto=p.texto, ocr_json=[{**w, "p": k} for w in palavras_json(p)],
            confianca_media=_num(p.confianca_media),
        ))
    gravar_resultado(s, doc, seg.resultado)
    # páginas do segmento renumeradas a partir de 1 no documento filho
    offset = seg.paginas[0].numero - 1
    if offset and doc.requerimento:
        for cdb in doc.requerimento.campos:
            if cdb.pagina:
                cdb.pagina -= offset


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


def processar_documento(s: Session, documento_id: int, store: Armazenamento | None = None) -> Documento:
    store = store or armazenamento()
    cfg = config()
    doc = s.get(Documento, documento_id)
    if doc is None:
        raise ValueError(f"documento {documento_id} não existe")
    doc.status = "processando"
    doc.tentativas = (doc.tentativas or 0) + 1
    doc.erro = None
    s.commit()
    inicio = time.monotonic()
    try:
        conteudo = store.ler(doc.storage_key)
        res = processar_arquivo(
            conteudo, criar_motor(cfg.motor_ocr, cfg.idioma_tesseract), referencias_padrao(),
            doc.nome_original, doc.content_type, limiar=cfg.limiar_confianca, conferir_numeros=cfg.conferir_numeros,
            remover_azul=cfg.remover_tinta_azul, confiar_texto_scanner=cfg.confiar_texto_scanner,
            dividir=doc.documento_pai_id is None,
        )
        if len(res.segmentos) == 1:
            anteriores = _correcoes_anteriores(s, doc)
            _gravar_segmento(s, doc, res.segmentos[0], res, store)
            if anteriores:
                _reaplicar_correcoes(s, doc, anteriores)
        else:
            doc.versao_pipeline = VERSAO_PIPELINE
            doc.config_extracao = config_extracao()
            doc.tipo_entrada = res.leitura.tipo_entrada
            doc.paginas = len(res.leitura.paginas)
            doc.status = "dividido"
            base = doc.nome_original.rsplit(".", 1)[0]
            lotes_pai = lotes_do_documento(s, doc.id)
            for i, seg in enumerate(res.segmentos, start=1):
                numeros = [p.numero for p in seg.paginas]
                sub, ct = _sub_arquivo(conteudo, res.leitura.tipo_entrada, numeros, seg)
                nome = f"{base} - parte {i} (pág. {numeros[0]}{'-' + str(numeros[-1]) if len(numeros) > 1 else ''}).pdf"
                reg = registrar_documento(
                    s, sub, nome, ct, lote=doc.lote, usuario_id=doc.criado_por_id, pai=doc,
                    pagina_inicial=numeros[0], store=store,
                )
                for lote_id in lotes_pai:  # as partes acompanham o original em todos os lotes
                    vincular_lote(s, lote_id, reg.documento, nome)
                if reg.duplicado:
                    continue
                filho = reg.documento
                filho.status = "processando"
                filho.tentativas = 1
                _gravar_segmento(s, filho, seg, res, store)
                filho.tipo_entrada = res.leitura.tipo_entrada
                filho.duracao_ms = int((time.monotonic() - inicio) * 1000)
    except ArquivoInvalido as e:
        s.rollback()
        doc = s.get(Documento, documento_id)
        doc.status, doc.erro = "erro", str(e)
    except Exception as e:  # noqa: BLE001
        log.exception("falha ao processar documento %s", documento_id)
        s.rollback()
        doc = s.get(Documento, documento_id)
        doc.status, doc.erro = "erro", f"{type(e).__name__}: {e}"
    doc.duracao_ms = int((time.monotonic() - inicio) * 1000)
    s.commit()
    atualizar_lotes_do_documento(s, doc.id)
    return doc


Chave = tuple[str, int | None]


def _correcoes_anteriores(s: Session, doc: Documento) -> tuple[dict[Chave, str], set[Chave]] | None:
    """Valores gravados antes da releitura e quais foram corrigidos na revisão (None se nenhum). Trava o
    requerimento e relê do banco, para não perder uma correção salva enquanto o OCR rodava."""
    req = doc.requerimento
    if req is None:
        return None
    s.refresh(req, with_for_update=True)
    manuais = {(c.campo, c.indice) for c in req.campos if c.corrigido_manual}
    if not manuais:
        return None
    return {(c.campo, c.indice): c.valor_bruto or "" for c in req.campos}, manuais


def _reaplicar_correcoes(s: Session, doc: Documento, anteriores: tuple[dict[Chave, str], set[Chave]]) -> None:
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

    aplicar_correcoes(s, doc, correcoes, None, auditar=False)
    s.add(Revisao(requerimento_id=doc.requerimento.id, campo="__reprocessamento__", valor_anterior=None,
                  valor_novo=f"{len(manuais)} correção(ões) manual(is) reaplicada(s) após nova leitura"))


def atualizar_lote(s: Session, lote_id: int) -> Lote:
    # trava o lote: dois workers terminando juntos não gravam uma contagem desatualizada
    lote = s.scalars(
        select(Lote).where(Lote.id == lote_id).with_for_update().execution_options(populate_existing=True)
    ).one()
    contagem = dict(
        s.execute(
            select(Documento.status, func.count())
            .join(LoteDocumento, LoteDocumento.documento_id == Documento.id)
            .where(LoteDocumento.lote_id == lote_id)
            .group_by(Documento.status)
        ).all()
    )
    total = sum(v for k, v in contagem.items() if k != "dividido")
    lote.total = total
    lote.em_revisao = contagem.get("revisao", 0)
    lote.validados = contagem.get("validado", 0)
    lote.com_erro = contagem.get("erro", 0)
    lote.processados = sum(contagem.get(k, 0) for k in STATUS_FINAIS)
    pendentes = contagem.get("recebido", 0) + contagem.get("processando", 0)
    if pendentes:
        lote.status = "processando"
        lote.finalizado_em = None
    else:
        lote.status = "concluido_com_erros" if lote.com_erro else "concluido"
        lote.finalizado_em = lote.finalizado_em or datetime.now(timezone.utc)
    s.commit()
    return lote


# ----------------------------------------------------------------- correções manuais
def _bruto_de(cdb: CampoExtraido | None, novo: str | None = None) -> CampoBruto:
    if cdb is None:
        return CampoBruto(novo, conf_fixa=100.0 if novo is not None else None)
    bbox = tuple(cdb.bbox) if cdb.bbox else None
    if novo is not None:
        return CampoBruto(novo or None, conf_fixa=100.0, pagina_fixa=cdb.pagina, bbox_fixa=bbox)
    return CampoBruto(
        cdb.valor_bruto, conf_fixa=float(cdb.confianca or 0) if not cdb.corrigido_manual else 100.0,
        pagina_fixa=cdb.pagina, bbox_fixa=bbox,
    )


def _travar_versao(s: Session, req: Requerimento, esperada: int | None) -> None:
    """Trava o requerimento até o commit e confere se ninguém o gravou depois de `esperada` (a versão que o
    cliente leu; sem ela, a carregada nesta sessão)."""
    atual = s.scalar(select(Requerimento.versao).where(Requerimento.id == req.id).with_for_update())
    if atual != (esperada if esperada is not None else req.versao):
        raise ConflitoVersao(
            "este documento foi alterado (por outra pessoa ou por uma nova leitura) depois que você o abriu; "
            "recarregue a página para ver a versão atual"
        )


def aplicar_correcoes(
    s: Session, doc: Documento, correcoes: dict[str, Any], usuario_id: int | None, refs: Referencias | None = None,
    versao: int | None = None, auditar: bool = True,
) -> Requerimento:
    """correcoes = {"campos": {nome: valor}, "finalidades": [..] | None, "irrigacao": [{sistema, area, cultura}] | None}

    O valor corrigido passa pela mesma validação do OCR (com confiança 100) e cada alteração é auditada
    (`auditar=False` só ao reaplicar correções já auditadas). ConflitoVersao se `versao` não for a atual."""
    refs = refs or referencias_padrao()
    req = doc.requerimento
    if req is None:
        raise ValueError("documento ainda não tem extração")
    _travar_versao(s, req, versao)
    por_chave = {(c.campo, c.indice): c for c in req.campos}
    manuais = {k for k, c in por_chave.items() if c.corrigido_manual}
    ex = ExtracaoBruta()
    alteracoes: list[tuple[str, str | None, str | None]] = []

    novos = correcoes.get("campos") or {}
    for nome in CAMPOS_SIMPLES:
        cdb = por_chave.get((nome, None))
        if nome in novos and (cdb is None or (novos[nome] or None) != cdb.valor_bruto):
            alteracoes.append((nome, cdb.valor_bruto if cdb else None, novos[nome]))
            setattr(ex, nome, _bruto_de(cdb, novos[nome] or ""))
            manuais.add((nome, None))
        else:
            setattr(ex, nome, _bruto_de(cdb))

    antigas_fin = [por_chave[k] for k in sorted((k for k in por_chave if k[0] == "finalidade"), key=lambda k: k[1])]
    if correcoes.get("finalidades") is not None:
        manuais = {m for m in manuais if m[0] != "finalidade"}
        lista = [v for v in correcoes["finalidades"] if v and v.strip()]
        for i, v in enumerate(lista):
            antiga = antigas_fin[i] if i < len(antigas_fin) else None
            if antiga is not None and antiga.valor_bruto == v:
                ex.finalidades.append(_bruto_de(antiga))
                if antiga.corrigido_manual:
                    manuais.add(("finalidade", i))
            else:
                ex.finalidades.append(_bruto_de(antiga, v))
                manuais.add(("finalidade", i))
        antes = " | ".join(c.valor_bruto or "" for c in antigas_fin)
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
                cdb = por_chave.get((f"irrigacao_{sub}", o)) if o is not None else None
                if cdb is not None and cdb.valor_bruto == novo:
                    partes.append(_bruto_de(cdb))
                    if cdb.corrigido_manual:
                        manuais.add((f"irrigacao_{sub}", ordem_nova))
                else:
                    partes.append(_bruto_de(cdb, novo))
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
            s.add(Revisao(requerimento_id=req.id, campo=campo, valor_anterior=antes, valor_novo=depois,
                          usuario_id=usuario_id))
    if doc.status == "validado" and alteracoes:
        doc.status = r.status
        req.status_validacao = "pendente"
        req.validado_por_id = req.validado_em = None
    gravar_resultado(s, doc, r, manuais, preservar_ocr=True)
    s.commit()
    if auditar:  # na releitura, processar_documento atualiza os lotes no fim
        atualizar_lotes_do_documento(s, doc.id)
    return req


def validar_documento(s: Session, doc: Documento, usuario_id: int | None, forcar: bool = False,
                      justificativa: str | None = None, versao: int | None = None) -> Requerimento:
    req = doc.requerimento
    if req is None:
        raise ValueError("documento ainda não tem extração")
    _travar_versao(s, req, versao)
    if req.pendencias and not forcar:
        raise PermissionError("há pendências; corrija os campos ou valide com justificativa")
    if forcar and req.pendencias:
        if not (justificativa and justificativa.strip()):
            raise PermissionError("justificativa obrigatória para validar com pendências")
        s.add(Revisao(requerimento_id=req.id, campo="__validacao_com_pendencias__",
                      valor_anterior="; ".join(req.pendencias), valor_novo=justificativa, usuario_id=usuario_id))
    req.status_validacao = "validado"
    req.validado_por_id = usuario_id
    req.validado_em = datetime.now(timezone.utc)
    req.versao += 1
    doc.status = "validado"
    s.commit()
    atualizar_lotes_do_documento(s, doc.id)
    return req


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
    por_chave: dict[tuple[str, int | None], CampoExtraido],
    novos: dict[str, str | None],
    manuais: set[tuple[str, int | None]],
    alteracoes: list[tuple[str, str | None, str | None]],
) -> tuple[list[BlocoFinalidade], set[tuple[str, int | None]]]:
    """Remonta os detalhes das finalidades a partir dos campos gravados e aplica as correções.

    Itens que ficarem com todas as colunas vazias são removidos e os seguintes renumerados."""
    blocos: dict[str, BlocoFinalidade] = {}

    def bloco(fin: str) -> BlocoFinalidade:
        if fin not in blocos:
            fdef = POR_CHAVE[fin]
            blocos[fin] = BlocoFinalidade(CampoBruto(fdef.nome), fdef)
        return blocos[fin]

    linhas: dict[str, dict[int, dict[str, CampoBruto]]] = {}
    for (nome, indice), cdb in por_chave.items():
        if "." not in nome:
            continue
        fin, campo = nome.split(".", 1)
        if fin not in POR_CHAVE:
            continue
        if indice is None:
            bloco(fin).valores[campo] = _bruto_de(cdb)
        else:
            bloco(fin)
            linhas.setdefault(fin, {}).setdefault(indice, {})[campo] = _bruto_de(cdb)

    for texto, valor in novos.items():
        fin, campo, n = chave_detalhe(texto)
        nome = f"{fin}.{campo}"
        cdb = por_chave.get((nome, n))
        valor = (valor or "").strip()
        if cdb is not None and (cdb.valor_bruto or "") == valor:
            continue
        alteracoes.append((texto, cdb.valor_bruto if cdb else None, valor or None))
        manuais.add((nome, n))
        if n is None:
            bloco(fin).valores[campo] = _bruto_de(cdb, valor)
        else:
            bloco(fin)
            linhas.setdefault(fin, {}).setdefault(n, {})[campo] = _bruto_de(cdb, valor)

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
