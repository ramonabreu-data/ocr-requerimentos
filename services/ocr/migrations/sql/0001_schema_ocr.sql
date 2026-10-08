-- Schema próprio da ferramenta de OCR. Não altera nenhuma tabela do SIGA (schema public).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS ocr;

CREATE TABLE ocr.lote (
  id             bigserial PRIMARY KEY,
  uuid           uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  nome           varchar(200),
  origem         varchar(20) NOT NULL,              -- upload | zip | pasta_monitorada
  status         varchar(20) NOT NULL DEFAULT 'pendente',
  total          integer NOT NULL DEFAULT 0,
  processados    integer NOT NULL DEFAULT 0,
  em_revisao     integer NOT NULL DEFAULT 0,
  validados      integer NOT NULL DEFAULT 0,
  com_erro       integer NOT NULL DEFAULT 0,
  criado_por_id  integer,                           -- public.accounts_user
  created_at     timestamptz NOT NULL DEFAULT now(),
  finalizado_em  timestamptz
);

CREATE TABLE ocr.documento (
  id                   bigserial PRIMARY KEY,
  uuid                 uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  lote_id              bigint REFERENCES ocr.lote(id) ON DELETE SET NULL,
  documento_pai_id     bigint REFERENCES ocr.documento(id) ON DELETE CASCADE,
  nome_original        varchar(255) NOT NULL,
  storage_key          text NOT NULL,
  content_type         varchar(100) NOT NULL,
  tamanho_bytes        bigint NOT NULL,
  sha256               char(64) NOT NULL UNIQUE,
  tipo_entrada         varchar(20),                 -- pdf_texto | pdf_imagem | imagem
  metodo_extracao      varchar(20),                 -- texto_nativo | ocr | qrcode+...
  paginas              smallint,
  pagina_inicial       smallint,
  assinatura_tipo      varchar(20),                 -- digital | manuscrita | ausente | indeterminada
  assinatura_detalhes  jsonb,
  qr_conteudo          text,
  processo_uuid        uuid,
  processo_id          bigint,                      -- public.protocolo_processo
  status               varchar(20) NOT NULL DEFAULT 'recebido',
  erro                 text,
  tentativas           smallint NOT NULL DEFAULT 0,
  duracao_ms           integer,
  criado_por_id        integer,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_documento_lote ON ocr.documento(lote_id);
CREATE INDEX ix_documento_status ON ocr.documento(status);

CREATE TABLE ocr.pagina (
  id               bigserial PRIMARY KEY,
  documento_id     bigint NOT NULL REFERENCES ocr.documento(id) ON DELETE CASCADE,
  numero           smallint NOT NULL,
  largura          integer,
  altura           integer,
  imagem_key       text,
  angulo_correcao  numeric(6,2),
  metodo           varchar(20),
  motor_ocr        varchar(20),
  texto_bruto      text,
  ocr_json         jsonb,                           -- [{t: texto, c: confiança, b: [x0,y0,x1,y1], p: página}]
  confianca_media  numeric(5,2),
  UNIQUE (documento_id, numero)
);

CREATE TABLE ocr.dominio (
  id         bigserial PRIMARY KEY,
  tipo       varchar(30) NOT NULL,                  -- sistema_irrigacao | cultura
  valor      varchar(150) NOT NULL,
  sinonimos  text[] NOT NULL DEFAULT '{}',
  ativo      boolean NOT NULL DEFAULT true,
  UNIQUE (tipo, valor)
);

CREATE TABLE ocr.requerimento (
  id                      bigserial PRIMARY KEY,
  documento_id            bigint NOT NULL UNIQUE REFERENCES ocr.documento(id) ON DELETE CASCADE,
  requerente_nome         varchar(255),
  cpf_cnpj                varchar(18),
  tipo_pessoa             char(1),
  pessoa_id               bigint,                   -- public.core_pessoa
  procedimento_texto      varchar(200),
  procedimento_id         bigint,                   -- public.protocolo_procedimento
  tipo_intervencao_texto  varchar(250),
  tipo_intervencao_id     bigint,                   -- public.outorga_tipointervencao
  municipio_texto         varchar(255),
  municipio_id            bigint,                   -- public.core_municipio
  localidade              varchar(100),
  latitude_texto          varchar(40),
  longitude_texto         varchar(40),
  latitude                numeric(10,7),
  longitude               numeric(10,7),
  geom                    geometry(Point, 4674),
  descricao_usos          text,
  assinante_nome          varchar(255),
  data_documento          date,
  confianca_geral         numeric(5,2),
  pendencias              jsonb,
  avisos                  jsonb,
  status_validacao        varchar(20) NOT NULL DEFAULT 'pendente',
  validado_por_id         integer,
  validado_em             timestamptz,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_requerimento_cpf ON ocr.requerimento(cpf_cnpj);
CREATE INDEX ix_requerimento_geom ON ocr.requerimento USING gist(geom);

CREATE TABLE ocr.requerimento_finalidade (
  id                  bigserial PRIMARY KEY,
  requerimento_id     bigint NOT NULL REFERENCES ocr.requerimento(id) ON DELETE CASCADE,
  finalidade_texto    varchar(250),
  tipo_finalidade_id  bigint,                       -- public.outorga_tipofinalidadeuso
  confianca           numeric(5,2),
  valido              boolean NOT NULL DEFAULT false
);

CREATE TABLE ocr.requerimento_irrigacao (
  id               bigserial PRIMARY KEY,
  requerimento_id  bigint NOT NULL REFERENCES ocr.requerimento(id) ON DELETE CASCADE,
  ordem            smallint NOT NULL,
  sistema_texto    varchar(150),
  sistema_id       bigint REFERENCES ocr.dominio(id),
  area_ha          numeric(12,4),
  cultura_texto    varchar(150),
  cultura_id       bigint REFERENCES ocr.dominio(id),
  confianca        numeric(5,2),
  valido           boolean NOT NULL DEFAULT false
);

CREATE TABLE ocr.campo_extraido (
  id                 bigserial PRIMARY KEY,
  requerimento_id    bigint NOT NULL REFERENCES ocr.requerimento(id) ON DELETE CASCADE,
  campo              varchar(60) NOT NULL,
  indice             smallint,
  valor_bruto        text,
  valor_normalizado  text,
  confianca          numeric(5,2),
  pagina             smallint,
  bbox               jsonb,
  valido             boolean,
  obrigatorio        boolean NOT NULL DEFAULT false,
  corrigido_manual   boolean NOT NULL DEFAULT false,
  mensagem           text
);
CREATE INDEX ix_campo_req ON ocr.campo_extraido(requerimento_id);

CREATE TABLE ocr.revisao (
  id               bigserial PRIMARY KEY,
  requerimento_id  bigint NOT NULL REFERENCES ocr.requerimento(id) ON DELETE CASCADE,
  campo            varchar(60) NOT NULL,
  valor_anterior   text,
  valor_novo       text,
  usuario_id       integer,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_revisao_req ON ocr.revisao(requerimento_id);
