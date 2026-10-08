# OCR de requerimentos do SIGA

Lê requerimentos de outorga ("Regularização de Poço Tubular" e afins) digitalizados — PDF do
sistema, PDF assinado, PDF de scanner, foto de celular ou imagem —, extrai os campos, confere
com o cadastro do SIGA e grava cada requerimento num arquivo JSON, no bucket (S3/MinIO). Funciona com
um arquivo de cada vez ou em lote
(vários arquivos, ZIP ou pasta do scanner). Uma tela de conferência mostra a folha ao lado do
formulário, com cada campo marcado no trecho de onde foi lido.

```
apps/web            Next.js (App Router): envio, lotes, fila de revisão e conferência
services/ocr        Python: API FastAPI, worker Celery, monitor de pasta, pipeline de OCR
  ocr_requerimentos/
    extracao/       parser por âncoras, normalizadores, validação, referências do SIGA
    imagem/         pré-processamento (OpenCV), Tesseract/PaddleOCR, QR code, assinatura
    pipeline/       leitura do arquivo, orquestração, gravação do resultado, correções
    modelos.py      contrato dos arquivos JSON (fonte da verdade)
    repositorio.py  JSON no bucket + índice, travas e contadores no Redis
    ferramentas.py  reconstruir índice, relatório de acurácia, JSON Schema, carga sintética
  tests/            testes automatizados (ver docs/cenarios-de-teste.md)
db/dev              stub das tabelas do SIGA para desenvolvimento
docs                cenários de teste e JSON Schema dos arquivos (docs/contrato-json)
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

## Onde os dados ficam

Não há banco de dados da ferramenta. Tudo o que ela produz fica em **arquivos JSON no bucket**, ao lado
dos arquivos originais; o Redis guarda a fila e um **índice derivado** desses JSONs.

```
                 ┌──────────── bucket (MinIO/S3) = fonte da verdade ─────────────┐
upload/pasta ──► │ documentos/{uuid}/original.pdf, paginas/{n}.jpg               │
                 │ dados/documentos/{uuid}.json   um requerimento, completo      │
   worker ─────► │ dados/paginas/{uuid}.json      texto e palavras do OCR        │
                 │ dados/lotes/{uuid}.json        lote (envio)                   │
                 └───────────────────────────────────────────────────────────────┘
                 ┌──────────── Redis = fila + índice (reconstruível) ────────────┐
   API ────────► │ travas por documento · SHA-256 → documento · contadores       │
                 │ por lote · conjuntos para fila, filtros e paginação           │
                 └───────────────────────────────────────────────────────────────┘
                 Banco do SIGA: só leitura (CPF, municípios e polígonos, listas)
```

**O JSON de um requerimento** (`dados/documentos/{uuid}.json`) traz o documento (arquivo, SHA-256,
situação, assinatura, QR code, versão do pipeline e configuração da leitura, lotes), os dados extraídos
e, para cada campo, o que é cada coisa com nome explícito:

```json
{
  "campo": "latitude",
  "valor_atual": "-5°02'41.06\"",
  "valor_atual_normalizado": "-5.0447389",
  "confianca_atual": 100.0,
  "corrigido_manualmente": true,
  "leitura_original_ocr": { "valor_lido": "-5°02'91.06\"", "confianca_ocr": 100.0 },
  "local_na_folha": { "pagina": 1, "caixa": [1556.7, 447.6, 1799.6, 508.9] },
  "validacao": { "valido": true, "obrigatorio": true, "mensagem": null }
}
```

- `valor_atual`/`confianca_atual`: o valor que vale agora (lido pelo OCR ou digitado na revisão).
- `leitura_original_ocr`: o que o OCR leu na última leitura, **nunca alterado pela revisão**; nulo quando
  o campo não foi lido e foi incluído na revisão.
- `historico_de_revisoes`: cada correção (`campo`, `valor_anterior`, `valor_novo`, `usuario_id`, `em`),
  validação com pendências (com a justificativa) e releitura com correções reaplicadas.

O formato completo, com a descrição de cada campo, está em `docs/contrato-json/*.schema.json` (gerado
de `services/ocr/ocr_requerimentos/modelos.py` com `python -m ocr_requerimentos.ferramentas json-schema`).
`GET /documentos/{uuid}/json` devolve o arquivo como está gravado.

Regras que a gravação garante (antes eram restrições do banco):

- **Contrato**: todo JSON passa pelos modelos antes de ir ao bucket. Situação, tipos, confiança (0–100),
  formato do CPF/CNPJ, validado com data e campo sem repetição: o que violar não é gravado (a API
  responde 422).
- **Concorrência**: quem altera um documento segura uma trava no Redis, relê o JSON, altera e grava. A
  tela envia `requerimento.versao` ao salvar e validar; se outra pessoa (ou uma releitura) gravou antes, a
  API responde 409 e pede para recarregar. O OCR roda fora da trava.
- **Sem leitura repetida**: o mesmo arquivo (SHA-256) vira um documento só, mesmo enviado várias vezes ao
  mesmo tempo. Reenviado em outro lote, entra nesse lote também (com as partes, se foi dividido).
- **Histórico de versões**: o compose liga o versionamento do bucket, então cada regravação de um JSON
  guarda a versão anterior (backup e trilha de auditoria sem custo de código).
- As referências ao SIGA (`pessoa_id`, `municipio_id`, ...) são ids do SIGA, lido só para consulta.
- O mesmo CPF/CNPJ pode ter vários requerimentos.

**Índice no Redis.** Guarda um resumo de cada documento e conjuntos ordenados por data (geral, por
situação, lote, procedimento e município), os contadores de cada lote e o mapa SHA-256 → documento. A
lista, a fila de revisão, os filtros e a paginação saem dele sem abrir os JSONs. É derivado: se o Redis
se perder, `make reconstruir-indice` refaz tudo lendo o bucket. O Redis do compose grava em disco (AOF)
e usa `noeviction`, para nunca descartar chaves do índice por falta de memória.

**Acurácia do OCR.** Cada campo guarda a leitura original mesmo depois de corrigido, e cada documento a
versão do pipeline que o leu. `make acuracia` (ou `python -m ocr_requerimentos.ferramentas acuracia
--saida PASTA`) gera, sobre os requerimentos validados:

- `acuracia_campo.csv`: quanto cada campo é corrigido, por versão do pipeline;
- `calibracao_confianca.csv`: acerto por faixa de confiança, para ajustar `LIMIAR_CONFIANCA`.

Ao mudar algo que altere o resultado da extração (leitura, parser, normalizadores, validação), suba
`VERSAO_PIPELINE` em `services/ocr/ocr_requerimentos/pipeline/__init__.py` para comparar as versões.
Para análises livres, o DuckDB lê os JSONs direto do bucket:

```sql
-- duckdb: INSTALL httpfs; LOAD httpfs; (configure o endpoint/credenciais do S3/MinIO)
SELECT c.campo, count(*) AS conferidos, count(*) FILTER (WHERE c.corrigido_manualmente) AS corrigidos
FROM (SELECT unnest(requerimento.campos) AS c
      FROM read_json_auto('s3://ocr-requerimentos/dados/documentos/*.json')
      WHERE requerimento.validacao.situacao = 'validado')
GROUP BY 1 ORDER BY corrigidos DESC;
```

**Volume.** Medido com `ferramentas carga-sintetica` em MinIO e Redis reais, numa máquina de
desenvolvimento, com 100 mil documentos:

| Operação | Tempo |
|---|---|
| gravação (JSON no bucket + índice, com trava) | 122 documentos/s (32 em paralelo) |
| lista, fila de revisão, filtro por situação, município, procedimento ou período de gravação | 2–13 ms |
| contadores de um lote | < 1 ms |
| busca por trecho do nome, do arquivo ou do CPF (varre os candidatos) | ~1,4 s |
| reconstruir o índice a partir do bucket | ~180 documentos/s (20 mil em 110 s) |
| memória do Redis | ~2 KB por documento (193 MB com 100 mil; ~2 GB com 1 milhão) |

A gravação não é o gargalo: o OCR leva segundos por documento (escale com `make escalar N=...`). A busca
por trecho de texto cresce linearmente com o número de candidatos (~14 µs por documento, ~14 s com 1
milhão); combinada com situação, município, procedimento ou período, ela só varre o que sobrou desses
filtros. Para busca livre rápida acima de algumas centenas de milhares de requerimentos, o próximo passo é
um índice de texto (Redis 8 com o Query Engine ou OpenSearch) alimentado pelos mesmos JSONs.

**Banco do SIGA.** Lido das variáveis `SIGA_DB_HOST`, `_PORTA`, `_NOME`, `_USUARIO`, `_SENHA` e
`_SSLMODE` do `.env` (`SIGA_DATABASE_URL`, se definida, vale sobre elas). O usuário só precisa de
`SELECT`.

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

O `docker-compose.override.yml` sobe um PostGIS, no papel do SIGA, com `db/dev/00_siga_stub.sql`: só
as tabelas do SIGA que a ferramenta lê, com 36 municípios, procedimentos, intervenções, finalidades e a pessoa do PDF de
exemplo. Os polígonos de Altos e Teresina são retângulos fictícios.

Sem Docker: Redis, Tesseract 5 com o idioma `por`, Python 3.12 e Node 22; um PostgreSQL + PostGIS com o
stub do SIGA (`db/dev`) ou `REFERENCIAS=estaticas` para validar sem o SIGA.

```bash
cd services/ocr && pip install -r requirements-dev.txt
export SIGA_DATABASE_URL=postgresql+psycopg://ocr:ocr@localhost:5432/siga STORAGE_BACKEND=local STORAGE_DIR=/tmp/ocr
export REDIS_URL=redis://localhost:6379/3                  # ou memoria:// (um processo só, com CELERY_EAGER=true)
uvicorn ocr_requerimentos.api.main:app --reload            # API
celery -A ocr_requerimentos.worker worker -Q ocr,padrao   # worker (ou CELERY_EAGER=true para dispensar Redis)
cd ../../apps/web && npm install && API_URL=http://localhost:8000 npm run dev
```

## Produção

```bash
make prod           # = docker compose -f docker-compose.yml up -d --build
make escalar N=4    # mais workers de OCR (cada um usa 1 núcleo por tarefa)
```

Dados: ficam no bucket `S3_BUCKET` (MinIO do compose ou um S3 externo, com `S3_ENDPOINT` e credenciais
no `.env`); faça backup do bucket, que é a fonte da verdade. O Redis (`redis://redis:6379`, base 2 para
a fila e 3 para o índice) não precisa de backup: o índice se refaz com `make reconstruir-indice`.

SIGA: preencha as variáveis `SIGA_DB_*` do `.env` (ou `SIGA_DATABASE_URL`). A ferramenta **só lê** o SIGA
(com `REFERENCIAS=siga`). Em desenvolvimento, o `docker-compose.override.yml` troca o SIGA pelo PostGIS
local. Permissões sugeridas:

```sql
CREATE ROLE ocr_leitura LOGIN PASSWORD '...';
GRANT USAGE ON SCHEMA public TO ocr_leitura;
GRANT SELECT ON core_estado, core_municipio, core_pessoa, core_pessoafisica, core_pessoajuridica,
  protocolo_procedimento, protocolo_processo, outorga_tipointervencao, outorga_tipofinalidadeuso TO ocr_leitura;
```

Confira o SRID das geometrias do SIGA (`SRID`, padrão 4674/SIRGAS 2000). A checagem do ponto dentro
do município transforma o ponto para o SRID de `core_municipio.geom` automaticamente.

## Pontos de integração pendentes

**Login.** A web é o único cliente da API: o proxy `apps/web/app/api/ocr/[...path]/route.ts` acrescenta
`X-API-Key` e `X-Usuario-Id`, e o navegador nunca vê a chave. Para usar o login do SIGA (Better Auth),
troque a função `usuarioAtual` pelo `auth.api.getSession(...)` da configuração que o SIGA já usa e
responda 401 sem sessão. Até lá, `DEV_USUARIO_ID` define o usuário gravado no histórico.

**Listas do formulário.** Sistemas de irrigação, culturas e as demais listas das finalidades não têm
tabela no SIGA, então vêm de `services/ocr/ocr_requerimentos/dados_referencia.py` (copiadas do formulário
público em 01/10/2026). O id de cada opção é a posição na lista: se o formulário mudar, acrescente as
opções novas no fim e suba `VERSAO_PIPELINE`.

**QR code no PDF (recomendado).** Se o gerador do PDF do requerimento incluir um QR com
`SIGA-REQ|v1|<uuid do processo>|<hash>`, o documento digitalizado fica ligado ao processo sem
depender do OCR. `ocr_requerimentos.imagem.qrcode.gerar_png(uuid, hash)` gera a imagem; imprima com
pelo menos 2 cm de lado.

**Enviar para o SIGA.** A ferramenta grava e valida os dados nos JSONs do bucket. Criar ou atualizar
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
| `GET /documentos/{uuid}` | campos com valor lido, normalizado, confiança, leitura original do OCR, página e caixa |
| `GET /documentos/{uuid}/json` | o arquivo JSON do requerimento, como está gravado no bucket |
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
python -m pytest -q                                   # unitários, extração (precisa do Tesseract) e repositório de JSON
TEST_DATABASE_URL=postgresql+psycopg://ocr:ocr@localhost:5432/siga_test python -m pytest -q   # + integração com o SIGA
```

Os testes gravam os JSONs numa pasta temporária e usam um Redis em memória (`fakeredis`).
`TEST_DATABASE_URL` deve apontar para um PostGIS **descartável**: as tabelas do stub do SIGA são recriadas.
Os documentos de teste são o PDF real enviado e PDFs sintéticos no mesmo layout
(`tests/fabrica.py`), também degradados: rotação, ruído, JPEG ruim, papel amarelado, foto em
perspectiva, página de cabeça para baixo, assinatura em caneta azul, assinatura digital e QR code.

## Limitações conhecidas

- O parser segue o texto do modelo atual do requerimento. Se o texto do PDF mudar, ajuste as
  expressões em `extracao/parser.py` (os testes mostram rapidamente o que quebrou).
- Manuscrito não é lido: só o texto impresso. A assinatura à mão é detectada como presença de tinta.
- Os detalhes de cada finalidade são lidos conforme as definições em `extracao/finalidades.py`; um
  campo novo no formulário precisa ser descrito lá.
- Reprocessar um documento `dividido` não relê as partes já criadas. Se a divisão falhar no meio, as
  partes já criadas continuam existindo (o documento original vai para `erro` e pode ser reprocessado).
- A busca por trecho de texto varre os candidatos (ver "Volume" acima).
- Uma tarefa que encontre o documento travado por outro processo por mais de 60 s volta para a fila
  (até 2 vezes); na API, a resposta é 409.
- O motor PaddleOCR é opcional e não foi testado; o Tesseract é o padrão testado.
- O armazenamento S3/MinIO usa boto3 padrão. Os testes automatizados usam o armazenamento local; o fluxo
  com MinIO e Redis reais (envio, correção, validação, versões no bucket e reconstrução do índice) e a carga
  sintética foram conferidos à parte.
