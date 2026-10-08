"""restrições de domínio e unicidade no schema ocr

Revision ID: 0005

Antes de criar, confere se algum registro existente viola as regras e, se houver, para com a lista
(nada é apagado ou corrigido automaticamente).
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _em(*valores: str) -> str:
    return "IN (" + ", ".join(f"'{v}'" for v in valores) + ")"


def _conf(col: str) -> str:
    return f"{col} BETWEEN 0 AND 100"


CHECKS = [
    ("lote", "ck_lote_origem", "origem " + _em("upload", "zip", "pasta_monitorada")),
    ("lote", "ck_lote_status", "status " + _em("pendente", "processando", "concluido", "concluido_com_erros")),
    ("documento", "ck_documento_status",
     "status " + _em("recebido", "processando", "extraido", "revisao", "validado", "erro", "dividido")),
    ("documento", "ck_documento_tipo_entrada", "tipo_entrada " + _em("pdf_texto", "pdf_imagem", "imagem")),
    ("documento", "ck_documento_metodo_extracao",
     "metodo_extracao " + _em("texto_nativo", "ocr", "qrcode+texto_nativo", "qrcode+ocr")),
    ("documento", "ck_documento_assinatura_tipo",
     "assinatura_tipo " + _em("digital", "manuscrita", "ausente", "indeterminada")),
    ("documento", "ck_documento_sha256", "sha256 ~ '^[0-9a-f]{64}$'"),
    ("documento", "ck_documento_tamanho", "tamanho_bytes >= 0"),
    ("documento", "ck_documento_tentativas", "tentativas >= 0"),
    ("pagina", "ck_pagina_metodo", "metodo " + _em("texto_nativo", "ocr")),
    ("pagina", "ck_pagina_confianca", _conf("confianca_media")),
    ("requerimento", "ck_requerimento_status_validacao", "status_validacao " + _em("pendente", "validado")),
    ("requerimento", "ck_requerimento_tipo_pessoa", "tipo_pessoa " + _em("F", "J")),
    # só dígitos e a pontuação de CPF/CNPJ; o mesmo CPF pode ter vários requerimentos (sem UNIQUE)
    ("requerimento", "ck_requerimento_cpf_cnpj", "cpf_cnpj ~ '^[0-9./-]*$'"),
    ("requerimento", "ck_requerimento_confianca", _conf("confianca_geral")),
    ("requerimento", "ck_requerimento_validado",
     "status_validacao <> 'validado' OR validado_em IS NOT NULL"),
    ("requerimento", "ck_requerimento_versao", "versao >= 1"),
    ("requerimento_finalidade", "ck_finalidade_confianca", _conf("confianca")),
    ("requerimento_irrigacao", "ck_irrigacao_confianca", _conf("confianca")),
    ("requerimento_irrigacao", "ck_irrigacao_area", "area_ha >= 0"),
    ("requerimento_irrigacao", "ck_irrigacao_ordem", "ordem >= 1"),
    ("campo_extraido", "ck_campo_confianca", _conf("confianca")),
]

# (nome, tabela, colunas): o mesmo campo não pode aparecer duas vezes no mesmo requerimento.
# COALESCE em vez de NULLS NOT DISTINCT para funcionar também em PostgreSQL < 15.
UNICOS = [
    ("ux_campo_extraido_chave", "campo_extraido", "requerimento_id, campo, COALESCE(indice, -1)"),
    ("ux_irrigacao_ordem", "requerimento_irrigacao", "requerimento_id, ordem"),
]


def upgrade() -> None:
    conn = op.get_bind()
    problemas = []
    for tabela, nome, expr in CHECKS:
        n = conn.scalar(sa.text(f"SELECT count(*) FROM ocr.{tabela} WHERE NOT ({expr})"))
        if n:
            problemas.append(f"{nome}: {n} registro(s) em ocr.{tabela} violam ({expr})")
    for nome, tabela, cols in UNICOS:
        n = conn.scalar(sa.text(
            f"SELECT count(*) FROM (SELECT 1 FROM ocr.{tabela} GROUP BY {cols} HAVING count(*) > 1) d"))
        if n:
            problemas.append(f"{nome}: {n} grupo(s) repetidos em ocr.{tabela} ({cols})")
    if problemas:
        raise RuntimeError("dados existentes violam as novas restrições; corrija antes de migrar:\n  "
                           + "\n  ".join(problemas))
    for tabela, nome, expr in CHECKS:
        op.execute(f"ALTER TABLE ocr.{tabela} ADD CONSTRAINT {nome} CHECK ({expr})")
    for nome, tabela, cols in UNICOS:
        op.execute(f"CREATE UNIQUE INDEX {nome} ON ocr.{tabela} ({cols})")


def downgrade() -> None:
    for nome, _, _ in UNICOS:
        op.execute(f"DROP INDEX ocr.{nome}")
    for tabela, nome, _ in CHECKS:
        op.execute(f"ALTER TABLE ocr.{tabela} DROP CONSTRAINT {nome}")
