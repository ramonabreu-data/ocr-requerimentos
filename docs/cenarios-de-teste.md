# Cenários de teste

Cada cenário tem um identificador (CT-xx) que aparece no nome do teste automatizado correspondente
em `services/ocr/tests/`. Os cenários da tela (CT-7x) são roteiros de teste manual.

Os documentos de teste são o PDF real enviado (`tests/fixtures/requerimento_exemplo.pdf`) e PDFs
sintéticos gerados no mesmo layout por `tests/fabrica.py`, que também simula digitalização ruim
(rotação, ruído, JPEG, papel amarelado, foto em perspectiva, assinatura em caneta azul).

## 1. Normalização e regras de negócio (unitários, sem banco)

| ID | Dado | Quando | Então |
|---|---|---|---|
| CT-01 | CPF `05974965361` | normalizado | válido, tipo F, formatado `059.749.653-61` |
| CT-02 | CPF lido pelo OCR como `O5974965361` | normalizado | letra O vira zero e o CPF continua válido |
| CT-03 | CPF com dígito verificador errado | normalizado | inválido, com mensagem de DV |
| CT-04 | CNPJ válido com máscara | normalizado | válido, tipo J |
| CT-05 | Latitude `-5°02'91.06"` (do PDF real) | convertida | erro "segundos fora do intervalo" |
| CT-06 | Longitude `-42°42'32.38"` | convertida | -42,7089944 sem erros |
| CT-07 | Coordenada sem sinal (`5°02'41"`) | convertida | recebe sinal negativo e aviso "assumido Sul/Oeste" |
| CT-08 | Coordenada com hemisfério (`5°02'41,5" S`) e grau lido como `o` | convertida | -5,0448611 |
| CT-09 | Áreas `10`, `2,5`, `1.234,5`, `1O` | normalizadas | 10, 2,5, 1234,5 e 10 |
| CT-10 | Município `ALT0S` (zero no lugar do O) | comparado com a lista do PI | associado a Altos |
| CT-11 | Município `Alto` | comparado | não é confundido com Altos nem Alto Longá abaixo do limiar |
| CT-12 | Coordenadas fora do Piauí | validadas | documento vai para revisão com pendência de limites |
| CT-13 | Finalidade Irrigação sem tabela | validada | pendência "Irrigação sem itens" |
| CT-14 | Finalidade Abastecimento Humano sem tabela | validada | sem pendência de tabela |
| CT-15 | Data no futuro | validada | campo inválido |

## 2. Extração (parser + leitura)

| ID | Dado | Quando | Então |
|---|---|---|---|
| CT-20 | PDF real enviado (texto nativo) | processado | lê sem OCR, todos os campos corretos, 3 linhas de irrigação, revisão só pela latitude inválida |
| CT-21 | PDF sintético válido (texto nativo) | processado | status `extraido`, confiança 100, nenhuma pendência |
| CT-22 | PDF real renderizado a 300 dpi como PNG | OCR | mesmos valores do CT-20 |
| CT-23 | Digitalização a 200 dpi girada 3°, com ruído e JPEG | OCR | inclinação corrigida (≈3°) e campos principais corretos |
| CT-24 | Página de cabeça para baixo (180°) | OCR | orientação corrigida e campos lidos |
| CT-25 | Foto de celular: folha em perspectiva sobre mesa, papel amarelado | OCR | folha retificada e campos principais corretos |
| CT-26 | PDF de scanner (só imagem) | processado | tipo `pdf_imagem`, método `ocr` |
| CT-27 | Assinatura em caneta azul sobre a linha | OCR | assinatura `manuscrita`; o texto ao redor continua correto |
| CT-28 | Documento impresso sem assinatura | OCR | assinatura `ausente` |
| CT-29 | PDF assinado digitalmente | processado | assinatura `digital` com nome do certificado, leitura por texto nativo |
| CT-30 | PDF com QR code `SIGA-REQ` | processado | uuid do processo lido do QR |
| CT-31 | Campo numérico com leituras divergentes | segunda leitura | confiança rebaixada e nota com a leitura alternativa |
| CT-32 | Arquivo que não é PDF nem imagem | lido | erro "formato não suportado" |
| CT-33 | Linha de tabela com área decimal `2,5` e cultura de duas palavras | extraída | sistema, área e cultura separados corretamente |
| CT-34 | Duas finalidades (Irrigação + Abastecimento Humano) | extraído | as duas finalidades reconhecidas e a tabela ligada à Irrigação |

## 3. API, gravação em JSON e lotes (integração com o SIGA em PostgreSQL + PostGIS, só leitura)

| ID | Dado | Quando | Então |
|---|---|---|---|
| CT-40 | Upload avulso do PDF real | `POST /documentos` | 201; ao final, status `revisao`, requerimento gravado com 3 itens de irrigação e CPF ligado à pessoa do cadastro |
| CT-41 | Mesmo arquivo enviado de novo | `POST /documentos` | 200 com `duplicado: true`, sem novo processamento |
| CT-42 | Correção da latitude para um valor válido | `PATCH /correcoes` | revalidado; sai da revisão; histórico registra antes/depois |
| CT-43 | Validar documento com pendências | `POST /validar` | 409 |
| CT-44 | Validar com pendências usando justificativa | `POST /validar` com `forcar` | validado e justificativa auditada |
| CT-45 | Ponto fora do polígono do município declarado | processado | pendência "fora do município declarado" (ST_Intersects) |
| CT-46 | Nome lido diferente do cadastro do CPF | processado | confiança do nome rebaixada com o nome do cadastro na mensagem |
| CT-47 | PDF com 3 requerimentos (scanner juntou tudo) | processado | documento pai `dividido` e 3 documentos filhos processados |
| CT-48 | ZIP com 2 PDFs, 1 imagem, 1 `.txt` e 1 duplicado | `POST /lotes` | lote conclui com erros: 3 processados, 1 erro, 1 duplicado informado |
| CT-49 | Lote com erro | `reprocessar-erros` | só o documento com erro volta para a fila |
| CT-50 | Lote processado | exportar CSV e XLSX | CSV com BOM e `;`; XLSX com abas Requerimentos e Irrigação |
| CT-51 | `API_KEY` configurada e cabeçalho ausente | qualquer rota protegida | 401 |
| CT-52 | Correção da tabela de irrigação (trocar cultura, remover linha) | `PATCH /correcoes` | itens regravados e marcados como corrigidos manualmente |
| CT-53 | Imagem da página | `GET /paginas/1/imagem` | JPEG da página corrigida |
| CT-54 | Reprocessar documento validado | `POST /reprocessar` | 409 |
| CT-55 | PDF real (com pendência) enviado como já conferido | `POST /documentos` com `validar_ao_ler` | validado ao fim da leitura em nome de quem enviou, `modo` `envio` no detalhe e no JSON do SIGA, justificativa automática no histórico; sem a opção, continua indo para a conferência |
| CT-56 | Lote já conferido com PDF de 2 requerimentos e um arquivo já enviado | `POST /lotes` com `validar_ao_ler` | as 2 partes validadas; o duplicado mantém a situação que tinha |
| CT-90 | Documento com latitude e irrigação corrigidas | `POST /reprocessar` | correções reaplicadas sobre a nova leitura; auditoria só registra `__reprocessamento__` |
| CT-91 | Documento sem correções | `POST /reprocessar` | nenhuma entrada no histórico |
| CT-92 | Mesmo arquivo em dois lotes | `POST /lotes` duas vezes | os dois lotes contam e exportam o documento; validar atualiza os dois |
| CT-93 | PDF dividido reenviado em outro lote | `POST /lotes` | as partes entram no lote novo junto com o original |
| CT-94 | Duas pessoas corrigindo a mesma versão | `PATCH /correcoes` e `POST /validar` com `versao` antiga | 409; a primeira gravação prevalece |
| CT-95 | Documento em leitura | `PATCH /correcoes`, `POST /validar` | 409 |
| CT-96 | Status, confiança, CPF fora do padrão, validado sem data ou campo repetido | `repo.salvar` | o contrato do JSON recusa e o arquivo no bucket não muda; o mesmo CPF em dois requerimentos é aceito |
| CT-97 | Finalidade repetida na correção | `PATCH /correcoes` | aceita; detalhes ficam só na primeira |
| CT-98 | Campo corrigido e documento validado | leitura do JSON e `ferramentas acuracia` | `leitura_original_ocr` preserva a leitura ao lado de `valor_atual`; versão do pipeline e configuração gravadas; o relatório de acurácia conta a correção |

## 3b. Repositório de JSON e índice (sem banco: pasta temporária + Redis em memória)

| ID | Dado | Quando | Então |
|---|---|---|---|
| CT-100 | Campo corrigido à mão | gravar | o JSON traz `valor_atual`, `confianca_atual`, `corrigido_manualmente` e `leitura_original_ocr` com nomes explícitos, em UTF-8 legível |
| CT-101 | CPF com letra, confiança > 100, validado sem data, campo desconhecido, status inválido | validar / gravar | recusado pelo contrato; o arquivo gravado não muda |
| CT-102 | Contrato | `ferramentas json-schema` | gera `documento`, `paginas` e `lote` `.schema.json` com as descrições dos campos |
| CT-103 | 12 gravações simultâneas no mesmo documento | `travar` + `salvar` | nenhuma se perde |
| CT-104 | Mesmo arquivo enviado 8 vezes ao mesmo tempo | `registrar_documento` | um só documento; 7 duplicados; contado uma vez no lote |
| CT-105 | Gravação com versão antiga | `conferir_versao` | `ConflitoVersao`; sem versão continua aceito |
| CT-106 | Documento muda de situação e entra num segundo lote | `salvar` / `vincular_lote` | contadores dos dois lotes acompanham; lote sem pendentes fica com data de conclusão |
| CT-107 | Filtros, paginação e varredura em blocos | `consultar` | resultados e totais corretos; dividido fora das listas; opções de filtro acompanham correções; temporários apagados |
| CT-108 | Redis perdido | `reconstruir_indice` | índice refeito do bucket, idêntico ao anterior |
| CT-109 | Carga sintética (450 documentos, 3 lotes) | `carga_sintetica` | totais e contadores coerentes |
| CT-110 | Validados e pendentes com correções | `acuracia` | só os validados contam; campos incluídos na revisão contam como não lidos; faixas de confiança corretas |
| CT-116 | Documento lido, enviado como já conferido, com pendência | `validar_no_envio` | validado com `modo` `envio`, em nome de quem enviou, com a justificativa automática; a opção é consumida; sem a opção ou com erro de leitura, nada muda |
| CT-117 | Três arquivos registrados, um repetido, uma parte e o Redis perdido | `registrar_documento` / `reconstruir_indice` | `REQ-AAAA-000001`, `-000002`; o repetido mantém o número; a parte recebe `-1`; achado pela busca; depois de refazer o índice a sequência continua em `-000003`; formato fora do padrão recusado pelo contrato |
| CT-118 | Documentos gravados antes da numeração (um de 31/12 à noite, um arquivo dividido e sua parte) | `ferramentas numerar` | numerados pela ordem e pelo ano no fuso do Piauí; a parte recebe o número do arquivo com `-1`; rodar de novo não muda nada |

## 3c. Publicação para o SIGA (sem banco: "bucket do SIGA" numa pasta temporária)

| ID | Dado | Quando | Então |
|---|---|---|---|
| CT-111 | Requerimento validado com pendências e campo corrigido | `json_siga` | formulário consolidado, campo com `valor_final` e `leitura_original_ocr`, justificativa e pendências da validação; sem posição/texto do OCR |
| CT-112 | Documento validado e depois corrigido | `salvar` | publicado no bucket do SIGA ao validar; removido quando volta a pendente; não validado nunca vai |
| CT-113 | Dois validados e um em revisão | `consolidado` / `gravar_consolidado` | só os validados, do mais antigo ao mais novo; arquivo gravado com o mesmo conteúdo |
| CT-114 | Nenhum validado; cinco em blocos de 2 | `consolidado` | JSON válido com `total` 0; depois os 5, na ordem |
| CT-115 | Publicação desligada / documento inexistente | `publicar_documento` | nada é gravado; inexistente é retirado do destino |

## 4. Pasta monitorada

| ID | Dado | Quando | Então |
|---|---|---|---|
| CT-60 | Arquivo novo na pasta do scanner | varredura | lote do dia criado, documento enfileirado, arquivo movido para `processados/` |
| CT-61 | Arquivo ainda sendo copiado (tamanho mudando) | varredura | ignorado até estabilizar |

## 5. Interface (roteiro manual)

| ID | Passos | Resultado esperado |
|---|---|---|
| CT-70 | Enviar um PDF avulso pela tela de envio | redireciona para o documento; status atualiza sozinho até terminar |
| CT-71 | Enviar um ZIP | abre o lote com barra de progresso e lista de documentos |
| CT-72 | Abrir documento em revisão e clicar num campo | a imagem rola até o trecho e destaca a caixa do campo |
| CT-73 | Corrigir a latitude e salvar | pendência some, campo marcado como corrigido |
| CT-74 | Validar | status muda para validado e o documento sai da fila de revisão |
| CT-75 | Exportar lote em XLSX | arquivo baixa e abre no Excel/LibreOffice com acentos corretos |
| CT-76 | Tela em celular (≤ 400 px) | layout em coluna única, imagem acima do formulário |
| CT-77 | Navegação só por teclado | todos os controles alcançáveis e com foco visível |
| CT-78 | Escolher arquivos e marcar "Já estão conferidos: só armazenar" | o botão vira "Enviar e validar"/"Criar lote e validar"; ao fim da leitura, os documentos aparecem como Validado e a conferência diz "Validado no envio" |
| CT-79 | Abrir um documento e clicar na aba JSON | árvore no padrão do SIGA; "Completo" troca para o JSON gravado; "Baixar JSON" baixa o formato escolhido; com correções não salvas, o download fica bloqueado; as edições da conferência continuam lá ao voltar |

## Resultado da última execução

08/10/2026, depois da troca do banco pelos JSONs no bucket. Ambiente: Python 3.12, Tesseract 5 (`por`),
Redis em memória (fakeredis) nos testes, PostgreSQL 16 + PostGIS 3.4 com o stub do SIGA, Node 22.

- `pytest` com `TEST_DATABASE_URL`: **147 passaram, 0 falharam** (inclui os 5 da publicação para o
  SIGA). Sem banco, os 38 de integração com o SIGA são pulados.
- Publicação conferida na stack de desenvolvimento: validar um documento grava
  `requerimentos/{uuid}.json` no bucket `siga` do MinIO, o `requerimentos.json` aparece 60 s depois e
  o botão "JSON consolidado" baixa o mesmo conteúdo.
- Conferido à parte com MinIO e Redis reais: envio de lote com PDF dividido, correção, 409 com versão
  antiga, validação, JSON no bucket com a leitura original preservada, 5 versões do JSON guardadas pelo
  versionamento do bucket e índice reconstruído idêntico depois de apagar o Redis.
- Carga sintética de 100 mil documentos (números no README, seção "Onde os dados ficam").
- Interface: `next build` sem erros de tipo, com o botão "Baixar JSON" na tela do documento. O roteiro
  CT-70 a CT-77 não foi refeito nesta mudança (a API manteve rotas e respostas).
