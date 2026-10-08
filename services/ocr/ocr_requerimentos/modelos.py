"""Modelos do schema `ocr`. As tabelas do SIGA (schema public) são só lidas, nunca mapeadas aqui."""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import config

SCHEMA = "ocr"


class Base(DeclarativeBase):
    pass


def _uuid_col():
    return mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=_uuid.uuid4)


def _agora():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Lote(Base):
    __tablename__ = "lote"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    uuid: Mapped[_uuid.UUID] = _uuid_col()
    nome: Mapped[str | None] = mapped_column(String(200))
    origem: Mapped[str] = mapped_column(String(20), nullable=False)  # upload | zip | pasta_monitorada
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente")
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    em_revisao: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    com_erro: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criado_por_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _agora()
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    documentos: Mapped[list["Documento"]] = relationship(back_populates="lote")  # lote de origem


class LoteDocumento(Base):
    """Documentos de cada lote. Um arquivo repetido entra em outro lote sem virar outro documento."""

    __tablename__ = "lote_documento"
    __table_args__ = {"schema": SCHEMA}

    lote_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.lote.id", ondelete="CASCADE"), primary_key=True)
    documento_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.documento.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    nome_arquivo: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _agora()


class Documento(Base):
    __tablename__ = "documento"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    uuid: Mapped[_uuid.UUID] = _uuid_col()
    lote_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.lote.id", ondelete="SET NULL"), index=True)
    documento_pai_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.documento.id", ondelete="CASCADE"))
    nome_original: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    tamanho_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    tipo_entrada: Mapped[str | None] = mapped_column(String(20))
    metodo_extracao: Mapped[str | None] = mapped_column(String(20))
    paginas: Mapped[int | None] = mapped_column(SmallInteger)
    pagina_inicial: Mapped[int | None] = mapped_column(SmallInteger)  # quando veio de divisão
    assinatura_tipo: Mapped[str | None] = mapped_column(String(20))
    assinatura_detalhes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    qr_conteudo: Mapped[str | None] = mapped_column(Text)
    processo_uuid: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    processo_id: Mapped[int | None] = mapped_column(BigInteger)  # public.protocolo_processo
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="recebido", index=True)
    erro: Mapped[str | None] = mapped_column(Text)
    tentativas: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    duracao_ms: Mapped[int | None] = mapped_column(Integer)
    versao_pipeline: Mapped[str | None] = mapped_column(String(20))
    config_extracao: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    criado_por_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _agora()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    lote: Mapped[Lote | None] = relationship(back_populates="documentos")
    paginas_lidas: Mapped[list["Pagina"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan", order_by="Pagina.numero"
    )
    requerimento: Mapped["Requerimento | None"] = relationship(
        back_populates="documento", cascade="all, delete-orphan", uselist=False
    )
    filhos: Mapped[list["Documento"]] = relationship(remote_side=[documento_pai_id], viewonly=True)


class Pagina(Base):
    __tablename__ = "pagina"
    __table_args__ = (UniqueConstraint("documento_id", "numero"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.documento.id", ondelete="CASCADE"), nullable=False)
    numero: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    largura: Mapped[int | None] = mapped_column(Integer)
    altura: Mapped[int | None] = mapped_column(Integer)
    imagem_key: Mapped[str | None] = mapped_column(Text)
    angulo_correcao: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    metodo: Mapped[str | None] = mapped_column(String(20))
    motor_ocr: Mapped[str | None] = mapped_column(String(20))
    texto_bruto: Mapped[str | None] = mapped_column(Text)
    ocr_json: Mapped[list[Any] | None] = mapped_column(JSONB)
    confianca_media: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    documento: Mapped[Documento] = relationship(back_populates="paginas_lidas")


class Requerimento(Base):
    __tablename__ = "requerimento"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    documento_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.documento.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    requerente_nome: Mapped[str | None] = mapped_column(String(255))
    cpf_cnpj: Mapped[str | None] = mapped_column(String(18), index=True)
    tipo_pessoa: Mapped[str | None] = mapped_column(CHAR(1))
    pessoa_id: Mapped[int | None] = mapped_column(BigInteger)
    procedimento_texto: Mapped[str | None] = mapped_column(String(200))
    procedimento_id: Mapped[int | None] = mapped_column(BigInteger)
    tipo_intervencao_texto: Mapped[str | None] = mapped_column(String(250))
    tipo_intervencao_id: Mapped[int | None] = mapped_column(BigInteger)
    municipio_texto: Mapped[str | None] = mapped_column(String(255))
    municipio_id: Mapped[int | None] = mapped_column(BigInteger)
    localidade: Mapped[str | None] = mapped_column(String(100))
    latitude_texto: Mapped[str | None] = mapped_column(String(40))
    longitude_texto: Mapped[str | None] = mapped_column(String(40))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    geom = mapped_column(Geometry("POINT", srid=4674), nullable=True)
    descricao_usos: Mapped[str | None] = mapped_column(Text)
    assinante_nome: Mapped[str | None] = mapped_column(String(255))
    data_documento: Mapped[date | None] = mapped_column(Date)
    confianca_geral: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    pendencias: Mapped[list[str] | None] = mapped_column(JSONB)
    avisos: Mapped[list[str] | None] = mapped_column(JSONB)
    status_validacao: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente")
    validado_por_id: Mapped[int | None] = mapped_column(Integer)
    validado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    versao: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = _agora()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    documento: Mapped[Documento] = relationship(back_populates="requerimento")
    finalidades: Mapped[list["RequerimentoFinalidade"]] = relationship(
        cascade="all, delete-orphan", order_by="RequerimentoFinalidade.id"
    )
    irrigacao: Mapped[list["RequerimentoIrrigacao"]] = relationship(
        cascade="all, delete-orphan", order_by="RequerimentoIrrigacao.ordem"
    )
    campos: Mapped[list["CampoExtraido"]] = relationship(cascade="all, delete-orphan", order_by="CampoExtraido.id")


class RequerimentoFinalidade(Base):
    __tablename__ = "requerimento_finalidade"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requerimento_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.requerimento.id", ondelete="CASCADE"), nullable=False
    )
    finalidade_texto: Mapped[str | None] = mapped_column(String(250))
    tipo_finalidade_id: Mapped[int | None] = mapped_column(BigInteger)
    confianca: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    valido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    chave: Mapped[str | None] = mapped_column(String(40))  # extracao.finalidades (ex.: criacao_animal)
    detalhes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # dados próprios, normalizados


class Dominio(Base):
    __tablename__ = "dominio"
    __table_args__ = (UniqueConstraint("tipo", "valor"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    valor: Mapped[str] = mapped_column(String(150), nullable=False)
    sinonimos: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RequerimentoIrrigacao(Base):
    __tablename__ = "requerimento_irrigacao"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requerimento_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.requerimento.id", ondelete="CASCADE"), nullable=False
    )
    ordem: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sistema_texto: Mapped[str | None] = mapped_column(String(150))
    sistema_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.dominio.id"))
    area_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cultura_texto: Mapped[str | None] = mapped_column(String(150))
    cultura_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.dominio.id"))
    confianca: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    valido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CampoExtraido(Base):
    """Um registro por campo lido: valor bruto, normalizado, confiança e posição na página."""

    __tablename__ = "campo_extraido"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requerimento_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.requerimento.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campo: Mapped[str] = mapped_column(String(60), nullable=False)
    indice: Mapped[int | None] = mapped_column(SmallInteger)  # posição em listas (finalidade/irrigação)
    valor_bruto: Mapped[str | None] = mapped_column(Text)
    valor_normalizado: Mapped[str | None] = mapped_column(Text)
    confianca: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    pagina: Mapped[int | None] = mapped_column(SmallInteger)
    bbox: Mapped[list[float] | None] = mapped_column(JSONB)
    valido: Mapped[bool | None] = mapped_column(Boolean)
    obrigatorio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    corrigido_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mensagem: Mapped[str | None] = mapped_column(Text)
    valor_ocr: Mapped[str | None] = mapped_column(Text)  # leitura original, mantida após correção
    confianca_ocr: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class Revisao(Base):
    __tablename__ = "revisao"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requerimento_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.requerimento.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campo: Mapped[str] = mapped_column(String(60), nullable=False)
    valor_anterior: Mapped[str | None] = mapped_column(Text)
    valor_novo: Mapped[str | None] = mapped_column(Text)
    usuario_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _agora()


@lru_cache
def engine() -> Engine:
    return create_engine(config().database_url, pool_pre_ping=True, future=True)


@lru_cache
def fabrica_sessao() -> sessionmaker:
    return sessionmaker(bind=engine(), expire_on_commit=False)


def sessao():
    return fabrica_sessao()()
