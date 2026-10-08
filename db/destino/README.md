# DDL do schema `ocr` para um banco novo

Cria, num banco vazio, o schema `ocr` no mesmo estado das migrações 0001 a 0006, pronto para o pipeline
de OCR começar a gravar do zero. Não cria nem altera nenhuma tabela do SIGA, e não cria views (o banco
de destino não trabalha com views nem views materializadas).

| Arquivo | Conteúdo |
|---|---|
| `00_schema.sql` | extensão PostGIS e schema `ocr` |
| `01_tabelas.sql` | tabelas, chaves, restrições e índices |
| `02_dominios.sql` | listas do formulário (`ocr.dominio`) que o pipeline usa para validar irrigação e finalidades |
| `03_alembic_versao.sql` | marca o banco como migrado até a 0006, para o serviço aplicar só migrações futuras |
| `consultas/acuracia.sql` | **não é DDL**: consultas de acurácia do OCR, para rodar quando quiser analisar |

## Requisitos do banco

- PostgreSQL 13 ou mais novo (usa `gen_random_uuid()` nativo).
- PostGIS disponível. Criar a extensão exige permissão; se o DBA já a criou, essa linha não faz nada.
- O usuário do serviço precisa de `SELECT, INSERT, UPDATE, DELETE` nas tabelas do schema `ocr`,
  `USAGE` nas sequências e, para as migrações futuras, `CREATE` no schema.

## Criar

```bash
DESTINO="postgresql://usuario:senha@host:5432/banco"
for f in 00_schema.sql 01_tabelas.sql 02_dominios.sql 03_alembic_versao.sql; do
  psql "$DESTINO" -v ON_ERROR_STOP=1 --single-transaction -f "$f" || break
done
```

Outra forma, sem estes arquivos: com o `.env` apontando para o banco novo (abaixo) e `CRIAR_VIEWS=false`,
`docker compose -f docker-compose.yml run --rm migrar` cria o mesmo schema pelas migrations, sem as
views. Sem `CRIAR_VIEWS=false`, a migration 0006 cria as views de acurácia.

## Ligar o pipeline

As credenciais ficam no `.env`, que o `docker-compose.yml` lê e repassa para `migrar`, `api`, `worker` e
`watcher`; o serviço monta a conexão a partir delas (a senha vai como está, sem codificar):

```bash
DESTINO_DB_HOST=host-do-banco
DESTINO_DB_PORTA=5432
DESTINO_DB_NOME=ocr
DESTINO_DB_USUARIO=ocr_app
DESTINO_DB_SENHA=...
DESTINO_DB_SSLMODE=require   # disable | prefer | require | verify-full
CRIAR_VIEWS=false
```

`DATABASE_URL`, se definida, vale sobre essas partes. Se o banco foi criado com estes arquivos,
`docker compose -f docker-compose.yml run --rm migrar` termina sem aplicar nada (já está na 0006).

De onde o pipeline tira as listas de referência depende de `REFERENCIAS`:

- `siga` (padrão): lê `ocr.dominio` (irrigação e detalhes das finalidades, gravando o id) e, no schema
  `public`, as tabelas do SIGA `core_estado`, `core_municipio`, `core_pessoa`, `core_pessoafisica`,
  `core_pessoajuridica`, `protocolo_procedimento`, `protocolo_processo`, `outorga_tipointervencao` e
  `outorga_tipofinalidadeuso`. Essas tabelas precisam existir neste banco (ou o pipeline falha ao ler).
- `estaticas`: usa as listas do próprio código e não lê nada do SIGA nem de `ocr.dominio`. A extração
  funciona, mas município, requerente, procedimento e itens de irrigação ficam sem id e com confiança
  limitada, e quase todo documento vai para revisão.

O `db/dev/00_siga_stub.sql` cria essas tabelas com dados fictícios. Serve para teste, não para produção.

## Observações

- Os arquivos (PDFs e imagens de página) não ficam no banco: `storage_key` e `imagem_key` apontam para o
  armazenamento S3/MinIO configurado no serviço.
- As colunas `*_id` que apontam para o SIGA não têm chave estrangeira; são só números de referência.
- Estes arquivos refletem a migração 0006. As próximas migrações o próprio serviço aplica (`migrar`);
  se alguma criar ou alterar views, ela precisa pular este banco (ou ser aplicada à mão sem a view).
- O pipeline não usa as views em nenhum momento: elas só servem para análise. No banco principal elas
  continuam existindo; aqui as mesmas análises estão em `consultas/acuracia.sql`.
