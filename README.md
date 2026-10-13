# OCR de requerimentos do SIGA

Ferramenta da SEMARH-PI que transforma requerimentos de outorga em papel (ou em PDF) em dados
estruturados e conferidos. Ela lê o documento, extrai os campos do formulário, confere cada um com o
cadastro do SIGA, aponta o que precisa de atenção e, depois da validação, entrega um JSON padronizado
para o SIGA.

- [Escopo](#escopo)
- [Arquitetura](#arquitetura)
- [Tecnologias e o que cada uma faz](#tecnologias-e-o-que-cada-uma-faz)
- [Fluxo detalhado](#fluxo-detalhado)
- [Onde os dados ficam](#onde-os-dados-ficam)
- [Publicação para o SIGA](#publicação-para-o-siga-json-padrão)
- [Rodar em desenvolvimento](#rodar-em-desenvolvimento) · [Produção](#produção) · [API](#api) · [Testes](#testes)

## Escopo

**Para quem é.** Técnicos da SEMARH-PI que recebem requerimentos de outorga ("Regularização de Poço
Tubular" e afins) e precisam lançá-los no SIGA sem redigitar o formulário.

**O que a ferramenta faz**

| | |
|---|---|
| Recebe | PDF gerado pelo sistema, PDF assinado digitalmente, PDF de scanner, foto de celular ou imagem (PDF, JPG, PNG, TIFF, WEBP, BMP, HEIC). Um arquivo, vários, um ZIP ou a pasta onde o scanner salva |
| Lê | texto do PDF direto quando existe; senão, trata a imagem e faz OCR. Um PDF com vários requerimentos é separado em um documento por requerimento |
| Extrai | requerente e CPF/CNPJ, procedimento, tipo de intervenção, município, localidade, coordenadas, finalidades com os detalhes de cada uma, tabela de irrigação, descrição dos usos, assinante e data |
| Confere | cada campo com o SIGA: pessoa pelo CPF, município do Piauí, procedimento, intervenção, finalidade e se o ponto cai dentro do polígono do município. Cada campo recebe uma confiança |
| Mostra | uma tela de conferência com a folha ao lado do formulário e cada campo marcado no trecho de onde foi lido |
| Guarda | cada requerimento num arquivo JSON no bucket (S3/MinIO), com a leitura original do OCR, as correções e quem fez o quê |
| Entrega | um JSON padrão por requerimento validado, mais um consolidado, no bucket do SIGA |

**O que fica de fora, de propósito**

- **Escrever no SIGA.** A ferramenta só lê o banco do SIGA. Criar processo ou ponto de interferência a
  partir dos validados é uma etapa separada, que deve passar pelas regras do próprio SIGA (Django).
- **Ler manuscrito.** Só o texto impresso é lido. A assinatura à mão é detectada como presença de tinta.
- **Login próprio.** A identidade do usuário virá do login do SIGA (ver [Pontos de integração
  pendentes](#pontos-de-integração-pendentes)).

## Arquitetura

```mermaid
flowchart LR
    subgraph entrada["Entrada"]
        U["Técnico no navegador"]
        S["Scanner<br/>(pasta monitorada)"]
    end

    subgraph web["apps/web · Next.js"]
        T["Telas<br/>envio · lotes · revisão · conferência"]
        PX["Proxy /api/ocr<br/>põe X-API-Key e X-Usuario-Id"]
    end

    subgraph ocr["services/ocr · Python"]
        API["API REST<br/>FastAPI + Uvicorn"]
        W["Worker<br/>Celery"]
        WT["Watcher<br/>pasta do scanner"]
    end

    subgraph dados["Dados"]
        R[("Redis<br/>fila · índice · travas")]
        B[("Bucket S3/MinIO<br/>originais · páginas · JSONs")]
    end

    subgraph siga["SIGA"]
        DB[("PostgreSQL + PostGIS<br/>só leitura")]
        BS[("Bucket do SIGA<br/>JSON padrão")]
    end

    U --> T --> PX --> API
    S --> WT
    API -- "arquivo e JSON" --> B
    API -- "enfileira leitura" --> R
    WT -- "registra e enfileira" --> B & R
    R -- "tarefa" --> W
    W -- "lê original, grava resultado" --> B
    W -- "consulta CPF, município, listas" --> DB
    API -- "listas e filtros" --> R
    W -- "publica validados" --> BS
```

Cada peça tem um papel só:

- **A web não guarda nada.** Ela mostra os dados e repassa as chamadas para a API por um proxy no
  servidor, para que o navegador nunca veja a chave da API.
- **A API responde rápido.** Ela recebe o arquivo, grava no bucket, cria o documento e põe a leitura na
  fila. O OCR, que é lento, nunca roda dentro de uma requisição.
- **O worker faz o trabalho pesado.** Ele lê o arquivo, extrai, confere com o SIGA e grava o resultado.
  Para ler mais rápido, basta subir mais workers.
- **O bucket é a fonte da verdade.** O Redis só guarda a fila e um índice que se refaz a partir do
  bucket.

```
apps/web            Next.js (App Router): envio, lotes, fila de revisão e conferência
  app/api/ocr/      proxy para a API (chave e usuário ficam no servidor)
services/ocr        Python: API FastAPI, worker Celery, monitor de pasta, pipeline de OCR
  ocr_requerimentos/
    api/            rotas REST
    extracao/       parser por âncoras, normalizadores, validação, referências do SIGA
    imagem/         pré-processamento (OpenCV), Tesseract/PaddleOCR, QR code, assinatura
    pipeline/       leitura do arquivo, orquestração, gravação do resultado, correções
    modelos.py      contrato dos arquivos JSON (fonte da verdade)
    repositorio.py  JSON no bucket + índice, travas e contadores no Redis
    publicacao.py   JSON padrão para o SIGA
    worker.py       tarefas Celery (leitura e publicação)
    watcher.py      monitor da pasta do scanner
    ferramentas.py  reconstruir índice, relatório de acurácia, JSON Schema, carga sintética
  tests/            testes automatizados (ver docs/cenarios-de-teste.md)
db/dev              stub das tabelas do SIGA para desenvolvimento
docs                cenários de teste e JSON Schema dos arquivos (docs/contrato-json)
```

## Tecnologias e o que cada uma faz

| Camada | Tecnologia | O que faz aqui |
|---|---|---|
| Interface | **Next.js 16** (App Router), **React 19**, **TypeScript** | Telas de envio, lotes, fila de revisão, lista de requerimentos e conferência. A rota `/api/ocr` funciona como proxy para a API |
| | **Atkinson Hyperlegible** | Fonte feita para leitura sem ambiguidade (0/O, 1/l/I), importante para conferir CPF e coordenadas |
| API | **FastAPI** + **Uvicorn** | API REST: recebe envios, devolve listas e detalhes, aplica correções, valida e exporta |
| | **Pydantic** / pydantic-settings | Contrato dos arquivos JSON (todo JSON passa por ele antes de ser gravado) e configuração por variáveis de ambiente |
| Fila | **Celery** sobre **Redis** | Fila de leitura (`ocr`) e de publicação (`padrao`), com novas tentativas. Cada worker lê um documento por vez |
| Índice | **Redis 7** | Índice derivado dos JSONs (listas, filtros, paginação), contadores de lote, mapa SHA-256 → documento e travas contra gravação simultânea. Usa AOF e `noeviction` |
| Armazenamento | **MinIO** (ou S3) via **boto3** | Guarda os originais, a imagem corrigida de cada página e os JSONs, com versionamento ligado (cada regravação guarda a anterior) |
| PDF | **PyMuPDF** | Lê o texto do PDF com a posição de cada palavra, gera a imagem da página em 300 dpi e corta um PDF com vários requerimentos em partes |
| Imagem | **OpenCV**, **NumPy**, **Pillow** | Corrige perspectiva, orientação e inclinação, remove a tinta azul e detecta a assinatura à mão |
| OCR | **Tesseract 5** (`por`) via pytesseract | Motor de OCR padrão e testado. **PaddleOCR** é opcional (`MOTOR_OCR=paddle`) |
| Correspondência | **RapidFuzz** | Casa o texto lido com as listas do SIGA (municípios, procedimentos, finalidades, culturas) tolerando erros de OCR |
| QR code | **zxing-cpp** (leitura), **qrcode** (geração) | Liga o documento ao processo do SIGA quando o PDF traz o QR |
| Assinatura digital | **pyHanko**, certvalidator, cryptography | Identifica quem assinou o PDF e confere a integridade |
| SIGA | **SQLAlchemy** + **psycopg**, **PostgreSQL/PostGIS** | Consulta (só leitura) pessoas pelo CPF, municípios e polígonos (`ST_Intersects`) e as listas do formulário |
| Exportação | **openpyxl** | Planilha XLSX do lote (CSV e JSON saem sem biblioteca extra) |
| Infraestrutura | **Docker Compose** | Sobe redis, minio, api, worker, watcher e web (e o PostGIS no papel do SIGA, em desenvolvimento). **Flower** é opcional (perfil `monitor`) para acompanhar a fila |
| Testes | **pytest**, **fakeredis**, httpx | Testes de unidade, de extração e da API, com Redis em memória e armazenamento numa pasta temporária |

## Fluxo detalhado

### 1. Visão geral: do arquivo ao SIGA

```mermaid
flowchart TD
    A["Arquivo enviado<br/>tela, ZIP ou pasta do scanner"] --> B{"Mesmo arquivo<br/>já existe? (SHA-256)"}
    B -- sim --> B1["Reaproveita o documento existente<br/>e o põe no lote novo, sem ler de novo"]
    B -- não --> C["Grava o original no bucket<br/>cria o documento: recebido"]
    C --> D["Fila de leitura (Celery/Redis)"]
    D --> E["Worker: processando"]
    E --> F{"Leu?"}
    F -- "arquivo ilegível" --> ERR["erro<br/>'Ler de novo' devolve à fila"]
    ERR -. reprocessar .-> D
    F -- "vários requerimentos" --> DIV["dividido<br/>cada parte vira um documento<br/>e segue o mesmo fluxo"]
    F -- "um requerimento" --> G["Extração + validação com o SIGA<br/>confiança por campo"]
    G --> H{"Enviado como<br/>já conferido?"}
    H -- sim --> V["validado<br/>automaticamente, em nome de quem enviou;<br/>pendências vão para o histórico"]
    H -- não --> I{"Há pendências?"}
    I -- não --> X["extraido<br/>pronto para validar"]
    I -- sim --> RV["revisao<br/>fila de revisão"]
    X & RV --> K["Tela de conferência<br/>folha ao lado do formulário"]
    K -- "corrige e salva<br/>(revalida e registra no histórico)" --> I
    K -- "valida<br/>(com justificativa se houver pendências)" --> V
    V --> P["Publica o JSON padrão<br/>no bucket do SIGA"]
    V -- "correção depois de validado" --> I
    P --> Q["requerimentos.json consolidado<br/>regerado por intervalo"]
```

### 2. Uma leitura, passo a passo

O que acontece entre a fila e a gravação do resultado, dentro do worker:

```mermaid
flowchart TD
    A["Original lido do bucket"] --> B{"Tipo do arquivo"}
    B -- "PDF com texto<br/>(sistema ou assinado)" --> N["Lê as palavras com posição<br/>direto do PDF · confiança 100%"]
    B -- "PDF de scanner<br/>ou imagem" --> O1["Página em 300 dpi"]
    N --> SIG["Assinatura digital<br/>(pyHanko: quem assinou e integridade)"]
    O1 --> O2["Corrige perspectiva<br/>(foto de celular)"]
    O2 --> O3["Corrige orientação 90°/180°<br/>e inclinação"]
    O3 --> O4["Remove a tinta azul<br/>(assinatura e carimbo somem)"]
    O4 --> O5["OCR · Tesseract"]
    O5 --> QR["Procura QR code<br/>(liga ao processo do SIGA)"]
    SIG --> SEG
    QR --> SEG["Separa por página que começa com 'REQUERIMENTO'<br/>(um PDF com vários vira várias partes)"]
    SEG --> PA["Parser por âncoras<br/>'inscrito sob o CPF/CNPJ', 'vem requerer … para …',<br/>'localizado no município', 'latitude … e longitude',<br/>seções das finalidades, tabela de irrigação, rodapé"]
    PA --> RL["Segunda leitura dos números<br/>CPF, coordenadas, áreas e data num recorte em cinza"]
    RL --> NO["Normalização<br/>máscara do CPF, graus decimais,<br/>sinal negativo do Piauí, datas"]
    NO --> VA["Validação com o SIGA<br/>pessoa pelo CPF · município do PI ·<br/>procedimento · intervenção · finalidade ·<br/>ponto dentro do polígono do município"]
    VA --> CF["Confiança por campo<br/>abaixo de LIMIAR_CONFIANCA (80) = pendência"]
    CF --> GR["Grava o JSON do documento<br/>e a imagem de cada página no bucket;<br/>atualiza o índice no Redis"]
```

### 3. Quem fala com quem num envio

```mermaid
sequenceDiagram
    autonumber
    actor T as Técnico
    participant WEB as Web (Next.js)
    participant API as API (FastAPI)
    participant RD as Redis
    participant BK as Bucket (MinIO)
    participant WK as Worker (Celery)
    participant SG as SIGA (PostGIS)
    participant BS as Bucket do SIGA

    T->>WEB: escolhe os arquivos e a opção<br/>"conferir na tela" ou "já conferidos"
    WEB->>API: POST /lotes (ou /documentos)<br/>validar_ao_ler, X-API-Key, X-Usuario-Id
    API->>RD: trava pelo SHA-256 (evita duplicado)
    API->>BK: grava original + JSON (recebido)
    API->>RD: indexa e enfileira a leitura
    API-->>WEB: 201 com o lote/documento
    WEB-->>T: abre o lote e acompanha o progresso
    RD->>WK: tarefa ocr.processar_documento
    WK->>BK: lê o original
    WK->>WK: OCR e extração (fora da trava)
    WK->>SG: CPF, município, polígono, listas
    WK->>RD: trava o documento
    WK->>BK: grava o resultado (extraido, revisao ou validado)
    WK->>RD: atualiza índice e contadores do lote
    alt documento validado
        WK->>BS: publica requerimentos/{uuid}.json
        WK->>BS: regera requerimentos.json (no máximo 1x por intervalo)
    end
    T->>WEB: abre a conferência, corrige e valida
    WEB->>API: PATCH /correcoes, POST /validar (com a versão lida)
    API->>BK: grava nova versão do JSON (409 se outro gravou antes)
```

### 4. Situações do documento

```mermaid
stateDiagram-v2
    [*] --> recebido: envio
    recebido --> processando: worker pega da fila
    processando --> extraido: sem pendências
    processando --> revisao: com pendências
    processando --> validado: enviado como já conferido
    processando --> erro: arquivo ilegível
    processando --> dividido: vários requerimentos no arquivo
    dividido --> [*]: as partes seguem o fluxo
    erro --> recebido: ler de novo
    extraido --> revisao: correção cria pendência
    revisao --> extraido: correção resolve as pendências
    extraido --> validado: validar
    revisao --> validado: validar com justificativa
    extraido --> recebido: ler de novo
    revisao --> recebido: ler de novo
    validado --> extraido: correção depois de validado
    validado --> revisao: correção depois de validado
    validado --> [*]: publicado para o SIGA
```

| Situação | Significa | Na tela |
|---|---|---|
| `recebido` | na fila de leitura | Na fila |
| `processando` | o worker está lendo; correção e validação ficam bloqueadas | Lendo |
| `extraido` | lido sem pendências | Pronto para validar |
| `revisao` | lido, com campos para conferir | Em revisão (fila de revisão) |
| `validado` | conferido; vai para o SIGA | Validado |
| `erro` | não foi possível ler o arquivo | Erro |
| `dividido` | arquivo com vários requerimentos; cada parte é um documento | Dividido |

### Regras do fluxo

- **Validar com pendências exige justificativa**, que fica no histórico e vai junto para o SIGA.
- **Enviar como já conferido.** No envio, depois de escolher os arquivos, dá para optar entre *conferir
  na tela* (o padrão) e *já estão conferidos: só armazenar*. Na segunda opção, cada requerimento novo é
  validado sozinho assim que a leitura termina, em nome de quem enviou, mesmo com pendências: elas ficam
  no histórico com a justificativa automática, e a validação sai com `validacao.modo = "envio"` (no JSON
  interno e no JSON do SIGA). Vale também para as partes de um PDF dividido. Arquivos já enviados antes
  mantêm a situação que tinham, e um arquivo que dê erro de leitura é validado quando for lido de novo.
  Depois de validado, o documento segue as regras de sempre: uma correção desfaz a validação e ele volta
  para a conferência.
- **Ler de novo não perde a revisão.** Depois da nova leitura (`reprocessar`), as correções manuais são
  reaplicadas. Listas corrigidas (finalidades, irrigação, itens de uma finalidade) voltam inteiras como o
  revisor deixou. Documento validado não pode ser lido de novo (409).
- **Mesmo arquivo, um documento só.** O SHA-256 identifica o arquivo: reenviado, ele entra no lote novo
  sem ser lido de novo.

### Escolhas da leitura que valem conhecer

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

## Publicação para o SIGA (JSON padrão)

Os requerimentos **validados** são publicados no bucket do SIGA num formato próprio, o contrato com o
SIGA (`docs/contrato-json/siga-requerimento.schema.json`, gerado de `publicacao.py`):

```
{SIGA_S3_PREFIXO}requerimentos/{uuid}.json   um requerimento; gravado na hora em que é validado ou alterado,
                                             e removido se uma correção desfizer a validação
{SIGA_S3_PREFIXO}requerimentos.json          todos os validados (consolidado); regerado no máximo uma vez a
                                             cada SIGA_CONSOLIDADO_INTERVALO_S (padrão 5 min) após mudanças
```

Cada requerimento traz `formulario` (os dados do formulário consolidados: requerente, procedimento,
intervenção, localização, finalidades com detalhes, irrigação, data; com os ids do SIGA quando
encontrados), `validacao` (quem, quando, e a justificativa se validado com pendências), `campos` (para
cada campo: `valor_final`, `confianca_final`, `corrigido_manualmente` e `leitura_original_ocr`),
`historico_de_revisoes` e `origem` (arquivo, SHA-256, QR code, versão do OCR). Texto e posição das
palavras do OCR ficam só no JSON interno.

- Na tela, **"JSON consolidado"** na barra superior baixa esse mesmo conteúdo, gerado na hora.
- Configuração: `SIGA_S3_BUCKET` (sem ele a publicação fica desligada), `SIGA_S3_ENDPOINT`,
  `SIGA_S3_ACCESS_KEY`, `SIGA_S3_SECRET_KEY` (vazios usam os `S3_*`) e `SIGA_S3_PREFIXO`. Em
  desenvolvimento, o override publica num bucket `siga` do MinIO local, com intervalo de 60 s.
- O envio roda no worker e é repetido se o bucket do SIGA estiver fora do ar. Para uma carga inicial ou
  depois de uma falha longa: `POST /siga/republicar` ou
  `python -m ocr_requerimentos.ferramentas publicar-siga`.

## Rodar em desenvolvimento

Requer Docker com Compose v2.

```bash
cp .env.example .env
make dev            # = docker compose up --build
```

- Tela: http://localhost:3000
- API e documentação interativa: http://localhost:8000/docs (outra porta com `API_PORTA` no `.env`)
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
| `POST /documentos` | envia um arquivo (201; 200 com `duplicado: true` se o mesmo arquivo já existe); `validar_ao_ler=true` valida ao fim da leitura (já conferido) |
| `POST /lotes` | envia vários arquivos e/ou ZIPs; informa duplicados (que passam a fazer parte do lote, sem nova leitura) e formatos não suportados; `validar_ao_ler` como no envio avulso |
| `GET /lotes`, `GET /lotes/{uuid}` | lista e detalhe com documentos e contadores |
| `POST /lotes/{uuid}/reprocessar-erros` | devolve à fila só os que deram erro |
| `GET /lotes/{uuid}/exportar?formato=csv\|xlsx\|json` | planilha do lote (CSV com `;` e BOM para Excel) ou os JSONs de todos os documentos, como estão gravados |
| `GET /documentos?status=&busca=` e `GET /revisao` | listas e fila de revisão; `busca` acha CPF/CNPJ com ou sem máscara |
| `GET /documentos?requerente=&procedimento=&municipio=&data_de=&data_ate=&campo_data=&pagina=&tamanho=` | filtros da lista de requerimentos, combinados com E: requerente sem diferenciar maiúsculas e acentos; período inclusivo pela data do documento (`campo_data=documento`, padrão) ou de gravação (`gravacao`, dia no fuso do Piauí) |
| `GET /filtros` | procedimentos e municípios presentes nos requerimentos gravados, com a quantidade de cada |
| `GET /documentos/{uuid}` | campos com valor lido, normalizado, confiança, leitura original do OCR, página e caixa |
| `GET /documentos/{uuid}/json` | o arquivo JSON do requerimento, como está gravado agora no bucket (sem cache; o nome traz a versão) |
| `GET /documentos/{uuid}/arquivo`, `/paginas/{n}/imagem` | original e página corrigida |
| `PATCH /documentos/{uuid}/correcoes` | corrige campos, finalidades e tabela de irrigação; revalida e audita. Com `versao` (de `requerimento.versao`), 409 se outro gravou antes |
| `POST /documentos/{uuid}/validar` | valida (`forcar` + `justificativa` quando há pendências; `versao` como nas correções) |
| `POST /documentos/{uuid}/reprocessar` | lê de novo e reaplica as correções manuais (409 se já validado) |
| `GET /documentos/{uuid}/revisoes` | histórico de correções |
| `GET /siga/requerimentos.json` | JSON padrão do SIGA com todos os validados, gerado na hora (o botão "JSON consolidado") |
| `GET /siga/requerimentos/{uuid}.json` | JSON padrão do SIGA de um requerimento, para conferência |
| `GET /siga/situacao`, `POST /siga/republicar` | situação da publicação; reenvio de todos os validados e do consolidado |
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
