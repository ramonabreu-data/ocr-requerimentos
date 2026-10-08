-- ============================================================================
-- OCR de requerimentos: schema `ocr` para um banco de destino (PostgreSQL 13+ com PostGIS).
-- Equivale às migrações 0001 a 0006 de services/ocr/migrations, sem as views (o destino não as aceita;
-- as mesmas análises estão em consultas/acuracia.sql). Rode os arquivos em ordem.
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS postgis;   -- requerimento.geom (Point, SIRGAS 2000)
CREATE SCHEMA IF NOT EXISTS ocr;
