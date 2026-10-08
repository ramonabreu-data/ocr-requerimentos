"""Tarefas Celery. Execute com: celery -A ocr_requerimentos.worker worker -Q ocr,padrao"""
from __future__ import annotations

import logging

from celery import Celery

from .config import config

log = logging.getLogger(__name__)

app = Celery("ocr_requerimentos", broker=config().celery_broker_url)
app.conf.update(
    task_always_eager=config().celery_eager,
    task_eager_propagates=False,
    task_acks_late=True,  # se o worker cair no meio, a tarefa volta para a fila
    worker_prefetch_multiplier=1,  # OCR é pesado: um documento por vez por processo
    task_default_queue="padrao",
    task_routes={"ocr.processar_documento": {"queue": "ocr"}},
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)


@app.task(name="ocr.processar_documento", bind=True, max_retries=2, default_retry_delay=30)
def processar_documento(self, documento_uuid: str) -> str:
    from .pipeline.persistencia import processar_documento as _processar
    from .repositorio import TravaOcupada

    try:
        doc = _processar(documento_uuid)
    except TravaOcupada as e:  # outro processo segurando o documento: tenta de novo mais tarde
        raise self.retry(exc=e)
    log.info("documento %s -> %s", documento_uuid, doc.status)
    return doc.status


@app.task(name="siga.publicar_documento", bind=True, max_retries=5, default_retry_delay=60)
def publicar_siga(self, documento_uuid: str) -> str:
    """Grava (ou remove) o JSON do requerimento no bucket do SIGA conforme o estado atual."""
    from .publicacao import publicar_documento

    try:
        return publicar_documento(documento_uuid)
    except Exception as e:  # noqa: BLE001 - bucket do SIGA fora do ar: tenta de novo
        raise self.retry(exc=e)


@app.task(name="siga.gerar_consolidado", bind=True, max_retries=3, default_retry_delay=120)
def gerar_consolidado(self) -> int:
    from .publicacao import gravar_consolidado

    try:
        return gravar_consolidado()
    except Exception as e:  # noqa: BLE001
        raise self.retry(exc=e)


def agendar_consolidado() -> None:
    """Regera o requerimentos.json no máximo uma vez por intervalo: a primeira mudança agenda, as
    seguintes dentro do intervalo entram na mesma geração."""
    from .repositorio import repositorio

    repo = repositorio()
    intervalo = config().siga_consolidado_intervalo_s
    if repo.r.set(repo._k("siga", "consolidado_agendado"), "1", nx=True, ex=max(intervalo, 1)):
        gerar_consolidado.apply_async(countdown=intervalo)


def enfileirar(documento_uuids: list[str]) -> None:
    for u in documento_uuids:
        processar_documento.delay(u)
