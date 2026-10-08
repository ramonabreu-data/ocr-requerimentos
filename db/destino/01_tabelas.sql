-- Tabelas do schema ocr, com chaves, restrições e índices.
-- As colunas *_id que apontam para o SIGA (pessoa, município, procedimento, processo, usuário) não têm
-- chave estrangeira: no banco de destino são só números de referência.

-- ---------------------------------------------------------------- entrada e controle
CREATE TABLE ocr.lote (
  id             bigserial PRIMARY KEY,
  uuid           uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  nome           varchar(200),
  origem         varchar(20) NOT NULL,
  status         varchar(20) NOT NULL DEFAULT 'pendente',
  total          integer NOT NULL DEFAULT 0,
  processados    integer NOT NULL DEFAULT 0,
  em_revisao     integer NOT NULL DEFAULT 0,
  validados      integer NOT NULL DEFAULT 0,
  com_erro       integer NOT NULL DEFAULT 0,
  criado_por_id  integer,                           -- SIGA: accounts_user
  created_at     timestamptz NOT NULL DEFAULT now(),
  finalizado_em  timestamptz,
  CONSTRAINT ck_lote_origem CHECK (origem IN ('upload', 'zip', 'pasta_monitorada')),
  CONSTRAINT ck_lote_status CHECK (status IN ('pendente', 'processando', 'concluido', 'concluido_com_erros'))
);

CREATE TABLE ocr.documento (
  id                   bigserial PRIMARY KEY,
  uuid                 uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  lote_id              bigint REFERENCES ocr.lote(id) ON DELETE SET NULL,   -- lote em que entrou primeiro
  documento_pai_id     bigint REFERENCES ocr.documento(id) ON DELETE CASCADE, -- parte de um PDF dividido
  nome_original        varchar(255) NOT NULL,
  storage_key          text NOT NULL,               -- caminho do arquivo no armazenamento (S3/MinIO)
  content_type         varchar(100) NOT NULL,
  tamanho_bytes        bigint NOT NULL,
  sha256               char(64) NOT NULL UNIQUE,
  tipo_entrada         varchar(20),
  metodo_extracao      varchar(20),
  paginas              smallint,
  pagina_inicial       smallint,
  assinatura_tipo      varchar(20),
  assinatura_detalhes  jsonb,
  qr_conteudo          text,
  processo_uuid        uuid,
  processo_id          bigint,                      -- SIGA: protocolo_processo
  status               varchar(20) NOT NULL DEFAULT 'recebido',
  erro                 text,
  tentativas           smallint NOT NULL DEFAULT 0,
  duracao_ms           integer,
  criado_por_id        integer,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  versao_pipeline      varchar(20),                 -- versão do pipeline na última leitura
  config_extracao      jsonb,                       -- motor, limiar e opções da última leitura
  CONSTRAINT ck_documento_status CHECK (status IN
    ('recebido', 'processando', 'extraido', 'revisao', 'validado', 'erro', 'dividido')),
  CONSTRAINT ck_documento_tipo_entrada CHECK (tipo_entrada IN ('pdf_texto', 'pdf_imagem', 'imagem')),
  CONSTRAINT ck_documento_metodo_extracao CHECK (metodo_extracao IN
    ('texto_nativo', 'ocr', 'qrcode+texto_nativo', 'qrcode+ocr')),
  CONSTRAINT ck_documento_assinatura_tipo CHECK (assinatura_tipo IN
    ('digital', 'manuscrita', 'ausente', 'indeterminada')),
  CONSTRAINT ck_documento_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_documento_tamanho CHECK (tamanho_bytes >= 0),
  CONSTRAINT ck_documento_tentativas CHECK (tentativas >= 0)
);
CREATE INDEX ix_documento_lote ON ocr.documento(lote_id);
CREATE INDEX ix_documento_status ON ocr.documento(status);

-- um mesmo arquivo pode fazer parte de vários lotes
CREATE TABLE ocr.lote_documento (
  lote_id       bigint NOT NULL REFERENCES ocr.lote(id) ON DELETE CASCADE,
  documento_id  bigint NOT NULL REFERENCES ocr.documento(id) ON DELETE CASCADE,
  nome_arquivo  varchar(255),                       -- nome com que o arquivo veio neste lote
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (lote_id, documento_id)
);
CREATE INDEX ix_lote_documento_documento ON ocr.lote_documento(documento_id);

-- ---------------------------------------------------------------- leitura bruta
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
  UNIQUE (documento_id, numero),
  CONSTRAINT ck_pagina_metodo CHECK (metodo IN ('texto_nativo', 'ocr')),
  CONSTRAINT ck_pagina_confianca CHECK (confianca_media BETWEEN 0 AND 100)
);

-- ---------------------------------------------------------------- listas do formulário
CREATE TABLE ocr.dominio (
  id         bigserial PRIMARY KEY,
  tipo       varchar(30) NOT NULL,                  -- sistema_irrigacao | cultura | especie_animal | ...
  valor      varchar(150) NOT NULL,
  sinonimos  text[] NOT NULL DEFAULT '{}',
  ativo      boolean NOT NULL DEFAULT true,
  UNIQUE (tipo, valor)
);

-- ---------------------------------------------------------------- dados do requerimento
CREATE TABLE ocr.requerimento (
  id                      bigserial PRIMARY KEY,
  documento_id            bigint NOT NULL UNIQUE REFERENCES ocr.documento(id) ON DELETE CASCADE,
  requerente_nome         varchar(255),
  cpf_cnpj                varchar(18),              -- o mesmo CPF/CNPJ pode ter vários requerimentos
  tipo_pessoa             char(1),
  pessoa_id               bigint,                   -- SIGA: core_pessoa
  procedimento_texto      varchar(200),
  procedimento_id         bigint,                   -- SIGA: protocolo_procedimento
  tipo_intervencao_texto  varchar(250),
  tipo_intervencao_id     bigint,                   -- SIGA: outorga_tipointervencao
  municipio_texto         varchar(255),
  municipio_id            bigint,                   -- SIGA: core_municipio
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
  updated_at              timestamptz NOT NULL DEFAULT now(),
  versao                  integer NOT NULL DEFAULT 1, -- sobe a cada gravação (trava otimista da revisão)
  CONSTRAINT ck_requerimento_status_validacao CHECK (status_validacao IN ('pendente', 'validado')),
  CONSTRAINT ck_requerimento_tipo_pessoa CHECK (tipo_pessoa IN ('F', 'J')),
  CONSTRAINT ck_requerimento_cpf_cnpj CHECK (cpf_cnpj ~ '^[0-9./-]*$'),
  CONSTRAINT ck_requerimento_confianca CHECK (confianca_geral BETWEEN 0 AND 100),
  CONSTRAINT ck_requerimento_validado CHECK (status_validacao <> 'validado' OR validado_em IS NOT NULL),
  CONSTRAINT ck_requerimento_versao CHECK (versao >= 1)
);
CREATE INDEX ix_requerimento_cpf ON ocr.requerimento(cpf_cnpj);
CREATE INDEX ix_requerimento_geom ON ocr.requerimento USING gist(geom);

CREATE TABLE ocr.requerimento_finalidade (
  id                  bigserial PRIMARY KEY,
  requerimento_id     bigint NOT NULL REFERENCES ocr.requerimento(id) ON DELETE CASCADE,
  finalidade_texto    varchar(250),
  tipo_finalidade_id  bigint,                       -- SIGA: outorga_tipofinalidadeuso
  confianca           numeric(5,2),
  valido              boolean NOT NULL DEFAULT false,
  chave               varchar(40),                  -- ex.: criacao_animal
  detalhes            jsonb,                        -- dados próprios da finalidade, normalizados
  CONSTRAINT ck_finalidade_confianca CHECK (confianca BETWEEN 0 AND 100)
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
  valido           boolean NOT NULL DEFAULT false,
  CONSTRAINT ck_irrigacao_confianca CHECK (confianca BETWEEN 0 AND 100),
  CONSTRAINT ck_irrigacao_area CHECK (area_ha >= 0),
  CONSTRAINT ck_irrigacao_ordem CHECK (ordem >= 1)
);
CREATE UNIQUE INDEX ux_irrigacao_ordem ON ocr.requerimento_irrigacao (requerimento_id, ordem);

-- ---------------------------------------------------------------- rastreabilidade e auditoria
-- um registro por campo lido: valor bruto, normalizado, confiança e posição na página
CREATE TABLE ocr.campo_extraido (
  id                 bigserial PRIMARY KEY,
  requerimento_id    bigint NOT NULL REFERENCES ocr.requerimento(id) ON DELETE CASCADE,
  campo              varchar(60) NOT NULL,
  indice             smallint,                      -- posição em listas (finalidade/irrigação/itens)
  valor_bruto        text,
  valor_normalizado  text,
  confianca          numeric(5,2),
  pagina             smallint,
  bbox               jsonb,                         -- [x0, y0, x1, y1]
  valido             boolean,
  obrigatorio        boolean NOT NULL DEFAULT false,
  corrigido_manual   boolean NOT NULL DEFAULT false,
  mensagem           text,
  valor_ocr          text,                          -- leitura original, mantida após correção
  confianca_ocr      numeric(5,2),
  CONSTRAINT ck_campo_confianca CHECK (confianca BETWEEN 0 AND 100),
  CONSTRAINT ck_campo_confianca_ocr CHECK (confianca_ocr BETWEEN 0 AND 100)
);
CREATE INDEX ix_campo_req ON ocr.campo_extraido(requerimento_id);
CREATE UNIQUE INDEX ux_campo_extraido_chave ON ocr.campo_extraido (requerimento_id, campo, COALESCE(indice, -1));

-- uma linha por alteração manual (e por validação com pendências / releitura)
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
