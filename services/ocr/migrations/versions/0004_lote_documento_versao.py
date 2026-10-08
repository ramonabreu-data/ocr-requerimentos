"""documento em vários lotes e versão do requerimento (trava otimista da revisão)

Revision ID: 0004
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- o mesmo arquivo (mesmo sha256) pode ser enviado em mais de um lote; documento.lote_id
        -- continua sendo o lote em que ele entrou pela primeira vez
        CREATE TABLE ocr.lote_documento (
          lote_id       bigint NOT NULL REFERENCES ocr.lote(id) ON DELETE CASCADE,
          documento_id  bigint NOT NULL REFERENCES ocr.documento(id) ON DELETE CASCADE,
          nome_arquivo  varchar(255),                -- nome com que o arquivo veio neste lote
          created_at    timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (lote_id, documento_id)
        );
        CREATE INDEX ix_lote_documento_documento ON ocr.lote_documento(documento_id);
        INSERT INTO ocr.lote_documento (lote_id, documento_id, nome_arquivo, created_at)
          SELECT lote_id, id, nome_original, created_at FROM ocr.documento WHERE lote_id IS NOT NULL;

        -- incrementada a cada gravação; correção/validação com versão antiga recebe 409
        ALTER TABLE ocr.requerimento ADD COLUMN versao integer NOT NULL DEFAULT 1;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE ocr.requerimento DROP COLUMN versao")
    op.execute("DROP TABLE ocr.lote_documento")
