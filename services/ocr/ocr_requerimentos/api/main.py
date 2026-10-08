"""API REST do serviço de OCR de requerimentos."""
from __future__ import annotations

import io
import mimetypes
import re
import uuid as _uuid
import zipfile
from datetime import date, datetime
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import exportacao
from ..armazenamento import armazenamento
from ..config import config
from ..dados_referencia import DOMINIOS
from ..extracao.finalidades import POR_CHAVE, FinalidadeDef, rotulo_campo
from ..extracao.validacao import ROTULOS
from ..modelos import CampoExtraido, Documento, Dominio, Lote, LoteDocumento, Requerimento, Revisao, sessao
from ..pipeline import persistencia as P
from ..worker import enfileirar

app = FastAPI(
    title="OCR de Requerimentos — SIGA",
    version="1.0.0",
    description="Extração de dados de requerimentos digitalizados (PDF ou imagem), individual ou em lote.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config().cors_origens.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

EXTENSOES_ACEITAS = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif")


# ----------------------------------------------------------------- dependências
def db():
    with sessao() as s:
        yield s


def autenticar(x_api_key: str | None = Header(default=None)) -> None:
    chave = config().api_key
    if chave and x_api_key != chave:
        raise HTTPException(401, "chave de API ausente ou inválida")


def usuario(x_usuario_id: str | None = Header(default=None)) -> int | None:
    try:
        return int(x_usuario_id) if x_usuario_id else None
    except ValueError:
        return None


Protegido = [Depends(autenticar)]


def _doc(s: Session, uid: str) -> Documento:
    try:
        u = _uuid.UUID(uid)
    except ValueError:
        raise HTTPException(404, "documento não encontrado")
    doc = s.scalar(
        select(Documento).where(Documento.uuid == u).options(
            selectinload(Documento.requerimento).selectinload(Requerimento.campos),
            selectinload(Documento.requerimento).selectinload(Requerimento.finalidades),
            selectinload(Documento.requerimento).selectinload(Requerimento.irrigacao),
            selectinload(Documento.paginas_lidas),
        )
    )
    if doc is None:
        raise HTTPException(404, "documento não encontrado")
    return doc


def _lote(s: Session, uid: str) -> Lote:
    try:
        u = _uuid.UUID(uid)
    except ValueError:
        raise HTTPException(404, "lote não encontrado")
    lote = s.scalar(select(Lote).where(Lote.uuid == u))
    if lote is None:
        raise HTTPException(404, "lote não encontrado")
    return lote


# ----------------------------------------------------------------- serialização
def disposicao(nome: str, tipo: str = "inline") -> str:
    """Content-Disposition seguro para nomes com acento (RFC 5987)."""
    from urllib.parse import quote

    from ..extracao.texto import sem_acento

    ascii_ = sem_acento(nome).encode("ascii", "ignore").decode().replace('"', "") or "arquivo"
    return f"{tipo}; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nome)}"


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def resumo_documento(d: Documento) -> dict[str, Any]:
    r = d.requerimento
    return {
        "uuid": str(d.uuid),
        "nome_original": d.nome_original,
        "status": d.status,
        "erro": d.erro,
        "tipo_entrada": d.tipo_entrada,
        "metodo_extracao": d.metodo_extracao,
        "paginas": d.paginas,
        "assinatura_tipo": d.assinatura_tipo,
        "lote_uuid": str(d.lote.uuid) if d.lote else None,
        "documento_pai_uuid": None,
        "requerente_nome": r.requerente_nome if r else None,
        "cpf_cnpj": r.cpf_cnpj if r else None,
        "municipio": r.municipio_texto if r else None,
        "procedimento": r.procedimento_texto if r else None,
        "data_documento": r.data_documento.isoformat() if r and r.data_documento else None,
        "validado_em": _iso(r.validado_em) if r else None,
        "confianca_geral": float(r.confianca_geral) if r and r.confianca_geral is not None else None,
        "pendencias": (r.pendencias or []) if r else [],
        "created_at": _iso(d.created_at),
        "updated_at": _iso(d.updated_at),
        "duracao_ms": d.duracao_ms,
    }


def _campo(c: CampoExtraido) -> dict[str, Any]:
    return {
        "campo": c.campo, "rotulo": ROTULOS.get(c.campo) or rotulo_campo(c.campo) or c.campo, "indice": c.indice,
        "valor_bruto": c.valor_bruto, "valor_normalizado": c.valor_normalizado,
        "confianca": float(c.confianca) if c.confianca is not None else None,
        "pagina": c.pagina, "bbox": c.bbox, "valido": c.valido, "obrigatorio": c.obrigatorio,
        "corrigido_manual": c.corrigido_manual, "mensagem": c.mensagem,
    }


def detalhe_documento(s: Session, d: Documento) -> dict[str, Any]:
    out = resumo_documento(d)
    if d.documento_pai_id:
        pai = s.get(Documento, d.documento_pai_id)
        out["documento_pai_uuid"] = str(pai.uuid) if pai else None
    out["filhos"] = [
        resumo_documento(f) for f in s.scalars(
            select(Documento).where(Documento.documento_pai_id == d.id).order_by(Documento.pagina_inicial)
        )
    ]
    out["assinatura_detalhes"] = d.assinatura_detalhes
    out["qr_conteudo"] = d.qr_conteudo
    out["processo_uuid"] = str(d.processo_uuid) if d.processo_uuid else None
    out["processo_id"] = d.processo_id
    out["paginas_lidas"] = [
        {"numero": p.numero, "largura": p.largura, "altura": p.altura, "metodo": p.metodo, "motor_ocr": p.motor_ocr,
         "confianca_media": float(p.confianca_media) if p.confianca_media is not None else None,
         "angulo_correcao": float(p.angulo_correcao) if p.angulo_correcao is not None else None,
         "tem_imagem": bool(p.imagem_key)}
        for p in d.paginas_lidas
    ]
    r = d.requerimento
    if r is None:
        out["requerimento"] = None
        return out
    out["requerimento"] = {
        "requerente_nome": r.requerente_nome, "cpf_cnpj": r.cpf_cnpj, "tipo_pessoa": r.tipo_pessoa,
        "pessoa_id": r.pessoa_id, "procedimento": r.procedimento_texto, "procedimento_id": r.procedimento_id,
        "tipo_intervencao": r.tipo_intervencao_texto, "tipo_intervencao_id": r.tipo_intervencao_id,
        "municipio": r.municipio_texto, "municipio_id": r.municipio_id, "localidade": r.localidade,
        "latitude": float(r.latitude) if r.latitude is not None else None,
        "longitude": float(r.longitude) if r.longitude is not None else None,
        "latitude_texto": r.latitude_texto, "longitude_texto": r.longitude_texto,
        "descricao_usos": r.descricao_usos, "assinante_nome": r.assinante_nome,
        "data_documento": r.data_documento.isoformat() if r.data_documento else None,
        "confianca_geral": float(r.confianca_geral) if r.confianca_geral is not None else None,
        "pendencias": r.pendencias or [], "avisos": r.avisos or [],
        "status_validacao": r.status_validacao, "validado_por_id": r.validado_por_id,
        "validado_em": _iso(r.validado_em), "versao": r.versao,
        "finalidades": [
            {"texto": f.finalidade_texto, "tipo_finalidade_id": f.tipo_finalidade_id,
             "confianca": float(f.confianca) if f.confianca is not None else None, "valido": f.valido,
             "chave": f.chave, "detalhes": f.detalhes,
             "estrutura": _estrutura(POR_CHAVE[f.chave]) if f.chave in POR_CHAVE else None}
            for f in r.finalidades
        ],
        "irrigacao": [
            {"ordem": i.ordem, "sistema": i.sistema_texto, "sistema_id": i.sistema_id,
             "area_ha": float(i.area_ha) if i.area_ha is not None else None, "cultura": i.cultura_texto,
             "cultura_id": i.cultura_id, "confianca": float(i.confianca) if i.confianca is not None else None,
             "valido": i.valido}
            for i in r.irrigacao
        ],
        "campos": [_campo(c) for c in r.campos],
    }
    return out


def _estrutura(f: FinalidadeDef) -> dict[str, Any]:
    """Campos que a tela mostra para os detalhes da finalidade (a irrigação tem tabela própria)."""
    cd = lambda c: {"chave": c.chave, "rotulo": c.rotulo, "tipo": c.tipo, "dominio": c.dominio,  # noqa: E731
                    "obrigatorio": c.obrigatorio}
    return {"nome": f.nome, "campos": [cd(c) for c in f.campos], "colunas": [cd(c) for c in f.colunas],
            "modo_linhas": f.modo_linhas, "rotulo_linhas": f.rotulo_linhas}


def resumo_lote(l: Lote) -> dict[str, Any]:
    return {
        "uuid": str(l.uuid), "nome": l.nome, "origem": l.origem, "status": l.status, "total": l.total,
        "processados": l.processados, "em_revisao": l.em_revisao, "validados": l.validados,
        "com_erro": l.com_erro, "created_at": _iso(l.created_at), "finalizado_em": _iso(l.finalizado_em),
    }


# ----------------------------------------------------------------- recebimento de arquivos
def _content_type(nome: str, informado: str | None) -> str:
    if informado and informado not in ("application/octet-stream", ""):
        return informado
    return mimetypes.guess_type(nome)[0] or "application/octet-stream"


async def _ler_upload(f: UploadFile) -> bytes:
    limite = config().max_upload_mb * 1024 * 1024
    dados = await f.read(limite + 1)
    if len(dados) > limite:
        raise HTTPException(413, f"'{f.filename}' excede {config().max_upload_mb} MB")
    if not dados:
        raise HTTPException(400, f"'{f.filename}' está vazio")
    return dados


def _entradas_zip(conteudo: bytes, nome_zip: str) -> list[tuple[str, bytes]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile:
        raise HTTPException(400, f"'{nome_zip}' não é um ZIP válido")
    saida = []
    limite = config().max_upload_mb * 1024 * 1024
    for info in z.infolist():
        nome = info.filename.replace("\\", "/")
        base = nome.rsplit("/", 1)[-1]
        if info.is_dir() or not base or base.startswith(".") or "__MACOSX" in nome:
            continue
        if info.file_size > limite:
            continue
        saida.append((base, z.read(info)))
        if len(saida) >= config().max_arquivos_zip:
            break
    return saida


# ----------------------------------------------------------------- rotas
@app.get("/saude")
def saude(s: Session = Depends(db)):
    s.execute(select(1))
    return {"status": "ok", "motor_ocr": config().motor_ocr}


@app.post("/documentos", status_code=201, dependencies=Protegido)
async def enviar_documento(
    arquivo: UploadFile = File(...), s: Session = Depends(db), usuario_id: int | None = Depends(usuario)
):
    dados = await _ler_upload(arquivo)
    nome = arquivo.filename or "documento"
    if nome.lower().endswith(".zip"):
        raise HTTPException(400, "para enviar um ZIP use o envio em lote (/lotes)")
    reg = P.registrar_documento(s, dados, nome, _content_type(nome, arquivo.content_type), usuario_id=usuario_id)
    s.commit()
    if not reg.duplicado:
        enfileirar([reg.documento.id])
    s.refresh(reg.documento)
    corpo = {**resumo_documento(reg.documento), "duplicado": reg.duplicado}
    return JSONResponse(corpo, status_code=200 if reg.duplicado else 201)


@app.post("/lotes", status_code=201, dependencies=Protegido)
async def criar_lote(
    arquivos: list[UploadFile] = File(...),
    nome: str | None = Form(default=None),
    s: Session = Depends(db),
    usuario_id: int | None = Depends(usuario),
):
    entradas: list[tuple[str, bytes]] = []
    origem = "upload"
    for f in arquivos:
        dados = await _ler_upload(f)
        fn = f.filename or "arquivo"
        if fn.lower().endswith(".zip"):
            origem = "zip"
            entradas.extend(_entradas_zip(dados, fn))
        else:
            entradas.append((fn, dados))
    if not entradas:
        raise HTTPException(400, "nenhum arquivo encontrado no envio")
    lote = Lote(nome=(nome or f"Lote de {datetime.now():%d/%m/%Y %H:%M}")[:200], origem=origem,
                status="processando", criado_por_id=usuario_id)
    s.add(lote)
    s.flush()
    novos, duplicados, ignorados = [], [], []
    for fn, dados in entradas:
        if not fn.lower().endswith(EXTENSOES_ACEITAS):
            ignorados.append(fn)  # entra mesmo assim: vira documento com erro, visível no lote
        reg = P.registrar_documento(s, dados, fn, _content_type(fn, None), lote=lote, usuario_id=usuario_id)
        if reg.duplicado:
            duplicados.append((fn, reg.documento))
        else:
            novos.append(reg.documento)
    # arquivo já enviado antes não é lido de novo, mas passa a fazer parte deste lote também
    s.commit()
    P.atualizar_lote(s, lote.id)
    enfileirar([d.id for d in novos])
    s.refresh(lote)
    return {
        **resumo_lote(lote),
        "recebidos": len(entradas),
        "novos": len(novos),
        "duplicados": [{"arquivo": fn, "documento_uuid": str(d.uuid), "status": d.status} for fn, d in duplicados],
        "formato_nao_suportado": ignorados,
    }


@app.get("/lotes", dependencies=Protegido)
def listar_lotes(pagina: int = Query(1, ge=1), tamanho: int = Query(20, ge=1, le=100), s: Session = Depends(db)):
    total = s.scalar(select(func.count()).select_from(Lote))
    lotes = s.scalars(select(Lote).order_by(Lote.created_at.desc()).offset((pagina - 1) * tamanho).limit(tamanho))
    return {"total": total, "itens": [resumo_lote(l) for l in lotes]}


def _docs_do_lote(lote: Lote):
    return select(Documento).join(LoteDocumento, LoteDocumento.documento_id == Documento.id).where(
        LoteDocumento.lote_id == lote.id
    )


@app.get("/lotes/{uid}", dependencies=Protegido)
def obter_lote(uid: str, s: Session = Depends(db)):
    lote = _lote(s, uid)
    docs = s.scalars(
        _docs_do_lote(lote).options(selectinload(Documento.requerimento), selectinload(Documento.lote))
        .order_by(Documento.created_at, Documento.pagina_inicial)
    ).all()
    return {**resumo_lote(lote), "documentos": [resumo_documento(d) for d in docs]}


@app.post("/lotes/{uid}/reprocessar-erros", dependencies=Protegido)
def reprocessar_erros(uid: str, s: Session = Depends(db)):
    lote = _lote(s, uid)
    docs = s.scalars(_docs_do_lote(lote).where(Documento.status == "erro")).all()
    for d in docs:
        d.status = "recebido"
    s.commit()
    P.atualizar_lote(s, lote.id)
    enfileirar([d.id for d in docs])
    return {"reenfileirados": len(docs)}


@app.get("/lotes/{uid}/exportar", dependencies=Protegido)
def exportar_lote(uid: str, formato: str = Query("csv", pattern="^(csv|xlsx)$"), s: Session = Depends(db)):
    lote = _lote(s, uid)
    docs = s.scalars(
        _docs_do_lote(lote).where(Documento.status != "dividido")
        .options(selectinload(Documento.requerimento).selectinload(Requerimento.finalidades),
                 selectinload(Documento.requerimento).selectinload(Requerimento.irrigacao))
        .order_by(Documento.created_at)
    ).all()
    nome = f"lote-{str(lote.uuid)[:8]}"
    if formato == "xlsx":
        return Response(exportacao.para_xlsx(docs),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nome}.xlsx"'})
    return Response(exportacao.para_csv(docs), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}.csv"'})


ACENTOS = ("áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ", "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC")
FUSO = "America/Fortaleza"  # Piauí, UTC-3 o ano todo


def _sem_acento(expr):
    """Sem acento e em minúsculas, sem depender da extensão unaccent."""
    return func.lower(func.translate(expr, *ACENTOS))


@app.get("/documentos", dependencies=Protegido)
def listar_documentos(
    status: str | None = None,
    busca: str | None = None,
    requerente: str | None = None,
    procedimento: str | None = None,
    municipio: str | None = None,
    data_de: date | None = None,
    data_ate: date | None = None,
    campo_data: str = Query("documento", pattern="^(documento|gravacao)$"),
    pagina: int = Query(1, ge=1),
    tamanho: int = Query(25, ge=1, le=200),
    s: Session = Depends(db),
):
    """Filtros combinados com E. `procedimento`/`municipio`: valor exato (opções em /filtros);
    `requerente`: trecho do nome, sem diferenciar maiúsculas nem acentos; `data_de`/`data_ate`: inclusivos,
    sobre a data do documento ou a data de gravação (dia no fuso do Piauí)."""
    q = select(Documento).outerjoin(Requerimento).where(Documento.status != "dividido")
    if status:
        q = q.where(Documento.status.in_(status.split(",")))
    if requerente and requerente.strip():
        q = q.where(_sem_acento(Requerimento.requerente_nome).contains(_sem_acento_py(requerente.strip()), autoescape=True))
    if procedimento:
        q = q.where(Requerimento.procedimento_texto == procedimento)
    if municipio:
        q = q.where(Requerimento.municipio_texto == municipio)
    if data_de or data_ate:
        dia = (Requerimento.data_documento if campo_data == "documento"
               else cast(func.timezone(FUSO, Documento.created_at), Date))
        if data_de:
            q = q.where(dia >= data_de)
        if data_ate:
            q = q.where(dia <= data_ate)
    if busca:
        termo = f"%{busca.strip()}%"
        condicoes = [
            Documento.nome_original.ilike(termo), Requerimento.requerente_nome.ilike(termo),
            Requerimento.cpf_cnpj.ilike(termo), Requerimento.municipio_texto.ilike(termo),
        ]
        # CPF/CNPJ com ou sem máscara (ou só parte dele): compara apenas os dígitos
        digitos = re.sub(r"\D", "", busca)
        if digitos and re.fullmatch(r"[\d\s./-]+", busca.strip()):
            condicoes.append(func.regexp_replace(Requerimento.cpf_cnpj, r"\D", "", "g").like(f"%{digitos}%"))
        q = q.where(or_(*condicoes))
    total = s.scalar(select(func.count()).select_from(q.subquery()))
    docs = s.scalars(
        q.options(selectinload(Documento.requerimento), selectinload(Documento.lote))
        .order_by(Documento.created_at.desc()).offset((pagina - 1) * tamanho).limit(tamanho)
    ).all()
    return {"total": total, "itens": [resumo_documento(d) for d in docs]}


def _sem_acento_py(texto: str) -> str:
    return texto.translate(str.maketrans(*ACENTOS)).lower()


@app.get("/filtros", dependencies=Protegido)
def opcoes_de_filtro(s: Session = Depends(db)):
    """Procedimentos e municípios que aparecem nos requerimentos gravados, com a quantidade de cada."""
    def distintos(col):
        linhas = s.execute(
            select(col, func.count()).join(Documento, Documento.id == Requerimento.documento_id)
            .where(Documento.status != "dividido", col.isnot(None), col != "")
            .group_by(col).order_by(col)
        ).all()
        return [{"nome": n, "total": t} for n, t in linhas]

    return {"procedimentos": distintos(Requerimento.procedimento_texto),
            "municipios": distintos(Requerimento.municipio_texto)}


@app.get("/revisao", dependencies=Protegido)
def fila_revisao(s: Session = Depends(db)):
    docs = s.scalars(
        select(Documento).where(Documento.status == "revisao")
        .options(selectinload(Documento.requerimento), selectinload(Documento.lote))
        .order_by(Documento.created_at)
    ).all()
    return {"total": len(docs), "itens": [resumo_documento(d) for d in docs]}


@app.get("/estatisticas", dependencies=Protegido)
def estatisticas(s: Session = Depends(db)):
    por_status = dict(s.execute(select(Documento.status, func.count()).group_by(Documento.status)).all())
    return {"por_status": por_status, "lotes": s.scalar(select(func.count()).select_from(Lote))}


@app.get("/documentos/{uid}", dependencies=Protegido)
def obter_documento(uid: str, s: Session = Depends(db)):
    return detalhe_documento(s, _doc(s, uid))


@app.get("/documentos/{uid}/arquivo", dependencies=Protegido)
def baixar_original(uid: str, s: Session = Depends(db)):
    d = _doc(s, uid)
    return Response(armazenamento().ler(d.storage_key), media_type=d.content_type,
                    headers={"Content-Disposition": disposicao(d.nome_original)})


@app.get("/documentos/{uid}/paginas/{numero}/imagem", dependencies=Protegido)
def imagem_pagina(uid: str, numero: int, s: Session = Depends(db)):
    d = _doc(s, uid)
    p = next((p for p in d.paginas_lidas if p.numero == numero), None)
    if p is None or not p.imagem_key:
        raise HTTPException(404, "página sem imagem")
    return Response(armazenamento().ler(p.imagem_key), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


@app.post("/documentos/{uid}/reprocessar", dependencies=Protegido)
def reprocessar(uid: str, s: Session = Depends(db)):
    d = _doc(s, uid)
    if d.status == "validado":
        raise HTTPException(409, "documento já validado; reprocessar descartaria a validação")
    if d.status == "processando":
        raise HTTPException(409, "documento já está em processamento")
    d.status = "recebido"
    s.commit()
    enfileirar([d.id])
    return resumo_documento(d)


class Correcoes(BaseModel):
    campos: dict[str, str | None] = Field(default_factory=dict)
    finalidades: list[str] | None = None
    irrigacao: list[dict[str, str | float | None]] | None = None
    # detalhes das finalidades: {"criacao_animal.cabecas#2": "150", "termoeletrica.potencia": "12.5"}
    detalhes: dict[str, str | None] = Field(default_factory=dict)
    # requerimento.versao lida pelo cliente; se outro gravou depois, a correção é recusada (409)
    versao: int | None = None


def _editavel(d: Documento) -> None:
    if d.status in ("recebido", "processando"):
        raise HTTPException(409, "documento está sendo lido de novo; aguarde o fim da leitura")
    if d.requerimento is None:
        raise HTTPException(409, "documento ainda não foi processado")


@app.patch("/documentos/{uid}/correcoes", dependencies=Protegido)
def corrigir(uid: str, corpo: Correcoes, s: Session = Depends(db), usuario_id: int | None = Depends(usuario)):
    d = _doc(s, uid)
    _editavel(d)
    invalidos = set(corpo.campos) - set(P.CAMPOS_SIMPLES)
    if invalidos:
        raise HTTPException(422, f"campos desconhecidos: {', '.join(sorted(invalidos))}")
    for k in corpo.detalhes:
        try:
            P.chave_detalhe(k)
        except ValueError as e:
            raise HTTPException(422, str(e))
    try:
        P.aplicar_correcoes(s, d, corpo.model_dump(exclude={"versao"}), usuario_id, versao=corpo.versao)
    except P.ConflitoVersao as e:
        raise HTTPException(409, str(e))
    s.expire_all()
    return detalhe_documento(s, _doc(s, uid))


class Validacao(BaseModel):
    forcar: bool = False
    justificativa: str | None = None
    versao: int | None = None


@app.post("/documentos/{uid}/validar", dependencies=Protegido)
def validar_documento(uid: str, corpo: Validacao | None = None, s: Session = Depends(db),
                      usuario_id: int | None = Depends(usuario)):
    d = _doc(s, uid)
    _editavel(d)
    corpo = corpo or Validacao()
    try:
        P.validar_documento(s, d, usuario_id, corpo.forcar, corpo.justificativa, corpo.versao)
    except (PermissionError, ValueError, P.ConflitoVersao) as e:
        raise HTTPException(409, str(e))
    s.expire_all()
    return detalhe_documento(s, _doc(s, uid))


@app.get("/documentos/{uid}/revisoes", dependencies=Protegido)
def historico(uid: str, s: Session = Depends(db)):
    d = _doc(s, uid)
    if d.requerimento is None:
        return []
    revs = s.scalars(select(Revisao).where(Revisao.requerimento_id == d.requerimento.id).order_by(Revisao.created_at))
    return [{"campo": r.campo, "valor_anterior": r.valor_anterior, "valor_novo": r.valor_novo,
             "usuario_id": r.usuario_id, "created_at": _iso(r.created_at)} for r in revs]


@app.get("/referencias/{tipo}", dependencies=Protegido)
def referencias(tipo: str):
    refs = P.referencias_padrao()
    mapa = {"municipios": "municipios", "procedimentos": "procedimentos", "intervencoes": "intervencoes",
            "finalidades": "finalidades", "sistemas": "sistemas_irrigacao", "culturas": "culturas"}
    if tipo in mapa:
        return [{"id": r.id, "nome": r.nome} for r in getattr(refs, mapa[tipo])]
    if tipo in DOMINIOS:  # listas dos detalhes das finalidades (estabelecimento, unidade, ...)
        return [{"id": r.id, "nome": r.nome} for r in refs.dominio(tipo)]
    raise HTTPException(404, "tipo de referência desconhecido")


@app.exception_handler(FileNotFoundError)
def _arquivo_ausente(_: Request, exc: FileNotFoundError):
    return JSONResponse({"detail": "arquivo não encontrado no armazenamento"}, status_code=404)
