"""dicionários iniciais de sistemas de irrigação e culturas

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

from ocr_requerimentos.dados_referencia import CULTURAS, SISTEMAS_IRRIGACAO

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = sa.text(
        "INSERT INTO ocr.dominio (tipo, valor, sinonimos) VALUES (:t, :v, :s) ON CONFLICT (tipo, valor) DO NOTHING"
    )
    conn = op.get_bind()
    for valor, sin in SISTEMAS_IRRIGACAO:
        conn.execute(sql, {"t": "sistema_irrigacao", "v": valor, "s": sin})
    for valor, sin in CULTURAS:
        conn.execute(sql, {"t": "cultura", "v": valor, "s": sin})


def downgrade() -> None:
    op.execute("DELETE FROM ocr.dominio WHERE tipo IN ('sistema_irrigacao', 'cultura')")
