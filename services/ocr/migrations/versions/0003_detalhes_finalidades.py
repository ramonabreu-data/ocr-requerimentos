"""detalhes por finalidade e listas completas do formulário de requerimento

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op

from ocr_requerimentos.dados_referencia import DOMINIOS

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requerimento_finalidade", sa.Column("chave", sa.String(40)), schema="ocr")
    op.add_column("requerimento_finalidade", sa.Column("detalhes", sa.dialects.postgresql.JSONB), schema="ocr")
    conn = op.get_bind()
    inserir = sa.text(
        "INSERT INTO ocr.dominio (tipo, valor, sinonimos, ativo) VALUES (:t, :v, :s, true) "
        "ON CONFLICT (tipo, valor) DO UPDATE SET sinonimos = EXCLUDED.sinonimos, ativo = true"
    )
    for tipo, opcoes in DOMINIOS.items():
        for valor, sinonimos in opcoes:
            conn.execute(inserir, {"t": tipo, "v": valor, "s": sinonimos})
        # valores da lista provisória da 0002 que o formulário não tem: desativados (podem ter itens ligados)
        conn.execute(
            sa.text("UPDATE ocr.dominio SET ativo = false WHERE tipo = :t AND NOT (valor = ANY(:vs))"),
            {"t": tipo, "vs": [v for v, _ in opcoes]},
        )


def downgrade() -> None:
    op.drop_column("requerimento_finalidade", "detalhes", schema="ocr")
    op.drop_column("requerimento_finalidade", "chave", schema="ocr")
    op.execute(
        "DELETE FROM ocr.dominio WHERE tipo IN ('prestador', 'especie_aquicultura', 'estabelecimento', "
        "'especie_animal', 'sistema_criacao', 'unidade', 'uso_outro', 'combustivel')"
    )
