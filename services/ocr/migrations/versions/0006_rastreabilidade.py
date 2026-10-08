"""versão do pipeline por documento, leitura original do OCR por campo e views de acurácia

Revision ID: 0006

As views só servem para análise (o pipeline não as usa). Com CRIAR_VIEWS=false elas não são criadas,
para bancos que não aceitam views; as mesmas análises estão em db/destino/consultas/acuracia.sql.
"""
from alembic import op

from ocr_requerimentos.config import config

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ocr.documento
          ADD COLUMN versao_pipeline  varchar(20),   -- pipeline.VERSAO_PIPELINE na última leitura
          ADD COLUMN config_extracao  jsonb;         -- motor, limiar e opções usadas na última leitura

        -- o que o OCR leu, preservado quando o revisor corrige valor_bruto/confianca
        ALTER TABLE ocr.campo_extraido
          ADD COLUMN valor_ocr      text,
          ADD COLUMN confianca_ocr  numeric(5,2),
          ADD CONSTRAINT ck_campo_confianca_ocr CHECK (confianca_ocr BETWEEN 0 AND 100);
        -- registros antigos: só os não corrigidos têm a leitura original conhecida
        UPDATE ocr.campo_extraido SET valor_ocr = valor_bruto, confianca_ocr = confianca
         WHERE NOT corrigido_manual;
    """)
    if not config().criar_views:
        return
    op.execute("""
        -- Base das duas views: campos de requerimentos validados (o revisor conferiu tudo), lidos por uma
        -- versão conhecida do pipeline. Campo vazio que ninguém preencheu fica de fora (nada a medir).
        CREATE VIEW ocr.vw_campo_conferido AS
        SELECT d.versao_pipeline, c.campo, c.indice, c.valor_ocr, c.confianca_ocr, c.corrigido_manual,
               (c.corrigido_manual AND c.valor_ocr IS NULL) AS nao_lido
          FROM ocr.campo_extraido c
          JOIN ocr.requerimento r ON r.id = c.requerimento_id
          JOIN ocr.documento d ON d.id = r.documento_id
         WHERE r.status_validacao = 'validado'
           AND d.versao_pipeline IS NOT NULL
           AND (c.valor_ocr IS NOT NULL OR c.corrigido_manual);

        -- quanto cada campo precisa de correção, por versão do pipeline
        CREATE VIEW ocr.vw_acuracia_campo AS
        SELECT versao_pipeline, campo,
               count(*)                                              AS conferidos,
               count(*) FILTER (WHERE corrigido_manual)              AS corrigidos,
               count(*) FILTER (WHERE nao_lido)                      AS nao_lidos,
               round(100.0 * count(*) FILTER (WHERE NOT corrigido_manual) / count(*), 1) AS pct_acerto,
               round(avg(confianca_ocr) FILTER (WHERE NOT corrigido_manual), 1)          AS confianca_media_acertos,
               round(avg(confianca_ocr) FILTER (WHERE corrigido_manual), 1)              AS confianca_media_corrigidos
          FROM ocr.vw_campo_conferido
         GROUP BY versao_pipeline, campo;

        -- a confiança informada bate com a realidade? (base para ajustar LIMIAR_CONFIANCA)
        CREATE VIEW ocr.vw_calibracao_confianca AS
        SELECT versao_pipeline,
               CASE WHEN confianca_ocr < 50 THEN '00-49'
                    WHEN confianca_ocr < 70 THEN '50-69'
                    WHEN confianca_ocr < 80 THEN '70-79'
                    WHEN confianca_ocr < 90 THEN '80-89'
                    ELSE '90-100' END                                AS faixa_confianca,
               count(*)                                              AS conferidos,
               count(*) FILTER (WHERE corrigido_manual)              AS corrigidos,
               round(100.0 * count(*) FILTER (WHERE NOT corrigido_manual) / count(*), 1) AS pct_acerto
          FROM ocr.vw_campo_conferido
         WHERE confianca_ocr IS NOT NULL
         GROUP BY 1, 2;
    """)


def downgrade() -> None:
    op.execute("""
        DROP VIEW IF EXISTS ocr.vw_calibracao_confianca;
        DROP VIEW IF EXISTS ocr.vw_acuracia_campo;
        DROP VIEW IF EXISTS ocr.vw_campo_conferido;
        ALTER TABLE ocr.campo_extraido DROP CONSTRAINT ck_campo_confianca_ocr,
          DROP COLUMN confianca_ocr, DROP COLUMN valor_ocr;
        ALTER TABLE ocr.documento DROP COLUMN config_extracao, DROP COLUMN versao_pipeline;
    """)
