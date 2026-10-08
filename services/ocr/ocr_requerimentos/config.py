from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco do SIGA, só leitura (pessoa pelo CPF, municípios e polígonos, procedimentos...). Os dados da
    # ferramenta não vão para banco: ficam em JSON no armazenamento (ver repositorio.py).
    # SIGA_DATABASE_URL, se definida, vale sobre as partes SIGA_DB_*; com as partes, a URL é montada aqui
    # (senha com @ : / não precisa ser codificada).
    siga_database_url: str = ""
    siga_db_host: str | None = None
    siga_db_porta: int = 5432
    siga_db_nome: str | None = None
    siga_db_usuario: str | None = None
    siga_db_senha: str | None = None
    siga_db_sslmode: str | None = None  # disable | prefer | require | verify-full ...

    # Redis: fila (Celery) e índice/travas dos JSONs. O índice é derivado do bucket e pode ser
    # reconstruído (python -m ocr_requerimentos.ferramentas reconstruir-indice).
    # "memoria://" usa um Redis em memória do próprio processo (testes; exige fakeredis).
    celery_broker_url: str = "redis://localhost:6379/2"
    celery_eager: bool = False  # executa tarefas na mesma thread (testes / desenvolvimento sem Redis)
    redis_url: str = "redis://localhost:6379/3"
    redis_prefixo: str = "ocr"
    trava_segundos: int = 120  # validade de uma trava de documento (renovada a cada gravação)

    storage_backend: str = "local"  # local | s3
    storage_dir: str = "/data/ocr"
    s3_endpoint: str | None = None
    s3_bucket: str = "ocr-requerimentos"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"

    api_key: str | None = None  # se definido, exigido no cabeçalho X-API-Key
    cors_origens: str = "http://localhost:3000"
    max_upload_mb: int = 50
    max_arquivos_zip: int = 500

    motor_ocr: str = "tesseract"  # tesseract | paddle
    idioma_tesseract: str = "por"
    limiar_confianca: float = 80.0
    remover_tinta_azul: bool = True
    confiar_texto_scanner: bool = False
    conferir_numeros: bool = True  # segunda leitura de CPF, coordenadas, áreas e datas

    uf: str = "PI"
    srid: int = 4674  # SIRGAS 2000; confira o SRID usado em outorga_pontointerferencia.coordenadas
    referencias: str = "siga"  # siga | estaticas

    pasta_monitorada: str | None = None
    pasta_intervalo_s: int = 10

    @model_validator(mode="after")
    def _montar_siga_database_url(self) -> "Config":
        if self.siga_database_url:
            return self
        if self.siga_db_host:
            self.siga_database_url = URL.create(
                "postgresql+psycopg", username=self.siga_db_usuario, password=self.siga_db_senha,
                host=self.siga_db_host, port=self.siga_db_porta, database=self.siga_db_nome,
                query={"sslmode": self.siga_db_sslmode} if self.siga_db_sslmode else {},
            ).render_as_string(hide_password=False)
        else:
            self.siga_database_url = "postgresql+psycopg://ocr:ocr@localhost:5432/siga"
        return self


@lru_cache
def config() -> Config:
    return Config()
