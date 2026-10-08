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
def processar_documento(self, documento_id: int) -> str:
    from .modelos import sessao
    from .pipeline.persistencia import processar_documento as _processar

    with sessao() as s:
        doc = _processar(s, documento_id)
        log.info("documento %s -> %s", documento_id, doc.status)
        return doc.status


def enfileirar(documento_ids: list[int]) -> None:
    for i in documento_ids:
        processar_documento.delay(i)
