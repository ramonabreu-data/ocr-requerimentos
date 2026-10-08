-- Consultas de acurácia do OCR. Só leitura: não criam nenhum objeto no banco.
-- Mesmo resultado das views ocr.vw_acuracia_campo e ocr.vw_calibracao_confianca do banco principal.
--
-- Base das duas: campos de requerimentos validados (o revisor conferiu tudo), lidos por uma versão
-- conhecida do pipeline. Campo vazio que ninguém preencheu fica de fora (nada a medir).

-- 1. Quanto cada campo precisa de correção, por versão do pipeline
WITH conferido AS (
  SELECT d.versao_pipeline, c.campo, c.confianca_ocr, c.corrigido_manual,
         (c.corrigido_manual AND c.valor_ocr IS NULL) AS nao_lido
    FROM ocr.campo_extraido c
    JOIN ocr.requerimento r ON r.id = c.requerimento_id
    JOIN ocr.documento d ON d.id = r.documento_id
   WHERE r.status_validacao = 'validado'
     AND d.versao_pipeline IS NOT NULL
     AND (c.valor_ocr IS NOT NULL OR c.corrigido_manual)
)
SELECT versao_pipeline, campo,
       count(*)                                              AS conferidos,
       count(*) FILTER (WHERE corrigido_manual)              AS corrigidos,
       count(*) FILTER (WHERE nao_lido)                      AS nao_lidos,
       round(100.0 * count(*) FILTER (WHERE NOT corrigido_manual) / count(*), 1) AS pct_acerto,
       round(avg(confianca_ocr) FILTER (WHERE NOT corrigido_manual), 1)          AS confianca_media_acertos,
       round(avg(confianca_ocr) FILTER (WHERE corrigido_manual), 1)              AS confianca_media_corrigidos
  FROM conferido
 GROUP BY versao_pipeline, campo
 ORDER BY versao_pipeline, pct_acerto, campo;

-- 2. A confiança informada bate com a realidade? (base para ajustar LIMIAR_CONFIANCA)
WITH conferido AS (
  SELECT d.versao_pipeline, c.confianca_ocr, c.corrigido_manual
    FROM ocr.campo_extraido c
    JOIN ocr.requerimento r ON r.id = c.requerimento_id
    JOIN ocr.documento d ON d.id = r.documento_id
   WHERE r.status_validacao = 'validado'
     AND d.versao_pipeline IS NOT NULL
     AND c.confianca_ocr IS NOT NULL
)
SELECT versao_pipeline,
       CASE WHEN confianca_ocr < 50 THEN '00-49'
            WHEN confianca_ocr < 70 THEN '50-69'
            WHEN confianca_ocr < 80 THEN '70-79'
            WHEN confianca_ocr < 90 THEN '80-89'
            ELSE '90-100' END                                AS faixa_confianca,
       count(*)                                              AS conferidos,
       count(*) FILTER (WHERE corrigido_manual)              AS corrigidos,
       round(100.0 * count(*) FILTER (WHERE NOT corrigido_manual) / count(*), 1) AS pct_acerto
  FROM conferido
 GROUP BY 1, 2
 ORDER BY 1, 2;
