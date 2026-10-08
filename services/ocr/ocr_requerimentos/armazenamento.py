"""Armazenamento de arquivos originais, imagens de página e dos JSONs de dados: disco local ou S3/MinIO."""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from .config import config


class Armazenamento(Protocol):
    def salvar(self, chave: str, conteudo: bytes, content_type: str = "application/octet-stream") -> None: ...
    def ler(self, chave: str) -> bytes: ...
    def existe(self, chave: str) -> bool: ...
    def remover(self, chave: str) -> None: ...
    def listar(self, prefixo: str) -> Iterator[str]: ...
    def salvar_arquivo(self, chave: str, caminho: str, content_type: str = "application/octet-stream") -> None: ...


class ArmazenamentoLocal:
    def __init__(self, raiz: str):
        self.raiz = Path(raiz)
        self.raiz.mkdir(parents=True, exist_ok=True)

    def _caminho(self, chave: str) -> Path:
        p = (self.raiz / chave).resolve()
        if self.raiz.resolve() not in p.parents:
            raise ValueError("chave de armazenamento inválida")
        return p

    def salvar(self, chave: str, conteudo: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._caminho(chave)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(conteudo)
        tmp.replace(p)

    def salvar_arquivo(self, chave: str, caminho: str, content_type: str = "application/octet-stream") -> None:
        import shutil

        p = self._caminho(chave)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        shutil.copyfile(caminho, tmp)
        tmp.replace(p)

    def ler(self, chave: str) -> bytes:
        return self._caminho(chave).read_bytes()

    def existe(self, chave: str) -> bool:
        return self._caminho(chave).exists()

    def remover(self, chave: str) -> None:
        self._caminho(chave).unlink(missing_ok=True)

    def listar(self, prefixo: str) -> Iterator[str]:
        base = self._caminho(prefixo) if prefixo else self.raiz
        if not base.is_dir():
            return
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.name.endswith(".tmp"):
                yield p.relative_to(self.raiz).as_posix()


class ArmazenamentoS3:
    def __init__(self, bucket: str | None = None, endpoint: str | None = None, access_key: str | None = None,
                 secret_key: str | None = None):
        import boto3

        c = config()
        self.bucket = bucket or c.s3_bucket
        self.cliente = boto3.client(
            "s3",
            endpoint_url=endpoint or c.s3_endpoint,
            aws_access_key_id=access_key or c.s3_access_key,
            aws_secret_access_key=secret_key or c.s3_secret_key,
            region_name=c.s3_region,
        )
        try:
            self.cliente.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self.cliente.create_bucket(Bucket=self.bucket)
            except Exception:  # noqa: BLE001 - sem permissão de criar (bucket de outro sistema): o envio dirá
                pass

    def salvar(self, chave: str, conteudo: bytes, content_type: str = "application/octet-stream") -> None:
        self.cliente.put_object(Bucket=self.bucket, Key=chave, Body=conteudo, ContentType=content_type)

    def salvar_arquivo(self, chave: str, caminho: str, content_type: str = "application/octet-stream") -> None:
        """Envio em partes (multipart): serve para arquivos grandes, como o consolidado."""
        self.cliente.upload_file(caminho, self.bucket, chave, ExtraArgs={"ContentType": content_type})

    def ler(self, chave: str) -> bytes:
        try:
            return self.cliente.get_object(Bucket=self.bucket, Key=chave)["Body"].read()
        except self.cliente.exceptions.NoSuchKey:
            raise FileNotFoundError(chave) from None

    def existe(self, chave: str) -> bool:
        try:
            self.cliente.head_object(Bucket=self.bucket, Key=chave)
            return True
        except Exception:
            return False

    def remover(self, chave: str) -> None:
        self.cliente.delete_object(Bucket=self.bucket, Key=chave)

    def listar(self, prefixo: str) -> Iterator[str]:
        for pagina in self.cliente.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefixo):
            for obj in pagina.get("Contents", []):
                yield obj["Key"]


@lru_cache
def armazenamento() -> Armazenamento:
    if config().storage_backend == "s3":
        return ArmazenamentoS3()
    return ArmazenamentoLocal(config().storage_dir)
