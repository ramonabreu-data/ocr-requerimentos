"""Transforma um arquivo (PDF ou imagem) em páginas com palavras posicionadas.

PDF com camada de texto (gerado pelo sistema ou assinado digitalmente) é lido direto, sem OCR.
PDF digitalizado e imagens passam por pré-processamento + OCR."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageSequence

from ..extracao.tipos import PaginaLida, Palavra, agrupar_linhas
from ..imagem import preprocessamento as pp
from ..imagem.assinatura import assinaturas_digitais
from ..imagem.ocr import MotorOCR
from ..imagem.qrcode import ConteudoQR, ler_qrcodes

log = logging.getLogger(__name__)

DPI = 300
TIPOS_IMAGEM = {"image/png", "image/jpeg", "image/jpg", "image/tiff", "image/webp", "image/bmp", "image/heic", "image/heif"}


class ArquivoInvalido(Exception):
    pass


@dataclass
class LeituraArquivo:
    tipo_entrada: str  # pdf_texto | pdf_imagem | imagem
    paginas: list[PaginaLida]
    qrcodes: list[ConteudoQR] = field(default_factory=list)
    assinaturas_digitais: list[dict[str, Any]] = field(default_factory=list)

    @property
    def metodo(self) -> str:
        metodos = {p.metodo for p in self.paginas}
        return "texto_nativo" if metodos == {"texto_nativo"} else "ocr"


def detectar_tipo(conteudo: bytes, nome: str = "", content_type: str | None = None) -> str:
    if conteudo[:5] == b"%PDF-":
        return "pdf"
    try:
        with Image.open(io.BytesIO(conteudo)) as im:
            im.verify()
        return "imagem"
    except Exception:
        pass
    if nome.lower().endswith((".heic", ".heif")):
        return "imagem"
    raise ArquivoInvalido(f"formato não suportado: {content_type or nome or 'desconhecido'}")


def _pagina_tem_texto_util(pagina: pymupdf.Page) -> bool:
    palavras = pagina.get_text("words")
    letras = sum(sum(c.isalpha() for c in w[4]) for w in palavras)
    return len(palavras) >= 15 and letras >= 60


def _pagina_e_digitalizacao(pagina: pymupdf.Page) -> bool:
    """Imagem cobrindo a página inteira: texto existente provavelmente é OCR do scanner."""
    area = pagina.rect.width * pagina.rect.height
    for info in pagina.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        if (x1 - x0) * (y1 - y0) > 0.8 * area:
            return True
    return False


def _pixmap_para_bgr(pix: pymupdf.Pixmap) -> np.ndarray:
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    if pix.n == 1:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _ler_pagina_nativa(pagina: pymupdf.Page, numero: int) -> PaginaLida:
    escala = DPI / 72
    pix = pagina.get_pixmap(dpi=DPI, alpha=False)
    # carimbo visível da assinatura digital ("Assinado digitalmente por ...", certificado, leitor de PDF)
    # não faz parte do formulário: misturado ao texto, vira linha de tabela ou rodapé
    carimbos = [w.rect for w in pagina.widgets() if w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE]
    palavras = [
        Palavra(w[4], 100.0, (w[0] * escala, w[1] * escala, w[2] * escala, w[3] * escala), numero)
        for w in pagina.get_text("words")
        if not any(r.contains(pymupdf.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)) for r in carimbos)
    ]
    return PaginaLida(numero, pix.width, pix.height, agrupar_linhas(palavras), "texto_nativo", _pixmap_para_bgr(pix))


def ocr_imagem(img: np.ndarray, numero: int, motor: MotorOCR, remover_azul: bool = True) -> PaginaLida:
    prep = pp.preparar(img, remover_azul=remover_azul)
    palavras = motor.reconhecer(prep.ocr, numero)
    h, w = prep.exibicao.shape[:2]
    return PaginaLida(
        numero, w, h, agrupar_linhas(palavras), "ocr", prep.exibicao,
        angulo_correcao=prep.angulo + prep.rotacao, motor=motor.nome,
    )


def decodificar_imagens(conteudo: bytes, nome: str = "") -> list[np.ndarray]:
    if nome.lower().endswith((".heic", ".heif")):
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except ImportError as e:  # pragma: no cover
            raise ArquivoInvalido("HEIC requer o pacote pillow-heif") from e
    imagens = []
    with Image.open(io.BytesIO(conteudo)) as im:
        for quadro in ImageSequence.Iterator(im):  # TIFF multipágina
            rgb = quadro.convert("RGB")
            imagens.append(cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR))
    return imagens


def ler_arquivo(
    conteudo: bytes,
    motor: MotorOCR,
    nome: str = "",
    content_type: str | None = None,
    *,
    confiar_texto_scanner: bool = False,
    remover_azul: bool = True,
    ler_qr: bool = True,
) -> LeituraArquivo:
    tipo = detectar_tipo(conteudo, nome, content_type)
    paginas: list[PaginaLida] = []
    digitais: list[dict[str, Any]] = []

    if tipo == "pdf":
        try:
            doc = pymupdf.open(stream=conteudo, filetype="pdf")
        except Exception as e:
            raise ArquivoInvalido(f"PDF corrompido ou protegido: {e}") from e
        if doc.needs_pass:
            raise ArquivoInvalido("PDF protegido por senha")
        if doc.page_count == 0:
            raise ArquivoInvalido("PDF sem páginas")
        digitais = assinaturas_digitais(conteudo)
        nativas = 0
        escaneadas = [_pagina_e_digitalizacao(p) for p in doc]
        uteis = [_pagina_tem_texto_util(p) for p in doc]
        # PDF gerado pelo sistema: a última página pode ter só o nome e a data, pouco texto mas legítimo
        pdf_de_texto = any(u and not e for u, e in zip(uteis, escaneadas))
        for i, pag in enumerate(doc, start=1):
            escaneada = escaneadas[i - 1]
            tem_texto = uteis[i - 1] or (pdf_de_texto and not escaneada and bool(pag.get_text("words")))
            usar_texto = tem_texto and (confiar_texto_scanner or not escaneada)
            if usar_texto:
                paginas.append(_ler_pagina_nativa(pag, i))
                nativas += 1
            else:
                img = _pixmap_para_bgr(pag.get_pixmap(dpi=DPI, alpha=False))
                paginas.append(ocr_imagem(img, i, motor, remover_azul))
        tipo_entrada = "pdf_texto" if nativas == doc.page_count else "pdf_imagem"
    else:
        imagens = decodificar_imagens(conteudo, nome)
        for i, img in enumerate(imagens, start=1):
            paginas.append(ocr_imagem(img, i, motor, remover_azul))
        tipo_entrada = "imagem"

    qrs: list[ConteudoQR] = []
    if ler_qr:
        for p in paginas:
            if p.imagem is not None:
                qrs.extend(ler_qrcodes(p.imagem))
    return LeituraArquivo(tipo_entrada, paginas, qrs, digitais)
