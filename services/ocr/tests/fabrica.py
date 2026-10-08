"""Gera requerimentos sintéticos no mesmo layout do PDF do SIGA e simula digitalizações ruins."""
from __future__ import annotations

import html
import io
from dataclasses import dataclass, field

import cv2
import numpy as np
import pymupdf


@dataclass
class DadosReq:
    nome: str = "Maria das Graças Sousa"
    documento: str = "52998224725"
    procedimento: str = "Regularização de Poço Tubular"
    intervencao: str = "Poço Tubular"
    municipio: str = "ALTOS"
    localidade: str = "Povoado Boa Esperança"
    latitude: str = "-5°02'41.06\""
    longitude: str = "-42°27'32.38\""
    descricao: str = "uso para irrigação de hortas"
    finalidades: list[str] = field(default_factory=lambda: ["Irrigação"])
    irrigacao: list[tuple[str, str, str]] = field(default_factory=lambda: [
        ("Aspersão por canhão hidráulico", "10", "Alface"),
        ("Aspersão por sistema autopropelido", "3", "Acerola"),
        ("Micro-aspersão", "1", "Abacaxi (solo limpo)"),
    ])
    data: str = "01/10/2026"
    # texto do formulário atual: "município de X, localidade Y latitude ..." (sem vírgula antes de latitude)
    texto_atual: bool = False


CSS = """
* { font-family: Helvetica, sans-serif; }
h1 { text-align: center; font-size: 24px; margin: 0 0 18px 0; }
p.par { font-size: 10.7px; text-align: justify; line-height: 1.25; }
h2 { font-size: 18px; margin: 14px 0 10px 0; }
h3 { font-size: 14px; margin: 14px 0 10px 0; }
table { width: 100%; border-collapse: collapse; font-size: 10.7px; }
th { font-weight: bold; padding: 4px; text-align: center; border-bottom: 1px solid #ccc; }
td { padding: 4px; text-align: center; border-bottom: 1px solid #ddd; }
.ass { text-align: center; margin: 110px auto 0 auto; width: 300px; font-size: 12px; }
.linha { display: block; width: 260px; border-top: 1px solid #000; margin: 0 auto 2px auto; }
"""


def _html(d: DadosReq) -> str:
    e = html.escape
    partes = [
        "<h1>REQUERIMENTO</h1>",
        f"<p class='par'>{e(d.nome)}, inscrito sob o CPF/CNPJ n° {e(d.documento)}, vem requerer "
        f"{e(d.procedimento)} para {e(d.intervencao)} localizado no município "
        + (f"de {e(d.municipio)}, localidade {e(d.localidade)} " if d.texto_atual
           else f"{e(d.municipio)}, localidade {e(d.localidade)}, ")
        + f"latitude {e(d.latitude)} e longitude {e(d.longitude)}.</p>",
        "<h2>Descrição dos usos da água</h2>",
        f"<p class='par'>{e(d.descricao)}</p>",
        "<h2>Finalidade(s) do Uso da Água</h2>",
    ]
    for f in d.finalidades:
        partes.append(f"<h3>{e(f)}</h3>")
        if f.lower().startswith("irriga") and d.irrigacao:
            linhas = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{e(c)}</td></tr>" for a, b, c in d.irrigacao)
            partes.append(
                "<table><tr><th>Sistema de Irrigação</th><th>Área Irrigada (ha)</th><th>Tipo de Cultura</th></tr>"
                f"{linhas}</table>"
            )
    partes.append(f"<div class='ass'><span class='linha'></span><b>{e(d.nome)}</b><br/>{e(d.data)}</div>")
    return "".join(partes)


def pdf_requerimento(*dados: DadosReq, qr_png: bytes | None = None) -> bytes:
    """Um PDF com uma página por requerimento (vários = lote escaneado num arquivo só)."""
    doc = pymupdf.open()
    for d in dados or (DadosReq(),):
        pag = doc.new_page(width=595.28, height=841.89)
        pag.insert_htmlbox(pymupdf.Rect(34, 40, 561, 800), _html(d), css=CSS)
        if qr_png:
            pag.insert_image(pymupdf.Rect(480, 740, 550, 810), stream=qr_png)
    return doc.tobytes()


def renderizar(pdf: bytes, pagina: int = 0, dpi: int = 300) -> np.ndarray:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pix = doc[pagina].get_pixmap(dpi=dpi, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


# ------------------------------------------------------------- degradações
def girar(img: np.ndarray, graus: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), graus, 1.0)
    return cv2.warpAffine(img, m, (w, h), borderValue=(255, 255, 255))


def ruido(img: np.ndarray, sigma: float = 18, semente: int = 7) -> np.ndarray:
    rng = np.random.default_rng(semente)
    n = rng.normal(0, sigma, img.shape)
    return np.clip(img.astype(np.float32) + n, 0, 255).astype(np.uint8)


def jpeg(img: np.ndarray, qualidade: int = 35) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def amarelar(img: np.ndarray) -> np.ndarray:
    """Papel amarelado + sombra lateral (iluminação desigual)."""
    h, w = img.shape[:2]
    grad = np.tile(np.linspace(0.70, 1.0, w, dtype=np.float32), (h, 1))[..., None]
    tom = np.array([0.82, 0.93, 1.0], dtype=np.float32)  # BGR: menos azul = amarelado
    return np.clip(img.astype(np.float32) * tom * grad, 0, 255).astype(np.uint8)


def foto_perspectiva(img: np.ndarray) -> np.ndarray:
    """Simula foto de celular: folha inclinada sobre mesa escura."""
    h, w = img.shape[:2]
    W, H = int(w * 1.3), int(h * 1.2)
    fundo = np.full((H, W, 3), (40, 50, 60), np.uint8)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[W * 0.12, H * 0.06], [W * 0.86, H * 0.09], [W * 0.92, H * 0.95], [W * 0.07, H * 0.92]])
    m = cv2.getPerspectiveTransform(src, dst)
    folha = cv2.warpPerspective(img, m, (W, H), borderValue=(0, 0, 0))
    mascara = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (W, H))
    fundo[mascara > 0] = folha[mascara > 0]
    return fundo


def rabisco_assinatura(img: np.ndarray, bbox_nome: tuple[float, float, float, float], cor=(170, 60, 20)) -> np.ndarray:
    """Desenha uma assinatura (curvas em tinta azul) sobre a linha acima do nome."""
    out = img.copy()
    x0, y0, x1, y1 = (int(v) for v in bbox_nome)
    alt = y1 - y0
    base_y = y0 - int(alt * 1.4)
    t = np.linspace(0, 1, 400)
    cx = (x0 + x1) / 2
    xs = cx - 260 + t * 520
    ys = base_y - 35 * np.sin(t * 18) * np.exp(-t) - 20 * np.cos(t * 7)
    pts = np.stack([xs, ys], axis=1).astype(np.int32)
    cv2.polylines(out, [pts], False, cor, 5, cv2.LINE_AA)
    cv2.line(out, (int(cx - 180), base_y + 25), (int(cx + 220), base_y - 10), cor, 4, cv2.LINE_AA)
    return out


def png(img: np.ndarray) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def jpg_bytes(img: np.ndarray, q: int = 85) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()


def pdf_de_imagens(*imgs: np.ndarray, dpi: int = 300) -> bytes:
    """PDF só-imagem, como o gerado por um scanner."""
    doc = pymupdf.open()
    for img in imgs:
        h, w = img.shape[:2]
        pag = doc.new_page(width=w * 72 / dpi, height=h * 72 / dpi)
        pag.insert_image(pag.rect, stream=jpg_bytes(img, 90))
    return doc.tobytes()


def bbox_texto_pdf(pdf: bytes, texto: str, pagina: int = 0, dpi: int = 300, ultima: bool = True):
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    rs = doc[pagina].search_for(texto)
    r = rs[-1] if ultima else rs[0]
    f = dpi / 72
    return (r.x0 * f, r.y0 * f, r.x1 * f, r.y1 * f)


def assinar_pdf_digitalmente(pdf: bytes, carimbo: tuple[float, float, float, float] | None = None) -> bytes:
    """Assina com certificado autoassinado gerado na hora (simula assinatura gov.br/ICP).

    `carimbo` (x0, y0, x1, y1 em pontos, origem no topo): como o Foxit, escreve o texto da
    assinatura no conteúdo da página e cria o campo de assinatura visível sobre ele."""
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    from pyhanko.sign.fields import SigFieldSpec, append_signature_field

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Teste Assinante:05974965361")])
    agora = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(agora - dt.timedelta(days=1))
        .not_valid_after(agora + dt.timedelta(days=30))
        .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
        .sign(chave, hashes.SHA256())
    )
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        kp, cp = os.path.join(d, "k.pem"), os.path.join(d, "c.pem")
        open(kp, "wb").write(chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption()))
        open(cp, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
        signer = signers.SimpleSigner.load(kp, cp)
        caixa = None
        if carimbo:
            doc = pymupdf.open(stream=pdf, filetype="pdf")
            pag = doc[0]
            pag.insert_textbox(
                pymupdf.Rect(*carimbo),
                "Assinado digitalmente por TESTE ASSINANTE:05974965361 ND: C=BR, O=ICP-Brasil, "
                "OU=RFB e-CPF A1 Razão: Eu sou o autor deste documento Foxit PDF Reader Versão: 2025.3.0",
                fontsize=6,
            )
            pdf = doc.tobytes()
            altura = pag.rect.height
            caixa = (int(carimbo[0]), int(altura - carimbo[3]), int(carimbo[2]), int(altura - carimbo[1]))
        w = IncrementalPdfFileWriter(io.BytesIO(pdf))
        append_signature_field(w, SigFieldSpec(sig_field_name="Assinatura1", box=caixa))
        out = io.BytesIO()
        signers.sign_pdf(w, signers.PdfSignatureMetadata(field_name="Assinatura1"), signer=signer, output=out)
        return out.getvalue()
