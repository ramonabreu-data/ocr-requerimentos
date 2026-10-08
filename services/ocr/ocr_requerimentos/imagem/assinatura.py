"""Detecção de assinatura: digital (PDF assinado, ICP-Brasil/gov.br) ou manuscrita (tinta na área
reservada acima do nome do assinante)."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from ..extracao.tipos import BBox

log = logging.getLogger(__name__)


@dataclass
class ResultadoAssinatura:
    tipo: str  # digital | manuscrita | ausente | indeterminada
    detalhes: dict[str, Any] = field(default_factory=dict)


def assinaturas_digitais(conteudo_pdf: bytes) -> list[dict[str, Any]]:
    """Lista assinaturas embutidas no PDF. Integridade é verificada; confiança na cadeia (raiz
    ICP-Brasil) só é avaliada se as raízes forem configuradas — aqui fica registrada como 'não verificada'."""
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except ImportError:  # pragma: no cover
        return []
    saida: list[dict[str, Any]] = []
    try:
        leitor = PdfFileReader(io.BytesIO(conteudo_pdf), strict=False)
        for sig in leitor.embedded_signatures:
            info: dict[str, Any] = {"campo": sig.field_name}
            try:
                cert = sig.signer_cert
                info["assinante"] = cert.subject.human_friendly
                info["emissor"] = cert.issuer.human_friendly
            except Exception:  # noqa: BLE001
                pass
            try:
                st = validate_pdf_signature(sig, ValidationContext(allow_fetching=False))
                info["integra"] = bool(st.intact and st.valid)
                info["cadeia_confiavel"] = bool(st.trusted)
                info["cobre_documento_inteiro"] = str(st.coverage)
                if st.signer_reported_dt:
                    info["data_assinatura"] = st.signer_reported_dt.isoformat()
            except Exception as e:  # noqa: BLE001
                info["erro_validacao"] = str(e)
            saida.append(info)
    except Exception as e:  # noqa: BLE001
        log.debug("PDF sem assinaturas legíveis: %s", e)
    return saida


def detectar_manuscrita(imagem_bgr: np.ndarray, bbox_nome: BBox | None, limiar: float = 0.006) -> ResultadoAssinatura:
    """Procura traços de tinta na faixa acima do nome impresso do assinante."""
    if imagem_bgr is None or bbox_nome is None:
        return ResultadoAssinatura("indeterminada", {"motivo": "nome do assinante não localizado"})
    h_img, w_img = imagem_bgr.shape[:2]
    x0, y0, x1, y1 = bbox_nome
    alt = max(y1 - y0, 10)
    larg = max(x1 - x0, 10)
    cx = (x0 + x1) / 2
    meia = max(larg * 2.2, w_img * 0.18)
    rx0, rx1 = int(max(cx - meia, 0)), int(min(cx + meia, w_img))
    ry0, ry1 = int(max(y0 - alt * 6, 0)), int(max(y0 - alt * 0.15, 0))
    if ry1 - ry0 < 5 or rx1 - rx0 < 5:
        return ResultadoAssinatura("indeterminada", {"motivo": "área de assinatura fora da página"})

    regiao = imagem_bgr[ry0:ry1, rx0:rx1]
    hsv = cv2.cvtColor(regiao, cv2.COLOR_BGR2HSV)
    cinza = cv2.cvtColor(regiao, cv2.COLOR_BGR2GRAY)
    escuro = cinza < 140
    colorido = (hsv[:, :, 1] > 70) & (hsv[:, :, 2] < 235)
    tinta = ((escuro | colorido) * 255).astype(np.uint8)

    # remove a linha de assinatura impressa (traço horizontal longo)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(int((rx1 - rx0) * 0.25), 15), 1))
    linhas = cv2.morphologyEx(tinta, cv2.MORPH_OPEN, k)
    linhas = cv2.dilate(linhas, np.ones((5, 1), np.uint8))
    tinta = cv2.subtract(tinta, linhas)
    tinta = cv2.morphologyEx(tinta, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    proporcao = float(np.count_nonzero(tinta)) / tinta.size
    n, _, stats, _ = cv2.connectedComponentsWithStats(tinta)
    componentes = int(sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 30))
    detalhes = {
        "proporcao_tinta": round(proporcao, 5),
        "componentes": componentes,
        "regiao": [rx0, ry0, rx1, ry1],
    }
    if proporcao >= limiar and componentes >= 1:
        return ResultadoAssinatura("manuscrita", detalhes)
    return ResultadoAssinatura("ausente", detalhes)
