"""Motores de OCR. Todos devolvem `Palavra`s com caixa e confiança na geometria da imagem recebida."""
from __future__ import annotations

import functools
import logging
from typing import Protocol

import numpy as np

from ..extracao.tipos import Palavra

log = logging.getLogger(__name__)


class MotorOCR(Protocol):
    nome: str

    def reconhecer(self, imagem: np.ndarray, pagina: int = 1) -> list[Palavra]: ...


class TesseractOCR:
    nome = "tesseract"

    def __init__(self, idioma: str = "por", psm: int = 4, dpi: int = 300):
        self.idioma = idioma
        self.config = f"--oem 1 --psm {psm} -c user_defined_dpi={dpi} -c preserve_interword_spaces=1"

    def reconhecer(self, imagem: np.ndarray, pagina: int = 1) -> list[Palavra]:
        import pytesseract

        dados = pytesseract.image_to_data(
            imagem, lang=self.idioma, config=self.config, output_type=pytesseract.Output.DICT
        )
        palavras: list[Palavra] = []
        for i, txt in enumerate(dados["text"]):
            txt = (txt or "").strip()
            conf = float(dados["conf"][i])
            if not txt or conf < 0:
                continue
            x, y, w, h = dados["left"][i], dados["top"][i], dados["width"][i], dados["height"][i]
            palavras.append(Palavra(txt, conf, (float(x), float(y), float(x + w), float(y + h)), pagina))
        return palavras


class PaddleOCR:
    """Motor opcional (melhor em tabelas e fotos). Requer `pip install paddleocr paddlepaddle`.

    O PaddleOCR devolve linhas; aqui cada linha é quebrada em palavras com caixas proporcionais."""

    nome = "paddle"

    def __init__(self, idioma: str = "pt"):
        self.idioma = idioma

    @functools.cached_property
    def _modelo(self):
        from paddleocr import PaddleOCR as _P  # import tardio: dependência pesada

        return _P(use_angle_cls=False, lang=self.idioma, show_log=False)

    def reconhecer(self, imagem: np.ndarray, pagina: int = 1) -> list[Palavra]:
        resultado = self._modelo.ocr(imagem, cls=False) or []
        palavras: list[Palavra] = []
        for bloco in resultado:
            for caixa, (texto, conf) in bloco or []:
                xs = [p[0] for p in caixa]
                ys = [p[1] for p in caixa]
                x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
                partes = texto.split()
                total = sum(len(p) for p in partes) + max(len(partes) - 1, 0)
                cursor = x0
                for parte in partes:
                    largura = (x1 - x0) * len(parte) / max(total, 1)
                    palavras.append(Palavra(parte, float(conf) * 100, (cursor, y0, cursor + largura, y1), pagina))
                    cursor += largura + (x1 - x0) / max(total, 1)
        return palavras


def criar_motor(nome: str, idioma_tesseract: str = "por") -> MotorOCR:
    if nome == "paddle":
        return PaddleOCR()
    return TesseractOCR(idioma=idioma_tesseract)
