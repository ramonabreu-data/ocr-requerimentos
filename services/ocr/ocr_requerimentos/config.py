from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco onde o schema ocr é gravado. DATABASE_URL, se definida, vale sobre as partes DESTINO_DB_*;
    # com as partes, a URL é montada aqui (senha com @ : / não precisa ser codificada).
    database_url: str = ""
    destino_db_host: str | None = None
    destino_db_porta: int = 5432
    destino_db_nome: str | None = None
    destino_db_usuario: str | None = None
    destino_db_senha: str | None = None
    destino_db_sslmode: str | None = None  # disable | prefer | require | verify-full ...
    criar_views: bool = True  # false: a migration 0006 não cria as views (banco que não aceita views)
    celery_broker_url: str = "redis://localhost:6379/2"
    celery_eager: bool = False  # executa tarefas na mesma thread (testes / desenvolvimento sem Redis)

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
    def _montar_database_url(self) -> "Config":
        if self.database_url:
            return self
        if self.destino_db_host:
            self.database_url = URL.create(
                "postgresql+psycopg", username=self.destino_db_usuario, password=self.destino_db_senha,
                host=self.destino_db_host, port=self.destino_db_porta, database=self.destino_db_nome,
                query={"sslmode": self.destino_db_sslmode} if self.destino_db_sslmode else {},
            ).render_as_string(hide_password=False)
        else:
            self.database_url = "postgresql+psycopg://ocr:ocr@localhost:5432/siga"
        return self


@lru_cache
def config() -> Config:
    return Config()
