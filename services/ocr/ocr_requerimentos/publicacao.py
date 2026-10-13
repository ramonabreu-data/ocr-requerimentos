"""Publicação para o SIGA: o JSON padrão dos requerimentos validados, no bucket do SIGA.

    {SIGA_S3_PREFIXO}requerimentos/{uuid}.json   um requerimento validado (gravado a cada mudança;
                                                 removido se a validação for desfeita por uma correção)
    {SIGA_S3_PREFIXO}requerimentos.json          todos os validados num arquivo só (consolidado), regerado
                                                 no máximo uma vez a cada SIGA_CONSOLIDADO_INTERVALO_S

O formato (`RequerimentoSiga`) é o contrato com o SIGA, separado do JSON interno da ferramenta: os dados
do formulário ficam em `formulario`, já consolidados (valor final de cada campo, com as correções), e a
rastreabilidade embaixo (`campos`, com confiança, leitura original do OCR e se foi corrigido; `validacao`;
`historico_de_revisoes`). Não leva texto nem posição das palavras do OCR. Mudanças incompatíveis sobem
`SCHEMA_VERSAO_SIGA`; o JSON Schema fica em docs/contrato-json/siga-*.schema.json."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field

from .armazenamento import Armazenamento, ArmazenamentoLocal, ArmazenamentoS3
from .config import config
from .modelos import Documento, LeituraOriginalOcr, Modelo, Revisao, agora
from .repositorio import Repositorio, repositorio

log = logging.getLogger(__name__)

SCHEMA_VERSAO_SIGA = 1
BLOCO = 500


# ----------------------------------------------------------------- contrato com o SIGA
class RefSiga(Modelo):
    nome: str | None = Field(description="Texto final do campo (como no formulário, corrigido se preciso).")
    id_siga: int | None = Field(None, description="Id do registro correspondente no SIGA, quando encontrado.")


class Requerente(Modelo):
    nome: str | None
    cpf_cnpj: str | None = Field(description="Com máscara: 000.000.000-00 ou 00.000.000/0000-00.")
    tipo_pessoa: Literal["F", "J"] | None = Field(description="F = física, J = jurídica.")
    id_siga: int | None = Field(None, description="core_pessoa.id no SIGA.")


class Localizacao(Modelo):
    municipio: RefSiga
    localidade: str | None
    latitude: float | None = Field(description="Graus decimais (negativo = Sul).")
    longitude: float | None = Field(description="Graus decimais (negativo = Oeste).")
    srid: int = Field(4674, description="4674 = SIRGAS 2000.")
    latitude_como_escrita: str | None = Field(description="Coordenada como está no documento (graus, minutos, segundos).")
    longitude_como_escrita: str | None


class FinalidadeSiga(Modelo):
    nome: str | None
    id_siga: int | None = Field(None, description="outorga_tipofinalidadeuso.id no SIGA.")
    chave: str | None = Field(None, description="Identificador da finalidade no formulário (ex.: criacao_animal).")
    detalhes: dict[str, Any] | None = Field(None, description="Dados próprios da finalidade, já normalizados.")


class LinhaIrrigacaoSiga(Modelo):
    ordem: int
    sistema: str | None
    area_ha: float | None
    cultura: str | None


class Formulario(Modelo):
    """Os dados do formulário do requerimento, consolidados: valor final de cada campo."""

    requerente: Requerente
    procedimento: RefSiga
    tipo_intervencao: RefSiga
    localizacao: Localizacao
    finalidades: list[FinalidadeSiga]
    irrigacao: list[LinhaIrrigacaoSiga]
    descricao_usos: str | None
    assinante_nome: str | None
    data_documento: date | None


class CampoRastreado(Modelo):
    campo: str
    indice: int | None = Field(None, description="Posição em listas (finalidade, linha da irrigação, item de detalhe).")
    valor_final: str | None = Field(description="Valor final do campo (lido pelo OCR ou corrigido na revisão).")
    confianca_final: float | None = Field(description="Confiança do valor final, 0–100; 100 quando corrigido à mão.")
    corrigido_manualmente: bool
    leitura_original_ocr: LeituraOriginalOcr | None = Field(
        description="O que o OCR leu, antes da revisão; nulo quando o campo foi incluído na revisão.")


class ValidacaoSiga(Modelo):
    validado_por_id: int | None = Field(description="Usuário do SIGA que validou.")
    validado_em: datetime | None
    com_pendencias: bool = Field(description="Validado mesmo com pendências, com justificativa.")
    pendencias: list[str] = Field(description="Pendências que existiam no momento da validação (se houve).")
    justificativa: str | None
    modo: Literal["conferencia", "envio"] = Field(
        description="conferencia: validado por uma pessoa na tela de conferência; envio: enviado como já conferido "
                    "e validado automaticamente ao fim da leitura, sem conferência na ferramenta.")


class Origem(Modelo):
    documento_uuid: str
    arquivo_nome: str
    arquivo_sha256: str
    documento_pai_uuid: str | None = Field(None, description="Arquivo com vários requerimentos de onde esta parte saiu.")
    pagina_inicial: int | None = None
    assinatura: str | None = Field(None, description="digital | manuscrita | ausente | indeterminada")
    processo_uuid_qrcode: str | None = Field(None, description="Processo do SIGA lido no QR code do PDF, se houver.")
    processo_id_qrcode: int | None = None
    versao_pipeline: str | None = Field(None, description="Versão do OCR que fez a leitura.")


class RequerimentoSiga(Modelo):
    schema_: Literal["semarh.ocr.requerimento"] = Field("semarh.ocr.requerimento", alias="schema")
    schema_versao: int = SCHEMA_VERSAO_SIGA
    uuid: str = Field(description="Identificador do requerimento (o mesmo do documento na ferramenta).")
    numero: str | None = Field(
        description="Número de registro legível e único: REQ-AAAA-NNNNNN (ano do recebimento e sequência no ano); "
                    "parte de um arquivo com vários requerimentos: REQ-AAAA-NNNNNN-n.")
    versao: int = Field(description="Sobe a cada gravação; o maior número é o mais recente.")
    atualizado_em: datetime
    formulario: Formulario
    validacao: ValidacaoSiga
    confianca_geral: float | None = Field(description="Confiança média da leitura, 0–100.")
    avisos: list[str]
    campos: list[CampoRastreado] = Field(description="Rastreabilidade de cada campo do formulário.")
    historico_de_revisoes: list[Revisao]
    origem: Origem

    model_config = {**Modelo.model_config, "populate_by_name": True}


class ConsolidadoSiga(Modelo):
    """Forma do arquivo requerimentos.json (gravado em fluxo, na ordem destes campos)."""

    schema_: Literal["semarh.ocr.requerimentos"] = Field("semarh.ocr.requerimentos", alias="schema")
    schema_versao: int = SCHEMA_VERSAO_SIGA
    gerado_em: datetime
    requerimentos: list[RequerimentoSiga] = Field(description="Todos os requerimentos validados, do mais antigo ao mais novo.")
    total: int

    model_config = {**Modelo.model_config, "populate_by_name": True}


def para_siga(d: Documento) -> RequerimentoSiga:
    r = d.requerimento
    if r is None:
        raise ValueError("documento sem requerimento extraído")
    justificativa = pendencias = None
    for h in reversed(d.historico_de_revisoes):
        if h.tipo == "validacao_com_pendencias":
            justificativa, pendencias = h.valor_novo, [p for p in (h.valor_anterior or "").split("; ") if p]
            break
    return RequerimentoSiga(
        uuid=d.uuid, numero=d.numero, versao=r.versao, atualizado_em=d.atualizado_em,
        formulario=Formulario(
            requerente=Requerente(nome=r.requerente_nome, cpf_cnpj=r.cpf_cnpj, tipo_pessoa=r.tipo_pessoa,
                                  id_siga=r.pessoa_id),
            procedimento=RefSiga(nome=r.procedimento, id_siga=r.procedimento_id),
            tipo_intervencao=RefSiga(nome=r.tipo_intervencao, id_siga=r.tipo_intervencao_id),
            localizacao=Localizacao(
                municipio=RefSiga(nome=r.municipio, id_siga=r.municipio_id), localidade=r.localidade,
                latitude=r.latitude, longitude=r.longitude, srid=r.srid,
                latitude_como_escrita=r.latitude_texto, longitude_como_escrita=r.longitude_texto,
            ),
            finalidades=[FinalidadeSiga(nome=f.texto, id_siga=f.tipo_finalidade_id, chave=f.chave, detalhes=f.detalhes)
                         for f in r.finalidades],
            irrigacao=[LinhaIrrigacaoSiga(ordem=i.ordem, sistema=i.sistema, area_ha=i.area_ha, cultura=i.cultura)
                       for i in r.irrigacao],
            descricao_usos=r.descricao_usos, assinante_nome=r.assinante_nome, data_documento=r.data_documento,
        ),
        validacao=ValidacaoSiga(
            validado_por_id=r.validacao.validado_por_id, validado_em=r.validacao.validado_em,
            com_pendencias=justificativa is not None, pendencias=pendencias or [], justificativa=justificativa,
            modo=r.validacao.modo,
        ),
        confianca_geral=r.confianca_geral, avisos=r.avisos,
        campos=[CampoRastreado(campo=c.campo, indice=c.indice, valor_final=c.valor_atual,
                               confianca_final=c.confianca_atual, corrigido_manualmente=c.corrigido_manualmente,
                               leitura_original_ocr=c.leitura_original_ocr) for c in r.campos],
        historico_de_revisoes=d.historico_de_revisoes,
        origem=Origem(
            documento_uuid=d.uuid, arquivo_nome=d.arquivo.nome_original, arquivo_sha256=d.arquivo.sha256,
            documento_pai_uuid=d.documento_pai_uuid, pagina_inicial=d.pagina_inicial, assinatura=d.assinatura.tipo,
            processo_uuid_qrcode=d.qr_code.processo_uuid if d.qr_code else None,
            processo_id_qrcode=d.qr_code.processo_id if d.qr_code else None,
            versao_pipeline=d.leitura.versao_pipeline,
        ),
    )


def json_siga(d: Documento, indent: int | None = 2) -> str:
    return para_siga(d).model_dump_json(by_alias=True, indent=indent)


# ----------------------------------------------------------------- consolidado
def consolidado(repo: Repositorio) -> Iterator[bytes]:
    """O requerimentos.json em pedaços (memória constante): validados do mais antigo ao mais novo."""
    yield (f'{{"schema": "semarh.ocr.requerimentos", "schema_versao": {SCHEMA_VERSAO_SIGA}, '
           f'"gerado_em": {json.dumps(agora().isoformat())}, "requerimentos": [').encode()
    total, desloc = 0, 0
    while True:
        _, resumos = repo.consultar(status=["validado"], crescente=True, pagina=desloc // BLOCO + 1, tamanho=BLOCO)
        if not resumos:
            break
        desloc += len(resumos)
        partes = []
        for d in repo.obter_varios([r["uuid"] for r in resumos]):
            if d.status == "validado" and d.requerimento is not None:
                partes.append(json_siga(d, indent=None))
        if partes:
            yield ((",\n" if total else "\n") + ",\n".join(partes)).encode()
            total += len(partes)
        if len(resumos) < BLOCO:
            break
    yield f'\n], "total": {total}}}\n'.encode()


# ----------------------------------------------------------------- destino e envio
@lru_cache
def destino() -> Armazenamento | None:
    """Bucket do SIGA (ou pasta local, em testes). None = publicação desligada."""
    c = config()
    if c.siga_s3_bucket:
        return ArmazenamentoS3(bucket=c.siga_s3_bucket, endpoint=c.siga_s3_endpoint,
                               access_key=c.siga_s3_access_key, secret_key=c.siga_s3_secret_key)
    if c.siga_destino_dir:
        return ArmazenamentoLocal(c.siga_destino_dir)
    return None


def chave_requerimento(u: str) -> str:
    return f"{config().siga_s3_prefixo}requerimentos/{u}.json"


def chave_consolidado() -> str:
    return f"{config().siga_s3_prefixo}requerimentos.json"


def publicar_documento(u: str, repo: Repositorio | None = None, dest: Armazenamento | None = None) -> str:
    """Põe no bucket do SIGA o estado atual do requerimento: grava se validado, remove se não está mais.
    Idempotente (sempre relê o documento), então pode ser repetido sem efeito colateral."""
    repo = repo or repositorio()
    dest = dest or destino()
    if dest is None:
        return "desligada"
    d = repo.obter(u)
    if d is not None and d.status == "validado" and d.requerimento is not None:
        dest.salvar(chave_requerimento(u), json_siga(d).encode(), "application/json")
        return "publicado"
    dest.remover(chave_requerimento(u))
    return "removido"


def gravar_consolidado(repo: Repositorio | None = None, dest: Armazenamento | None = None) -> int:
    """Gera o requerimentos.json num arquivo temporário e envia (em partes) ao bucket do SIGA."""
    repo = repo or repositorio()
    dest = dest or destino()
    if dest is None:
        return 0
    fd, caminho = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "wb") as f:
            for pedaco in consolidado(repo):
                f.write(pedaco)
        dest.salvar_arquivo(chave_consolidado(), caminho, "application/json")
    finally:
        os.unlink(caminho)
    repo.r.set(repo._k("siga", "consolidado_em"), agora().isoformat())
    return repo.por_status().get("validado", 0)


def apos_salvar(doc: Documento, status_anterior: str | None) -> None:
    """Chamado pelo repositório depois de cada gravação: entrou ou saiu dos validados -> publica."""
    if destino() is None or "validado" not in (doc.status, status_anterior):
        return
    from .worker import agendar_consolidado, publicar_siga

    publicar_siga.delay(doc.uuid)
    agendar_consolidado()


def situacao(repo: Repositorio | None = None) -> dict[str, Any]:
    repo = repo or repositorio()
    c = config()
    ativo = destino() is not None
    return {
        "publicacao_ativa": ativo,
        "destino": (f"s3://{c.siga_s3_bucket}/{c.siga_s3_prefixo}" if c.siga_s3_bucket
                    else c.siga_destino_dir) if ativo else None,
        "validados": repo.por_status().get("validado", 0),
        "consolidado_gerado_em": repo.r.get(repo._k("siga", "consolidado_em")),
        "intervalo_consolidado_s": c.siga_consolidado_intervalo_s,
    }
