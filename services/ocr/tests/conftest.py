"""Configuração dos testes.

Unitários e de extração rodam sem banco. Os de integração (marcador `db`) exigem
TEST_DATABASE_URL apontando para um PostgreSQL com PostGIS **descartável** (o banco é recriado)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).parent))

TEST_DB = os.environ.get("TEST_DATABASE_URL")
_STORAGE = tempfile.mkdtemp(prefix="ocr-teste-")
# precisa acontecer antes de importar o pacote: config() é cacheada
os.environ.setdefault("STORAGE_DIR", _STORAGE)
os.environ["STORAGE_BACKEND"] = "local"
os.environ["CELERY_EAGER"] = "true"
os.environ["CELERY_BROKER_URL"] = "memory://"
os.environ["CRIAR_VIEWS"] = "true"  # test_ct98 consulta as views
if TEST_DB:
    os.environ["DATABASE_URL"] = TEST_DB
    os.environ["REFERENCIAS"] = "siga"

from ocr_requerimentos.dados_referencia import CULTURAS, SISTEMAS_IRRIGACAO  # noqa: E402
from ocr_requerimentos.extracao.referencias import ReferenciasEstaticas  # noqa: E402
from ocr_requerimentos.extracao.texto import Ref  # noqa: E402
from ocr_requerimentos.imagem.ocr import TesseractOCR  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def pdf_exemplo() -> bytes:
    return (FIXTURES / "requerimento_exemplo.pdf").read_bytes()


@pytest.fixture(scope="session")
def motor():
    return TesseractOCR()


@pytest.fixture
def refs() -> ReferenciasEstaticas:
    return ReferenciasEstaticas(
        municipios=[Ref(1, "Altos"), Ref(2, "Teresina"), Ref(3, "Alto Longá"), Ref(4, "José de Freitas"),
                    Ref(5, "Campo Maior"), Ref(6, "São João do Piauí")],
        procedimentos=[Ref(10, "Regularização de Poço Tubular"), Ref(11, "Outorga de Direito de Uso")],
        intervencoes=[Ref(20, "Poço Tubular"), Ref(21, "Captação Superficial"), Ref(22, "Poço Amazonas")],
        finalidades=[Ref(30, "Irrigação"), Ref(31, "Abastecimento Humano"), Ref(32, "Dessedentação Animal")],
        sistemas_irrigacao=[Ref(100 + i, n, s) for i, (n, s) in enumerate(SISTEMAS_IRRIGACAO)],
        culturas=[Ref(200 + i, n, s) for i, (n, s) in enumerate(CULTURAS)],
        pessoas={"05974965361": Ref(1, "Ramon Teste")},
        processos={"6f1c2a3e-9b7d-4c1e-8f2a-1b2c3d4e5f60": Ref(77, "2026.0001.000123")},
    )


# ------------------------------------------------------------------ integração
def pytest_collection_modifyitems(config, items):
    if TEST_DB:
        return
    pular = pytest.mark.skip(reason="defina TEST_DATABASE_URL para rodar os testes de integração")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(pular)


@pytest.fixture(scope="session")
def banco():
    """Recria o banco de teste: stub do SIGA + migrations do schema ocr."""
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import create_engine, text

    eng = create_engine(TEST_DB)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS ocr CASCADE"))
        c.execute(text("DROP TABLE IF EXISTS public.alembic_version_ocr"))
        for t in ("core_pessoafisica", "core_pessoajuridica", "core_pessoa", "core_municipio", "core_estado",
                  "protocolo_processo", "protocolo_procedimento", "outorga_tipointervencao",
                  "outorga_tipofinalidadeuso"):
            c.execute(text(f"DROP TABLE IF EXISTS public.{t} CASCADE"))
        for sql in sorted((RAIZ.parents[1] / "db" / "dev").glob("*.sql")):
            c.exec_driver_sql(sql.read_text(encoding="utf-8"))
    cfg = AlembicConfig(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def limpar(banco):
    from sqlalchemy import text

    with banco.begin() as c:
        c.execute(text("TRUNCATE ocr.revisao, ocr.campo_extraido, ocr.requerimento_irrigacao, "
                       "ocr.requerimento_finalidade, ocr.requerimento, ocr.pagina, ocr.documento, ocr.lote "
                       "RESTART IDENTITY CASCADE"))
    from ocr_requerimentos.pipeline.persistencia import referencias_padrao

    refs = referencias_padrao()
    if hasattr(refs, "limpar_cache"):
        refs.limpar_cache()
    yield


@pytest.fixture
def cliente(limpar):
    from fastapi.testclient import TestClient

    from ocr_requerimentos.api.main import app

    return TestClient(app)
