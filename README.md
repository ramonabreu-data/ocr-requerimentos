# OCR de requerimentos do SIGA

Lê requerimentos de outorga ("Regularização de Poço Tubular" e afins) digitalizados — PDF do
sistema, PDF assinado, PDF de scanner, foto de celular ou imagem —, extrai os campos, confere
com o cadastro do SIGA e grava em PostgreSQL. Funciona com um arquivo de cada vez ou em lote
(vários arquivos, ZIP ou pasta do scanner). Uma tela de conferência mostra a folha ao lado do
formulário, com cada campo marcado no trecho de onde foi lido.

```
apps/web            Next.js (App Router): envio, lotes, fila de revisão e conferência
services/ocr        Python: API FastAPI, worker Celery, monitor de pasta, pipeline de OCR
  ocr_requerimentos/
    extracao/       parser por âncoras, normalizadores, validação, referências do SIGA
    imagem/         pré-processamento (OpenCV), Tesseract/PaddleOCR, QR code, assinatura
    pipeline/       leitura do arquivo, orquestração, gravação no banco, correções
  migrations/       schema "ocr" (Alembic + SQL)
  tests/            testes automatizados (ver docs/cenarios-de-teste.md)
db/dev              stub das tabelas do SIGA para desenvolvimento
db/destino          DDL consolidada do schema "ocr" para criar um banco novo (sem views)
docs                cenários de teste
```

## Como funciona

```
arquivo ──► texto do PDF? ──sim──► palavras com posição (sem OCR)
              │ não
              ▼
          perspectiva ► 300 dpi ► orientação 90/180° ► inclinação ► remove tinta azul ► Tesseract
              │
              ▼
   divide por página que começa com "REQUERIMENTO" (um PDF com vários vira vários documentos)
              │
              ▼
   parser por âncoras ("inscrito sob o CPF/CNPJ", "vem requerer … para …", "localizado no município",
   "latitude … e longitude", seções, tabela de irrigação, rodapé com nome e data)
              │
              ▼
   segunda leitura dos campos numéricos (CPF, coordenadas, áreas, data) ► normalização ► validação
   contra o SIGA (pessoa pelo CPF, município do PI, procedimento, intervenção, finalidade, ponto dentro
   do polígono do município) ► confiança por campo ► "Pronto para validar" ou "Em revisão"
```

Situações do documento: `recebido` (na fila), `processando`, `extraido` (pronto para validar),
`revisao`, `validado`, `erro`, `dividido` (arquivo com vários requerimentos; os filhos seguem o fluxo).
Validar com pendências exige justificativa, que fica no histórico. Enquanto o documento está sendo
lido, correção e validação ficam bloqueadas.

Ler de novo (`reprocessar`) não perde a revisão: depois da nova leitura, as correções manuais são
reaplicadas. Listas corrigidas (finalidades, irrigação, itens de uma finalidade) voltam inteiras como
o revisor deixou.

Escolhas que valem conhecer:

- PDF gerado pelo sistema ou assinado digitalmente não passa por OCR: o texto é lido direto, com
  100% de confiança. A assinatura digital é identificada (pyHanko) e a integridade verificada.
- PDF de scanner que traz uma camada de texto embutida é refeito pelo nosso OCR, porque o OCR dos
  scanners costuma ser pior (`CONFIAR_TEXTO_SCANNER=true` muda isso).
- O canal azul da imagem é usado no OCR: assinatura e carimbo em caneta azul somem e o texto preto
  por baixo continua legível. A detecção de assinatura à mão usa a imagem colorida original.
- O sinal negativo perdido pelo OCR nas coordenadas é recolocado (o Piauí está todo no Sul/Oeste),
  com aviso. Minutos ou segundos ≥ 60 invalidam o campo.
- CPF, coordenadas, áreas e data são relidos num recorte em tons de cinza. Leituras iguais elevam a
  confiança; diferentes mandam o campo para revisão mostrando as duas versões.

## Banco de dados

Tudo o que a ferramenta grava fica no schema `ocr` (migrations em `services/ocr/migrations`):

| Tabela | Guarda |
|---|---|
| `lote` | envio (upload, ZIP ou pasta do scanner) e contadores por situação |
| `lote_documento` | documentos de cada lote; o mesmo arquivo pode estar em vários lotes |
| `documento` | arquivo (`sha256` único), situação, assinatura, QR code, versão do pipeline e configuração da última leitura |
| `pagina` | texto e palavras do OCR com posição, por página |
| `requerimento` | dados extraídos: texto lido + id no SIGA, ponto (PostGIS, SIRGAS 2000), pendências, `versao` |
| `requerimento_finalidade` | finalidades, com os detalhes de cada uma em JSONB |
| `requerimento_irrigacao` | sistema, área e cultura de cada linha da tabela de irrigação |
| `dominio` | listas fechadas do formulário (culturas, sistemas de irrigação, espécies, ...) |
| `campo_extraido` | um registro por campo: valor lido e normalizado, confiança, página, caixa, se foi corrigido e o que o OCR leu originalmente |
| `revisao` | auditoria: cada correção, validação com pendências e releitura com correções reaplicadas |

Regras que o banco e a gravação garantem:

- O mesmo arquivo nunca é lido duas vezes. Reenviado em outro lote, entra nesse lote também (com as
  partes, se tiver sido dividido) e os contadores dos dois lotes são atualizados.
- O mesmo CPF/CNPJ pode ter vários requerimentos.
- Situações, tipos, faixas de confiança (0–100) e formato do CPF/CNPJ têm restrição `CHECK`; um campo
  não aparece duas vezes no mesmo requerimento.
- Duas pessoas revisando o mesmo documento: a tela envia `requerimento.versao` ao salvar e validar; se
  outra pessoa (ou uma releitura) gravou antes, a API responde 409 e pede para recarregar.
- As referências ao SIGA (`pessoa_id`, `municipio_id`, ...) não têm chave estrangeira: o schema `public`
  é só lido.

**Acurácia do OCR.** Cada campo guarda a leitura original (`valor_ocr`, `confianca_ocr`) mesmo depois de
corrigido, e cada documento guarda a versão do pipeline que o leu. Duas views usam isso, sempre sobre
requerimentos validados:

- `ocr.vw_acuracia_campo`: quanto cada campo é corrigido, por versão do pipeline;
- `ocr.vw_calibracao_confianca`: acerto por faixa de confiança, para ajustar `LIMIAR_CONFIANCA`.

Ao mudar algo que altere o resultado da extração (leitura, parser, normalizadores, validação), suba
`VERSAO_PIPELINE` em `services/ocr/ocr_requerimentos/pipeline/__init__.py` para comparar as versões.

**Banco de destino.** O banco onde o schema `ocr` é gravado vem do `.env`, nas variáveis `DESTINO_DB_HOST`,
`_PORTA`, `_NOME`, `_USUARIO`, `_SENHA` e `_SSLMODE`, que o `docker-compose.yml` repassa aos serviços
(`DATABASE_URL`, se definida, vale sobre elas). Para um banco que não aceita views, use
`CRIAR_VIEWS=false`: a migration 0006 pula as views, e as mesmas análises ficam em
`db/destino/consultas/acuracia.sql`, como consultas comuns. Para criar o schema sem rodar Python (pelo
DBA, por exemplo), use os arquivos de `db/destino`; o README de lá explica.

## Rodar em desenvolvimento

Requer Docker com Compose v2.

```bash
cp .env.example .env
make dev            # = docker compose up --build
```

- Tela: http://localhost:3000
- API e documentação interativa: http://localhost:8000/docs
- Console do MinIO: http://localhost:9001
- Pasta do scanner: `./entrada` (cada dia vira um lote "Pasta monitorada dd/mm/aaaa")

O `docker-compose.override.yml` sobe um PostGIS com `db/dev/00_siga_stub.sql`: só as tabelas do SIGA
que a ferramenta lê, com 36 municípios, procedimentos, intervenções, finalidades e a pessoa do PDF de
exemplo. Os polígonos de Altos e Teresina são retângulos fictícios.

Sem Docker: PostgreSQL 16 + PostGIS, Redis, Tesseract 5 com o idioma `por`, Python 3.12 e Node 22.

```bash
cd services/ocr && pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://ocr:ocr@localhost:5432/siga STORAGE_BACKEND=local STORAGE_DIR=/tmp/ocr
alembic upgrade head
uvicorn ocr_requerimentos.api.main:app --reload            # API
celery -A ocr_requerimentos.worker worker -Q ocr,padrao   # worker (ou CELERY_EAGER=true para dispensar Redis)
cd ../../apps/web && npm install && API_URL=http://localhost:8000 npm run dev
```

## Produção

```bash
make prod           # = docker compose -f docker-compose.yml up -d --build
make escalar N=4    # mais workers de OCR (cada um usa 1 núcleo por tarefa)
```

Banco: preencha as variáveis `DESTINO_DB_*` do `.env` (ou `DATABASE_URL`). A ferramenta **só lê** o
schema `public` (tabelas do SIGA, com `REFERENCIAS=siga`) e escreve apenas no schema `ocr`, criado pelas
migrations (controle de versão em `public.alembic_version_ocr`, separado da `django_migrations`). Em
desenvolvimento, o `docker-compose.override.yml` troca o banco pelo PostGIS local. Permissões sugeridas:

```sql
CREATE ROLE ocr_app LOGIN PASSWORD '...';
GRANT CREATE ON DATABASE siga TO ocr_app;           -- para criar o schema ocr na 1ª migration
GRANT USAGE ON SCHEMA public TO ocr_app;
GRANT SELECT ON core_estado, core_municipio, core_pessoa, core_pessoafisica, core_pessoajuridica,
  protocolo_procedimento, protocolo_processo, outorga_tipointervencao, outorga_tipofinalidadeuso TO ocr_app;
```

Confira o SRID das geometrias do SIGA (`SRID`, padrão 4674/SIRGAS 2000). A checagem do ponto dentro
do município transforma o ponto para o SRID de `core_municipio.geom` automaticamente.

## Pontos de integração pendentes

**Login.** A web é o único cliente da API: o proxy `apps/web/app/api/ocr/[...path]/route.ts` acrescenta
`X-API-Key` e `X-Usuario-Id`, e o navegador nunca vê a chave. Para usar o login do SIGA (Better Auth),
troque a função `usuarioAtual` pelo `auth.api.getSession(...)` da configuração que o SIGA já usa e
responda 401 sem sessão. Até lá, `DEV_USUARIO_ID` define o usuário gravado no histórico.

**Listas do formulário.** Sistemas de irrigação, culturas e as demais listas das finalidades não têm
tabela no SIGA, então ficam em `ocr.dominio`, semeadas a partir de
`services/ocr/ocr_requerimentos/dados_referencia.py` (copiadas do formulário público em 01/10/2026). Se
o formulário mudar, atualize esse arquivo e crie uma migration que regrave `ocr.dominio`.

**QR code no PDF (recomendado).** Se o gerador do PDF do requerimento incluir um QR com
`SIGA-REQ|v1|<uuid do processo>|<hash>`, o documento digitalizado fica ligado ao processo sem
depender do OCR. `ocr_requerimentos.imagem.qrcode.gerar_png(uuid, hash)` gera a imagem; imprima com
pelo menos 2 cm de lado.

**Enviar para o SIGA.** A ferramenta grava e valida os dados no schema `ocr`. Criar ou atualizar
registros do SIGA a partir dos validados (processo, ponto de interferência) é uma etapa separada,
de propósito, para passar pelas regras do próprio Django.

## API

| Método e rota | Faz |
|---|---|
| `POST /documentos` | envia um arquivo (201; 200 com `duplicado: true` se o mesmo arquivo já existe) |
| `POST /lotes` | envia vários arquivos e/ou ZIPs; informa duplicados (que passam a fazer parte do lote, sem nova leitura) e formatos não suportados |
| `GET /lotes`, `GET /lotes/{uuid}` | lista e detalhe com documentos e contadores |
| `POST /lotes/{uuid}/reprocessar-erros` | devolve à fila só os que deram erro |
| `GET /lotes/{uuid}/exportar?formato=csv\|xlsx` | planilha do lote (CSV com `;` e BOM para Excel) |
| `GET /documentos?status=&busca=` e `GET /revisao` | listas e fila de revisão; `busca` acha CPF/CNPJ com ou sem máscara |
| `GET /documentos?requerente=&procedimento=&municipio=&data_de=&data_ate=&campo_data=&pagina=&tamanho=` | filtros da lista de requerimentos, combinados com E: requerente sem diferenciar maiúsculas e acentos; período inclusivo pela data do documento (`campo_data=documento`, padrão) ou de gravação (`gravacao`, dia no fuso do Piauí) |
| `GET /filtros` | procedimentos e municípios presentes nos requerimentos gravados, com a quantidade de cada |
| `GET /documentos/{uuid}` | campos com valor lido, normalizado, confiança, página e caixa |
| `GET /documentos/{uuid}/arquivo`, `/paginas/{n}/imagem` | original e página corrigida |
| `PATCH /documentos/{uuid}/correcoes` | corrige campos, finalidades e tabela de irrigação; revalida e audita. Com `versao` (de `requerimento.versao`), 409 se outro gravou antes |
| `POST /documentos/{uuid}/validar` | valida (`forcar` + `justificativa` quando há pendências; `versao` como nas correções) |
| `POST /documentos/{uuid}/reprocessar` | lê de novo e reaplica as correções manuais (409 se já validado) |
| `GET /documentos/{uuid}/revisoes` | histórico de correções |
| `GET /referencias/{municipios\|procedimentos\|intervencoes\|finalidades\|sistemas\|culturas}` | listas para a tela |

## Testes

Os cenários estão em `docs/cenarios-de-teste.md`; cada teste automatizado leva o ID do cenário.

```bash
cd services/ocr
python -m pytest -q                                   # unitários + extração (precisa do Tesseract)
TEST_DATABASE_URL=postgresql+psycopg://ocr:ocr@localhost:5432/siga_test python -m pytest -q   # + integração
```

`TEST_DATABASE_URL` deve apontar para um banco **descartável**: ele é recriado a cada execução.
Os documentos de teste são o PDF real enviado e PDFs sintéticos no mesmo layout
(`tests/fabrica.py`), também degradados: rotação, ruído, JPEG ruim, papel amarelado, foto em
perspectiva, página de cabeça para baixo, assinatura em caneta azul, assinatura digital e QR code.

## Limitações conhecidas

- O parser segue o texto do modelo atual do requerimento. Se o texto do PDF mudar, ajuste as
  expressões em `extracao/parser.py` (os testes mostram rapidamente o que quebrou).
- Manuscrito não é lido: só o texto impresso. A assinatura à mão é detectada como presença de tinta.
- Os detalhes de cada finalidade são lidos conforme as definições em `extracao/finalidades.py`; um
  campo novo no formulário precisa ser descrito lá.
- Reprocessar um documento `dividido` não relê as partes já criadas.
- CPF/CNPJ lido com mais de 18 caracteres não cabe na coluna e o documento vai para `erro`.
- O motor PaddleOCR é opcional e não foi testado; o Tesseract é o padrão testado.
- O armazenamento S3/MinIO usa boto3 padrão; nos testes automatizados foi usado o armazenamento local.
