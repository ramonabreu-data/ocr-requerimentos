# Imagem única para api, worker e watcher (muda só o comando).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    OMP_THREAD_LIMIT=1
# OMP_THREAD_LIMIT=1: o Tesseract roda 1 thread por processo; a escala vem de mais workers.

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-por tesseract-ocr-osd \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-paddle.txt ./
RUN pip install -r requirements.txt

ARG COM_PADDLE=0
RUN if [ "$COM_PADDLE" = "1" ]; then pip install -r requirements-paddle.txt \
      && python -c "from paddleocr import PaddleOCR; PaddleOCR(lang='pt', show_log=False)"; fi

COPY ocr_requerimentos ./ocr_requerimentos
COPY migrations ./migrations
COPY alembic.ini pyproject.toml ./

RUN useradd --create-home --uid 10001 ocr && mkdir -p /data/ocr /data/entrada && chown -R ocr /data
USER ocr

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fs http://localhost:8000/saude || exit 1
CMD ["uvicorn", "ocr_requerimentos.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

# ---- testes: docker build --target testes -t ocr-testes . && docker run --rm ocr-testes
FROM base AS testes
USER root
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests
USER ocr
CMD ["python", "-m", "pytest", "-q"]
