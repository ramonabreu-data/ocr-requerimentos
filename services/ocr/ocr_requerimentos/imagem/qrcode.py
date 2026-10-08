"""QR code de identificação do requerimento.

Conteúdo recomendado (gerado pelo SIGA ao emitir o PDF):
    SIGA-REQ|v1|<uuid do processo>|<sha256 dos dados, 16 primeiros caracteres>
Também é aceita uma URL contendo o uuid do processo."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

import numpy as np

RE_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
PREFIXO = "SIGA-REQ"


@dataclass
class ConteudoQR:
    bruto: str
    processo_uuid: str | None
    hash_dados: str | None


def interpretar(texto: str) -> ConteudoQR:
    partes = texto.strip().split("|")
    if partes[0] == PREFIXO and len(partes) >= 3:
        return ConteudoQR(texto, partes[2].lower(), partes[3] if len(partes) > 3 else None)
    m = RE_UUID.search(texto)
    return ConteudoQR(texto, m.group(0).lower() if m else None, None)


def ler_qrcodes(imagem: np.ndarray) -> list[ConteudoQR]:
    try:
        import zxingcpp
    except ImportError:  # pragma: no cover
        return []
    achados = []
    for r in zxingcpp.read_barcodes(imagem):
        if r.format == zxingcpp.BarcodeFormat.QRCode and r.text:
            achados.append(interpretar(r.text))
    return achados


def conteudo_padrao(processo_uuid: str, hash_dados: str | None = None) -> str:
    return "|".join([PREFIXO, "v1", processo_uuid, *( [hash_dados[:16]] if hash_dados else [])])


def gerar_png(processo_uuid: str, hash_dados: str | None = None, caixa: int = 6) -> bytes:
    """PNG do QR para o gerador de PDF do SIGA embutir no rodapé (mín. 2 cm impresso)."""
    import qrcode

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=caixa, border=4)
    qr.add_data(conteudo_padrao(processo_uuid, hash_dados))
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()
