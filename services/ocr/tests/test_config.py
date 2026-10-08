"""Conexão com o banco de destino a partir das variáveis DESTINO_DB_* (sem banco)."""
from sqlalchemy.engine import make_url

from ocr_requerimentos.config import Config


def test_url_montada_das_partes(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    c = Config(_env_file=None, destino_db_host="db.exemplo", destino_db_porta=6543, destino_db_nome="ocr",
               destino_db_usuario="ocr_app", destino_db_senha="p@ss:w/rd%1#", destino_db_sslmode="require")
    u = make_url(c.database_url)
    assert u.drivername == "postgresql+psycopg"
    assert (u.host, u.port, u.database, u.username) == ("db.exemplo", 6543, "ocr", "ocr_app")
    assert u.password == "p@ss:w/rd%1#"  # caracteres especiais da senha não quebram a URL
    assert dict(u.query) == {"sslmode": "require"}


def test_database_url_vale_sobre_as_partes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://a:b@h:5432/x")
    assert Config(_env_file=None, destino_db_host="outro").database_url == "postgresql+psycopg://a:b@h:5432/x"


def test_sem_banco_configurado_usa_local(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DESTINO_DB_HOST", raising=False)
    assert Config(_env_file=None).database_url == "postgresql+psycopg://ocr:ocr@localhost:5432/siga"
