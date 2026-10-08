-- Marca o schema como já migrado até a 0006. Assim o serviço `migrar` (alembic upgrade head) do OCR,
-- apontado para este banco, não tenta criar o schema de novo (nem as views da 0006) e aplica só as
-- migrações futuras.
CREATE TABLE IF NOT EXISTS public.alembic_version_ocr (
  version_num varchar(32) NOT NULL,
  CONSTRAINT alembic_version_ocr_pkc PRIMARY KEY (version_num)
);
DELETE FROM public.alembic_version_ocr;
INSERT INTO public.alembic_version_ocr (version_num) VALUES ('0006');
