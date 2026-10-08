"""API REST do serviço de OCR de requerimentos."""
from __future__ import annotations

import io
import mimetypes
import re
import uuid as _uuid
import zipfile
from datetime import date, datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError

from .. import exportacao
from ..config import config
from ..dados_referencia import DOMINIOS
from ..extracao.finalidades import POR_CHAVE, FinalidadeDef, rotulo_campo
from ..extracao.validacao import ROTULOS
from ..modelos import Campo, Documento, Lote, Revisao
from ..pipeline import persistencia as P
from ..repositorio import FINAIS, PENDENTES, TravaOcupada, publico, repositorio, resumo_documento
from ..worker import enfileirar

app = FastAPI(
    title="OCR de Requerimentos — SIGA",
    version="2.0.0",
    description="Extração de dados de requerimentos digitalizados (PDF ou imagem), individual ou em lote. "
                "Os dados ficam em arquivos JSON no armazenamento (ver /docs do projeto).",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config().cors_origens.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

EXTENSOES_ACEITAS = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif")
FUSO = ZoneInfo("America/Fortaleza")  # Piauí, UTC-3 o ano todo


# ----------------------------------------------------------------- dependências
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


def _uuid_valido(uid: str, o_que: str) -> str:
    try:
        return str(_uuid.UUID(uid))
    except ValueError:
        raise HTTPException(404, f"{o_que} não encontrado")


def _doc(uid: str) -> Documento:
    doc = repositorio().obter(_uuid_valido(uid, "documento"))
    if doc is None:
        raise HTTPException(404, "documento não encontrado")
    return doc


def _lote(uid: str) -> Lote:
    lote = repositorio().obter_lote(_uuid_valido(uid, "lote"))
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


def _campo(c: Campo) -> dict[str, Any]:
    original = c.leitura_original_ocr
    return {
        "campo": c.campo, "rotulo": ROTULOS.get(c.campo) or rotulo_campo(c.campo) or c.campo, "indice": c.indice,
        "valor_bruto": c.valor_atual, "valor_normalizado": c.valor_atual_normalizado,
        "confianca": c.confianca_atual, "pagina": c.local_na_folha.pagina, "bbox": c.local_na_folha.caixa,
        "valido": c.validacao.valido, "obrigatorio": c.validacao.obrigatorio,
        "corrigido_manual": c.corrigido_manualmente, "mensagem": c.validacao.mensagem,
        "leitura_original_ocr": {"valor": original.valor_lido, "confianca": original.confianca_ocr} if original else None,
    }


def detalhe_documento(d: Documento) -> dict[str, Any]:
    out = resumo_documento(d)
    repo = repositorio()
    filhos = sorted(repo.resumos(d.partes), key=lambda r: (r.get("_pagina_inicial") or 0, r["_ts"]))
    out["filhos"] = [publico(r) for r in filhos]
    out["assinatura_detalhes"] = d.assinatura.detalhes
    out["qr_conteudo"] = d.qr_code.conteudo if d.qr_code else None
    out["processo_uuid"] = d.qr_code.processo_uuid if d.qr_code else None
    out["processo_id"] = d.qr_code.processo_id if d.qr_code else None
    out["versao_pipeline"] = d.leitura.versao_pipeline
    out["paginas_lidas"] = [
        {"numero": p.numero, "largura": p.largura, "altura": p.altura, "metodo": p.metodo, "motor_ocr": p.motor_ocr,
         "confianca_media": p.confianca_media, "angulo_correcao": p.angulo_correcao, "tem_imagem": bool(p.imagem_chave)}
        for p in d.paginas_lidas
    ]
    r = d.requerimento
    if r is None:
        out["requerimento"] = None
        return out
    out["requerimento"] = {
        "requerente_nome": r.requerente_nome, "cpf_cnpj": r.cpf_cnpj, "tipo_pessoa": r.tipo_pessoa,
        "pessoa_id": r.pessoa_id, "procedimento": r.procedimento, "procedimento_id": r.procedimento_id,
        "tipo_intervencao": r.tipo_intervencao, "tipo_intervencao_id": r.tipo_intervencao_id,
        "municipio": r.municipio, "municipio_id": r.municipio_id, "localidade": r.localidade,
        "latitude": r.latitude, "longitude": r.longitude,
        "latitude_texto": r.latitude_texto, "longitude_texto": r.longitude_texto,
        "descricao_usos": r.descricao_usos, "assinante_nome": r.assinante_nome,
        "data_documento": r.data_documento.isoformat() if r.data_documento else None,
        "confianca_geral": r.confianca_geral,
        "pendencias": r.pendencias, "avisos": r.avisos,
        "status_validacao": r.validacao.situacao, "validado_por_id": r.validacao.validado_por_id,
        "validado_em": _iso(r.validacao.validado_em), "versao": r.versao,
        "finalidades": [
            {"texto": f.texto, "tipo_finalidade_id": f.tipo_finalidade_id, "confianca": f.confianca,
             "valido": f.valido, "chave": f.chave, "detalhes": f.detalhes,
             "estrutura": _estrutura(POR_CHAVE[f.chave]) if f.chave in POR_CHAVE else None}
            for f in r.finalidades
        ],
        "irrigacao": [i.model_dump() for i in r.irrigacao],
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
    repo = repositorio()
    cont = repo.contagem_lote(l.uuid)
    pendentes = sum(cont.get(s, 0) for s in PENDENTES)
    com_erro = cont.get("erro", 0)
    return {
        "uuid": l.uuid, "nome": l.nome, "origem": l.origem,
        "status": "processando" if pendentes else ("concluido_com_erros" if com_erro else "concluido"),
        "total": sum(n for s, n in cont.items() if s != "dividido"),
        "processados": sum(cont.get(s, 0) for s in FINAIS), "em_revisao": cont.get("revisao", 0),
        "validados": cont.get("validado", 0), "com_erro": com_erro,
        "created_at": _iso(l.criado_em), "finalizado_em": None if pendentes else repo.finalizado_em(l.uuid),
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
def saude():
    repositorio().ping()
    return {"status": "ok", "motor_ocr": config().motor_ocr}


@app.post("/documentos", status_code=201, dependencies=Protegido)
async def enviar_documento(arquivo: UploadFile = File(...), usuario_id: int | None = Depends(usuario)):
    dados = await _ler_upload(arquivo)
    nome = arquivo.filename or "documento"
    if nome.lower().endswith(".zip"):
        raise HTTPException(400, "para enviar um ZIP use o envio em lote (/lotes)")
    reg = await run_in_threadpool(P.registrar_documento, dados, nome, _content_type(nome, arquivo.content_type),
                                  usuario_id=usuario_id)
    if not reg.duplicado:
        await run_in_threadpool(enfileirar, [reg.documento.uuid])
    doc = repositorio().obter(reg.documento.uuid) or reg.documento
    corpo = {**resumo_documento(doc), "duplicado": reg.duplicado}
    return JSONResponse(corpo, status_code=200 if reg.duplicado else 201)


@app.post("/lotes", status_code=201, dependencies=Protegido)
async def criar_lote(
    arquivos: list[UploadFile] = File(...),
    nome: str | None = Form(default=None),
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
    return await run_in_threadpool(_registrar_lote, entradas, nome, origem, usuario_id)


def _registrar_lote(entradas: list[tuple[str, bytes]], nome: str | None, origem: str, usuario_id: int | None):
    repo = repositorio()
    lote = Lote(uuid=str(_uuid.uuid4()), nome=nome or f"Lote de {datetime.now(FUSO):%d/%m/%Y %H:%M}",
                origem=origem, criado_por_id=usuario_id)
    repo.salvar_lote(lote)
    novos, duplicados, ignorados = [], [], []
    for fn, dados in entradas:
        if not fn.lower().endswith(EXTENSOES_ACEITAS):
            ignorados.append(fn)  # entra mesmo assim: vira documento com erro, visível no lote
        reg = P.registrar_documento(dados, fn, _content_type(fn, None), lote_uuid=lote.uuid, usuario_id=usuario_id)
        # arquivo já enviado antes não é lido de novo, mas passa a fazer parte deste lote também
        (duplicados if reg.duplicado else novos).append((fn, reg.documento))
    enfileirar([d.uuid for _, d in novos])
    return {
        **resumo_lote(lote),
        "recebidos": len(entradas),
        "novos": len(novos),
        "duplicados": [{"arquivo": fn, "documento_uuid": d.uuid, "status": d.status} for fn, d in duplicados],
        "formato_nao_suportado": ignorados,
    }


@app.get("/lotes", dependencies=Protegido)
def listar_lotes(pagina: int = Query(1, ge=1), tamanho: int = Query(20, ge=1, le=100)):
    total, lotes = repositorio().listar_lotes(pagina, tamanho)
    return {"total": total, "itens": [resumo_lote(l) for l in lotes]}


@app.get("/lotes/{uid}", dependencies=Protegido)
def obter_lote(uid: str):
    lote = _lote(uid)
    repo = repositorio()
    docs = repo.resumos(repo.uuids_do_lote(lote.uuid))
    docs.sort(key=lambda r: (r["_ts"], r.get("_pagina_inicial") or 0))
    return {**resumo_lote(lote), "documentos": [publico(r) for r in docs]}


@app.post("/lotes/{uid}/reprocessar-erros", dependencies=Protegido)
def reprocessar_erros(uid: str):
    lote = _lote(uid)
    repo = repositorio()
    reenfileirar = []
    for res in repo.resumos(repo.uuids_do_lote(lote.uuid)):
        if res["status"] != "erro":
            continue
        with repo.travar(res["uuid"]):
            d = repo.obter(res["uuid"])
            if d.status == "erro":
                d.status = "recebido"
                repo.salvar(d)
                reenfileirar.append(d.uuid)
    enfileirar(reenfileirar)
    return {"reenfileirados": len(reenfileirar)}


@app.get("/lotes/{uid}/exportar", dependencies=Protegido)
def exportar_lote(uid: str, formato: str = Query("csv", pattern="^(csv|xlsx)$")):
    lote = _lote(uid)
    repo = repositorio()
    resumos = [r for r in repo.resumos(repo.uuids_do_lote(lote.uuid)) if r["status"] != "dividido"]
    docs = repo.obter_varios([r["uuid"] for r in sorted(resumos, key=lambda r: r["_ts"])])
    nome = f"lote-{lote.uuid[:8]}"
    if formato == "xlsx":
        return Response(exportacao.para_xlsx(docs),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nome}.xlsx"'})
    return Response(exportacao.para_csv(docs), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}.csv"'})


def _sem_acento_min(texto: str) -> str:
    from ..extracao.texto import sem_acento

    return sem_acento(texto).lower()


def _inicio_do_dia(d: date) -> float:
    return datetime.combine(d, dtime.min, tzinfo=FUSO).timestamp()


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
):
    """Filtros combinados com E. `procedimento`/`municipio`: valor exato (opções em /filtros);
    `requerente`: trecho do nome, sem diferenciar maiúsculas nem acentos; `data_de`/`data_ate`: inclusivos,
    sobre a data do documento ou a data de gravação (dia no fuso do Piauí)."""
    testes = []
    ts_de = ts_ate = None
    if requerente and requerente.strip():
        trecho = _sem_acento_min(requerente.strip())
        testes.append(lambda r: trecho in r["_requerente"])
    if data_de or data_ate:
        if campo_data == "gravacao":
            ts_de = _inicio_do_dia(data_de) if data_de else None
            ts_ate = _inicio_do_dia(data_ate + timedelta(days=1)) - 1e-6 if data_ate else None
        else:
            de, ate = (data_de.isoformat() if data_de else None), (data_ate.isoformat() if data_ate else None)
            testes.append(lambda r: r["data_documento"] is not None
                          and (de is None or r["data_documento"] >= de) and (ate is None or r["data_documento"] <= ate))
    if busca and busca.strip():
        termo = _sem_acento_min(busca.strip())
        # CPF/CNPJ com ou sem máscara (ou só parte dele): compara apenas os dígitos
        digitos = re.sub(r"\D", "", busca)
        por_digitos = bool(digitos) and re.fullmatch(r"[\d\s./-]+", busca.strip()) is not None
        testes.append(lambda r: any(termo in parte for parte in r["_busca"].split("\x1f"))
                      or (por_digitos and digitos in r["_cpf"]))
    total, itens = repositorio().consultar(
        status=status.split(",") if status else None, procedimento=procedimento or None,
        municipio=municipio or None, ts_de=ts_de, ts_ate=ts_ate,
        filtro=(lambda r: all(t(r) for t in testes)) if testes else None, pagina=pagina, tamanho=tamanho,
    )
    return {"total": total, "itens": [publico(r) for r in itens]}


@app.get("/filtros", dependencies=Protegido)
def opcoes_de_filtro():
    """Procedimentos e municípios que aparecem nos requerimentos gravados, com a quantidade de cada."""
    repo = repositorio()
    return {"procedimentos": repo.opcoes("proc"), "municipios": repo.opcoes("mun")}


@app.get("/revisao", dependencies=Protegido)
def fila_revisao(pagina: int = Query(1, ge=1), tamanho: int = Query(500, ge=1, le=2000)):
    """Mais antigos primeiro."""
    total, itens = repositorio().consultar(status=["revisao"], crescente=True, pagina=pagina, tamanho=tamanho)
    return {"total": total, "itens": [publico(r) for r in itens]}


@app.get("/estatisticas", dependencies=Protegido)
def estatisticas():
    repo = repositorio()
    return {"por_status": repo.por_status(), "lotes": repo.total_lotes()}


@app.get("/documentos/{uid}", dependencies=Protegido)
def obter_documento(uid: str):
    return detalhe_documento(_doc(uid))


@app.get("/documentos/{uid}/json", dependencies=Protegido)
def baixar_json(uid: str):
    """O arquivo JSON do documento, como está gravado no armazenamento."""
    d = _doc(uid)
    return Response(d.model_dump_json(indent=2), media_type="application/json",
                    headers={"Content-Disposition": disposicao(f"{d.uuid}.json", "attachment")})


@app.get("/documentos/{uid}/arquivo", dependencies=Protegido)
def baixar_original(uid: str):
    d = _doc(uid)
    return Response(repositorio().store.ler(d.arquivo.chave), media_type=d.arquivo.content_type,
                    headers={"Content-Disposition": disposicao(d.arquivo.nome_original)})


@app.get("/documentos/{uid}/paginas/{numero}/imagem", dependencies=Protegido)
def imagem_pagina(uid: str, numero: int):
    d = _doc(uid)
    p = next((p for p in d.paginas_lidas if p.numero == numero), None)
    if p is None or not p.imagem_chave:
        raise HTTPException(404, "página sem imagem")
    return Response(repositorio().store.ler(p.imagem_chave), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


@app.post("/documentos/{uid}/reprocessar", dependencies=Protegido)
def reprocessar(uid: str):
    u = _doc(uid).uuid
    repo = repositorio()
    with repo.travar(u):
        d = repo.obter(u)
        if d.status == "validado":
            raise HTTPException(409, "documento já validado; reprocessar descartaria a validação")
        if d.status == "processando":
            raise HTTPException(409, "documento já está em processamento")
        d.status = "recebido"
        d = repo.salvar(d)
    enfileirar([d.uuid])
    return resumo_documento(repo.obter(u) or d)


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
def corrigir(uid: str, corpo: Correcoes, usuario_id: int | None = Depends(usuario)):
    u = _doc(uid).uuid
    invalidos = set(corpo.campos) - set(P.CAMPOS_SIMPLES)
    if invalidos:
        raise HTTPException(422, f"campos desconhecidos: {', '.join(sorted(invalidos))}")
    for k in corpo.detalhes:
        try:
            P.chave_detalhe(k)
        except ValueError as e:
            raise HTTPException(422, str(e))
    repo = repositorio()
    with repo.travar(u):
        d = repo.obter(u)
        _editavel(d)
        try:
            P.aplicar_correcoes(d, corpo.model_dump(exclude={"versao"}), usuario_id, versao=corpo.versao)
        except P.ConflitoVersao as e:
            raise HTTPException(409, str(e))
        d = repo.salvar(d)
    return detalhe_documento(d)


class Validacao(BaseModel):
    forcar: bool = False
    justificativa: str | None = None
    versao: int | None = None


@app.post("/documentos/{uid}/validar", dependencies=Protegido)
def validar_documento(uid: str, corpo: Validacao | None = None, usuario_id: int | None = Depends(usuario)):
    u = _doc(uid).uuid
    corpo = corpo or Validacao()
    repo = repositorio()
    with repo.travar(u):
        d = repo.obter(u)
        _editavel(d)
        try:
            P.validar_documento(d, usuario_id, corpo.forcar, corpo.justificativa, corpo.versao)
        except (PermissionError, ValueError, P.ConflitoVersao) as e:
            raise HTTPException(409, str(e))
        d = repo.salvar(d)
    return detalhe_documento(d)


# nomes que a tela já conhece para as entradas do histórico que não são correção de um campo
CAMPO_DO_TIPO = {"validacao_com_pendencias": "__validacao_com_pendencias__", "reprocessamento": "__reprocessamento__"}


def _revisao(r: Revisao) -> dict[str, Any]:
    return {"tipo": r.tipo, "campo": CAMPO_DO_TIPO.get(r.tipo, r.campo), "valor_anterior": r.valor_anterior,
            "valor_novo": r.valor_novo, "usuario_id": r.usuario_id, "created_at": _iso(r.em)}


@app.get("/documentos/{uid}/revisoes", dependencies=Protegido)
def historico(uid: str):
    return [_revisao(r) for r in _doc(uid).historico_de_revisoes]


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


@app.exception_handler(TravaOcupada)
def _trava_ocupada(_: Request, exc: TravaOcupada):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(ValidationError)
def _contrato_violado(_: Request, exc: ValidationError):
    """Uma gravação que violaria o contrato do JSON (ex.: CPF com letra) é recusada, sem gravar nada."""
    return JSONResponse({"detail": f"dados fora do contrato do JSON: {exc.errors()[0].get('msg')}"}, status_code=422)
