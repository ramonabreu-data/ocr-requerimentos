.PHONY: dev prod parar logs escalar testes testes-integracao migrar web-build

dev:            ## sobe tudo com Postgres/PostGIS e stub do SIGA
	@test -f .env || cp .env.example .env
	docker compose up --build

prod:           ## sobe sem Postgres local (usa DATABASE_URL do .env)
	docker compose -f docker-compose.yml up -d --build

parar:
	docker compose down

logs:
	docker compose logs -f api worker watcher

escalar:        ## make escalar N=4
	docker compose up -d --scale worker=$(or $(N),4)

migrar:
	docker compose run --rm migrar

testes:         ## unitários e de extração (sem banco), dentro do container
	docker build --target testes -t ocr-requerimentos/testes services/ocr
	docker run --rm ocr-requerimentos/testes

testes-integracao:  ## exige um PostGIS descartável em TEST_DATABASE_URL
	cd services/ocr && TEST_DATABASE_URL=$(TEST_DATABASE_URL) python -m pytest -q

web-build:
	cd apps/web && npm ci && npm run build
