.PHONY: dev prod parar logs escalar testes testes-integracao reconstruir-indice acuracia web-build

dev:            ## sobe tudo com Postgres/PostGIS fazendo o papel do SIGA
	@test -f .env || cp .env.example .env
	docker compose up --build

prod:           ## sobe sem Postgres local (lê o SIGA de SIGA_DB_* do .env)
	docker compose -f docker-compose.yml up -d --build

parar:
	docker compose down

logs:
	docker compose logs -f api worker watcher

escalar:        ## make escalar N=4
	docker compose up -d --scale worker=$(or $(N),4)

reconstruir-indice:  ## refaz o índice do Redis a partir dos JSONs do bucket
	docker compose run --rm api python -m ocr_requerimentos.ferramentas reconstruir-indice

acuracia:       ## análises de acurácia do OCR (CSV na saída)
	docker compose run --rm api python -m ocr_requerimentos.ferramentas acuracia

testes:         ## unitários, extração e repositório de JSON (sem banco), dentro do container
	docker build --target testes -t ocr-requerimentos/testes services/ocr
	docker run --rm ocr-requerimentos/testes

testes-integracao:  ## exige um PostGIS descartável em TEST_DATABASE_URL (stub do SIGA)
	cd services/ocr && TEST_DATABASE_URL=$(TEST_DATABASE_URL) python -m pytest -q

web-build:
	cd apps/web && npm ci && npm run build
