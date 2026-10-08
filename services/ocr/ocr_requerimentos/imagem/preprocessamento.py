"""Pré-processamento de páginas digitalizadas ou fotografadas antes do OCR.

Ordem: perspectiva (fotos) -> escala (300 dpi) -> orientação 90/180/270 -> inclinação fina ->
imagem para OCR (remove tinta azul, nivela iluminação, binariza).
A mesma geometria é aplicada à imagem colorida exibida na revisão, para as caixas coincidirem."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)

LARGURA_PADRAO = 2480  # A4 em 300 dpi


@dataclass
class PaginaPreparada:
    exibicao: np.ndarray  # BGR, geometria final
    ocr: np.ndarray  # tons de cinza/binária, mesma geometria
    angulo: float
    rotacao: int
    perspectiva: bool


def cinza(img: np.ndarray, remover_azul: bool = True) -> np.ndarray:
    if img.ndim == 2:
        return img
    if remover_azul:
        # no canal azul, tinta azul (assinaturas, rubricas) fica clara e o texto preto continua escuro
        return img[:, :, 0].copy()
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def corrigir_perspectiva(img: np.ndarray) -> tuple[np.ndarray, bool]:
    """Detecta a folha em fotos (papel claro sobre fundo mais escuro) e retifica."""
    h, w = img.shape[:2]
    escala = 1000 / max(h, w)
    peq = cv2.resize(img, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    g = cv2.GaussianBlur(cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contornos, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return img, False
    c = max(contornos, key=cv2.contourArea)
    area = cv2.contourArea(c) / (peq.shape[0] * peq.shape[1])
    if area < 0.25 or area > 0.97:
        return img, False  # folha ocupa a imagem inteira (scanner) ou nada encontrado
    aprox = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(aprox) != 4:
        return img, False
    pts = (aprox.reshape(4, 2) / escala).astype(np.float32)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    tl, br, tr, bl = pts[np.argmin(s)], pts[np.argmax(s)], pts[np.argmin(d)], pts[np.argmax(d)]
    larg = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    alt = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if larg < 200 or alt < 200:
        return img, False
    m = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]), np.float32([[0, 0], [larg, 0], [larg, alt], [0, alt]]))
    return cv2.warpPerspective(img, m, (larg, alt), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)), True


def padronizar_escala(img: np.ndarray, largura: int = LARGURA_PADRAO) -> np.ndarray:
    h, w = img.shape[:2]
    if abs(w - largura) < 10:
        return img
    f = largura / w
    return cv2.resize(img, (largura, int(round(h * f))), interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)


def rotacionar_90(img: np.ndarray, graus: int) -> np.ndarray:
    return {
        0: img,
        90: cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE),
        180: cv2.rotate(img, cv2.ROTATE_180),
        270: cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE),
    }[graus % 360]


def detectar_orientacao(g: np.ndarray) -> int:
    """Rotação (horária) necessária para deixar o texto em pé, via Tesseract OSD."""
    try:
        import pytesseract

        peq = padronizar_escala(g, 1240)
        osd = pytesseract.image_to_osd(peq, config="--psm 0 -c min_characters_to_try=20",
                                       output_type=pytesseract.Output.DICT)
        rot = int(osd.get("rotate", 0)) % 360
        if float(osd.get("orientation_conf", 0)) < 1.5:
            return 0
        return rot
    except Exception as e:  # pouco texto, OSD indisponível etc.
        log.debug("OSD falhou: %s", e)
        return 0


def estimar_inclinacao(g: np.ndarray, limite: float = 8.0) -> float:
    """Ângulo (graus) que maximiza a nitidez do perfil horizontal de projeção."""
    peq = padronizar_escala(g, 1000)
    _, bw = cv2.threshold(peq, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = bw.shape
    centro = (w / 2, h / 2)

    def nota(ang: float) -> float:
        m = cv2.getRotationMatrix2D(centro, ang, 1.0)
        rot = cv2.warpAffine(bw, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        perfil = rot.sum(axis=1, dtype=np.float64)
        return float(np.sum(np.diff(perfil) ** 2))

    melhor = max(np.arange(-limite, limite + 0.01, 0.5), key=nota)
    fino = max(np.arange(melhor - 0.5, melhor + 0.51, 0.1), key=nota)
    return float(round(fino, 2))


def girar(img: np.ndarray, ang: float) -> np.ndarray:
    if abs(ang) < 0.05:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    borda = 255 if img.ndim == 2 else (255, 255, 255)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=borda)


def preparar_para_ocr(g: np.ndarray) -> np.ndarray:
    """Nivela iluminação (sombra de foto, fundo amarelado) e binariza."""
    fundo = cv2.morphologyEx(g, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (41, 41)))
    nivelado = cv2.divide(g, fundo, scale=255)
    nivelado = cv2.medianBlur(nivelado, 3)
    _, bw = cv2.threshold(nivelado, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw


def preparar(img: np.ndarray, *, remover_azul: bool = True, corrigir_orientacao: bool = True) -> PaginaPreparada:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img, persp = corrigir_perspectiva(img)
    rot = 0
    if corrigir_orientacao:
        rot = detectar_orientacao(cinza(img, remover_azul))
        img = rotacionar_90(img, rot)
    img = padronizar_escala(img)
    ang = estimar_inclinacao(cinza(img, remover_azul))
    img = girar(img, ang)
    return PaginaPreparada(img, preparar_para_ocr(cinza(img, remover_azul)), ang, rot, persp)
