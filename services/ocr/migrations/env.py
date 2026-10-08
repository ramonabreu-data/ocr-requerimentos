from alembic import context
from sqlalchemy import create_engine, pool

from ocr_requerimentos.config import config

# tabela de controle própria, separada da django_migrations
VERSAO = {"version_table": "alembic_version_ocr", "version_table_schema": "public"}


def run_migrations_offline() -> None:
    context.configure(url=config().database_url, literal_binds=True, **VERSAO)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    eng = create_engine(config().database_url, poolclass=pool.NullPool)
    with eng.connect() as conn:
        context.configure(connection=conn, **VERSAO)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
