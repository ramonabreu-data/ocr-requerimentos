"""Monitora a pasta onde o scanner salva os arquivos e cria um lote por dia.

Uso: python -m ocr_requerimentos.watcher  (pasta em PASTA_MONITORADA)
Arquivos só são lidos depois que o tamanho fica estável entre duas varreduras (cópia terminada).
Depois de registrados, vão para processados/AAAA-MM-DD/; arquivos ilegíveis vão para erros/."""
from __future__ import annotations

import logging
import shutil
import time
from datetime import date, datetime, time as dtime
from pathlib import Path

from sqlalchemy import select

from .config import config
from .modelos import Lote, sessao
from .pipeline.persistencia import atualizar_lote, registrar_documento
from .worker import enfileirar

log = logging.getLogger("ocr.watcher")
EXTENSOES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif"}
IGNORAR = {"processados", "erros"}


def _lote_do_dia(s, hoje: date) -> Lote:
    nome = f"Pasta monitorada {hoje:%d/%m/%Y}"
    inicio = datetime.combine(hoje, dtime.min).astimezone()
    lote = s.scalar(
        select(Lote).where(Lote.origem == "pasta_monitorada", Lote.nome == nome, Lote.created_at >= inicio)
    )
    if lote is None:
        lote = Lote(nome=nome, origem="pasta_monitorada", status="processando")
        s.add(lote)
        s.flush()
    return lote


def _mover(arq: Path, destino: Path) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / arq.name
    n = 1
    while alvo.exists():
        alvo = destino / f"{arq.stem} ({n}){arq.suffix}"
        n += 1
    shutil.move(str(arq), alvo)
    return alvo


def varrer(pasta: Path, tamanhos: dict[str, int], hoje: date | None = None) -> list[int]:
    """Uma varredura. `tamanhos` guarda o tamanho visto na varredura anterior (estado do loop)."""
    hoje = hoje or date.today()
    prontos: list[Path] = []
    vistos = set()
    for arq in sorted(pasta.iterdir()):
        if arq.is_dir() or arq.name.startswith(".") or arq.suffix.lower() not in EXTENSOES:
            continue
        chave = str(arq)
        vistos.add(chave)
        tam = arq.stat().st_size
        if tam > 0 and tamanhos.get(chave) == tam:
            prontos.append(arq)
        tamanhos[chave] = tam
    for k in list(tamanhos):
        if k not in vistos:
            tamanhos.pop(k)
    if not prontos:
        return []

    ids: list[int] = []
    with sessao() as s:
        lote = _lote_do_dia(s, hoje)
        for arq in prontos:
            try:
                conteudo = arq.read_bytes()
                import mimetypes

                ct = mimetypes.guess_type(arq.name)[0] or "application/octet-stream"
                reg = registrar_documento(s, conteudo, arq.name, ct, lote=lote)
                s.commit()
                if not reg.duplicado:
                    ids.append(reg.documento.id)
                _mover(arq, pasta / "processados" / f"{hoje:%Y-%m-%d}")
            except Exception:  # noqa: BLE001
                log.exception("falha ao registrar %s", arq)
                s.rollback()
                _mover(arq, pasta / "erros")
            tamanhos.pop(str(arq), None)
        atualizar_lote(s, lote.id)
    enfileirar(ids)
    return ids


def main() -> None:  # pragma: no cover - loop infinito
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config()
    if not cfg.pasta_monitorada:
        raise SystemExit("defina PASTA_MONITORADA")
    pasta = Path(cfg.pasta_monitorada)
    pasta.mkdir(parents=True, exist_ok=True)
    log.info("monitorando %s a cada %ss", pasta, cfg.pasta_intervalo_s)
    tamanhos: dict[str, int] = {}
    while True:
        try:
            ids = varrer(pasta, tamanhos)
            if ids:
                log.info("%d arquivo(s) enviados para processamento", len(ids))
        except Exception:  # noqa: BLE001
            log.exception("erro na varredura")
        time.sleep(cfg.pasta_intervalo_s)


if __name__ == "__main__":
    main()
