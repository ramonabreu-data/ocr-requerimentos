"""Conexão com o banco do SIGA (só leitura) a partir das variáveis SIGA_DB_* (sem banco)."""
from sqlalchemy.engine import make_url

from ocr_requerimentos.config import Config


def test_url_montada_das_partes(monkeypatch):
    monkeypatch.delenv("SIGA_DATABASE_URL", raising=False)
    c = Config(_env_file=None, siga_db_host="db.exemplo", siga_db_porta=6543, siga_db_nome="siga",
               siga_db_usuario="ocr_leitura", siga_db_senha="p@ss:w/rd%1#", siga_db_sslmode="require")
    u = make_url(c.siga_database_url)
    assert u.drivername == "postgresql+psycopg"
    assert (u.host, u.port, u.database, u.username) == ("db.exemplo", 6543, "siga", "ocr_leitura")
    assert u.password == "p@ss:w/rd%1#"  # caracteres especiais da senha não quebram a URL
    assert dict(u.query) == {"sslmode": "require"}


def test_siga_database_url_vale_sobre_as_partes(monkeypatch):
    monkeypatch.setenv("SIGA_DATABASE_URL", "postgresql+psycopg://a:b@h:5432/x")
    assert Config(_env_file=None, siga_db_host="outro").siga_database_url == "postgresql+psycopg://a:b@h:5432/x"


def test_sem_banco_configurado_usa_local(monkeypatch):
    monkeypatch.delenv("SIGA_DATABASE_URL", raising=False)
    monkeypatch.delenv("SIGA_DB_HOST", raising=False)
    assert Config(_env_file=None).siga_database_url == "postgresql+psycopg://ocr:ocr@localhost:5432/siga"
