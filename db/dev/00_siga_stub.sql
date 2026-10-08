-- ============================================================================
-- STUB do SIGA para DESENVOLVIMENTO. Cria só as tabelas/colunas do schema public que a
-- ferramenta de OCR LÊ, com dados de exemplo. Em produção, aponte DATABASE_URL para o banco
-- real do SIGA e NÃO rode este arquivo.
-- Polígonos dos municípios são retângulos fictícios, apenas para testar ST_Intersects.
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS public.core_estado (
  id bigserial PRIMARY KEY, uuid uuid NOT NULL DEFAULT gen_random_uuid(),
  nome varchar(25) NOT NULL, uf varchar(2) NOT NULL, codigo_ibge integer, geom geometry
);
CREATE TABLE IF NOT EXISTS public.core_municipio (
  id bigserial PRIMARY KEY, uuid uuid NOT NULL DEFAULT gen_random_uuid(),
  codigo_ibge integer NOT NULL DEFAULT 0, nome varchar(255) NOT NULL, geom geometry,
  estado_id bigint NOT NULL REFERENCES public.core_estado(id)
);
CREATE TABLE IF NOT EXISTS public.core_pessoa (
  id bigserial PRIMARY KEY, uuid uuid NOT NULL DEFAULT gen_random_uuid(),
  nome varchar(255) NOT NULL, tipo_cadastro_pessoa varchar(1) NOT NULL DEFAULT 'F'
);
CREATE TABLE IF NOT EXISTS public.core_pessoafisica (
  pessoa_ptr_id bigint PRIMARY KEY REFERENCES public.core_pessoa(id), cpf varchar(14) NOT NULL
);
CREATE TABLE IF NOT EXISTS public.core_pessoajuridica (
  pessoa_ptr_id bigint PRIMARY KEY REFERENCES public.core_pessoa(id), cnpj varchar(18) NOT NULL,
  razao_social varchar(255) NOT NULL
);
CREATE TABLE IF NOT EXISTS public.protocolo_procedimento (
  id bigserial PRIMARY KEY, uuid uuid NOT NULL DEFAULT gen_random_uuid(),
  nome varchar(100) NOT NULL, sigla varchar(8) NOT NULL DEFAULT '', ativo boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS public.protocolo_processo (
  id bigserial PRIMARY KEY, uuid uuid NOT NULL DEFAULT gen_random_uuid(),
  numero_processo varchar(200) NOT NULL, procedimento_id bigint REFERENCES public.protocolo_procedimento(id)
);
CREATE TABLE IF NOT EXISTS public.outorga_tipointervencao (
  id bigserial PRIMARY KEY, uuid uuid NOT NULL DEFAULT gen_random_uuid(),
  nome varchar(250) NOT NULL, categoria varchar(5) NOT NULL DEFAULT '', ativo boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS public.outorga_tipofinalidadeuso (
  id bigserial PRIMARY KEY, uuid uuid NOT NULL DEFAULT gen_random_uuid(),
  nome varchar(250) NOT NULL, categoria varchar(5) NOT NULL DEFAULT '', ativo boolean NOT NULL DEFAULT true
);

INSERT INTO public.core_estado (nome, uf, codigo_ibge) VALUES ('Piauí', 'PI', 22), ('Maranhão', 'MA', 21);

INSERT INTO public.core_municipio (nome, estado_id, geom) VALUES
 ('Altos', 1, ST_MakeEnvelope(-42.75, -5.25, -42.25, -4.85, 4674)),
 ('Teresina', 1, ST_MakeEnvelope(-42.99, -5.40, -42.76, -4.85, 4674)),
 ('Parnaíba', 1, NULL), ('Picos', 1, NULL), ('Piripiri', 1, NULL), ('Floriano', 1, NULL),
 ('Campo Maior', 1, NULL), ('Barras', 1, NULL), ('União', 1, NULL), ('José de Freitas', 1, NULL),
 ('Esperantina', 1, NULL), ('Pedro II', 1, NULL), ('Oeiras', 1, NULL), ('São Raimundo Nonato', 1, NULL),
 ('Corrente', 1, NULL), ('Bom Jesus', 1, NULL), ('Uruçuí', 1, NULL), ('Valença do Piauí', 1, NULL),
 ('Piracuruca', 1, NULL), ('Luís Correia', 1, NULL), ('Miguel Alves', 1, NULL), ('Alto Longá', 1, NULL),
 ('Demerval Lobão', 1, NULL), ('Nazária', 1, NULL), ('Beneditinos', 1, NULL), ('Coivaras', 1, NULL),
 ('Pau D''Arco do Piauí', 1, NULL), ('Lagoa Alegre', 1, NULL), ('Monsenhor Gil', 1, NULL),
 ('Água Branca', 1, NULL), ('Amarante', 1, NULL), ('Cocal', 1, NULL), ('Batalha', 1, NULL),
 ('Castelo do Piauí', 1, NULL), ('Regeneração', 1, NULL),
 ('Timon', 2, NULL);

INSERT INTO public.core_pessoa (nome) VALUES ('Ramon Teste'), ('Maria das Graças Sousa');
INSERT INTO public.core_pessoafisica (pessoa_ptr_id, cpf) VALUES (1, '059.749.653-61');

INSERT INTO public.protocolo_procedimento (nome, sigla) VALUES
 ('Regularização de Poço Tubular', 'RPT'), ('Outorga de Direito de Uso', 'ODU'),
 ('Outorga Preventiva', 'OP'), ('Dispensa de Outorga', 'DO'), ('Autorização de Perfuração de Poço', 'APP');
INSERT INTO public.protocolo_processo (numero_processo, procedimento_id, uuid)
 VALUES ('2026.0001.000123', 1, '6f1c2a3e-9b7d-4c1e-8f2a-1b2c3d4e5f60');

INSERT INTO public.outorga_tipointervencao (nome) VALUES
 ('Poço Tubular'), ('Poço Amazonas'), ('Captação Superficial'), ('Barramento'), ('Lançamento de Efluentes');
INSERT INTO public.outorga_tipofinalidadeuso (nome) VALUES
 ('Irrigação'), ('Abastecimento Humano'), ('Dessedentação Animal'), ('Aquicultura'),
 ('Indústria'), ('Mineração'), ('Consumo Humano'), ('Lazer e Turismo');
