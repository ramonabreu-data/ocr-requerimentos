"""Executa o pipeline completo sobre um arquivo, sem depender do banco.

arquivo -> páginas (texto nativo/OCR) -> divisão por requerimento -> parser -> segunda leitura
dos campos numéricos -> validação -> assinatura -> QR."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..extracao.normalizadores import corrigir_digitos
from ..extracao.parser import RE_TITULO, ExtracaoBruta, extrair
from ..extracao.texto import normalizar_paralelo
from ..extracao.tipos import CampoBruto, PaginaLida, uniao_bbox
from ..extracao.validacao import Referencias, Resultado, validar
from ..imagem import preprocessamento as pp
from ..imagem.assinatura import ResultadoAssinatura, detectar_manuscrita
from ..imagem.ocr import MotorOCR
from ..imagem.qrcode import ConteudoQR
from .leitura import LeituraArquivo, ler_arquivo

log = logging.getLogger(__name__)


@dataclass
class Segmento:
    paginas: list[PaginaLida]
    extracao: ExtracaoBruta
    resultado: Resultado
    assinatura: ResultadoAssinatura
    qrcodes: list[ConteudoQR] = field(default_factory=list)

    @property
    def pagina_inicial(self) -> int:
        return self.paginas[0].numero


@dataclass
class ResultadoArquivo:
    leitura: LeituraArquivo
    segmentos: list[Segmento]


def dividir_por_requerimento(paginas: list[PaginaLida]) -> list[list[PaginaLida]]:
    """Cada página cujo topo contém o título REQUERIMENTO inicia um novo requerimento."""
    grupos: list[list[PaginaLida]] = []
    for p in paginas:
        topo = " ".join(l.texto for l in p.linhas[:3])
        inicia = bool(RE_TITULO.search(normalizar_paralelo(topo)))
        if inicia or not grupos:
            grupos.append([p])
        else:
            grupos[-1].append(p)
    return grupos


def _digitos(s: str | None) -> str:
    return re.sub(r"\D", "", corrigir_digitos(s or ""))


def conferir_campo_numerico(campo: CampoBruto, paginas: dict[int, PaginaLida], remover_azul: bool = True) -> None:
    """Segunda leitura do recorte em tons de cinza (psm 8). Leituras iguais elevam a confiança;
    divergentes rebaixam e registram as duas versões para o revisor."""
    if not campo.valor or not campo.palavras or campo.bbox is None:
        return
    pag = paginas.get(campo.pagina or 1)
    if pag is None or pag.metodo != "ocr" or pag.imagem is None:
        return
    import pytesseract

    # só as palavras com dígitos: a coordenada pode quebrar a linha depois do sinal ("latitude -" / "7°4'...")
    # e o recorte das duas linhas pegaria texto que atrapalha a segunda leitura
    com_digito = [p for p in campo.palavras if any(c.isdigit() for c in p.texto) and p.pagina == campo.pagina]
    x0, y0, x1, y1 = (int(v) for v in (uniao_bbox([p.bbox for p in com_digito]) if com_digito else campo.bbox))
    pad = 12
    g = pp.cinza(pag.imagem, remover_azul)
    recorte = g[max(y0 - pad, 0): y1 + pad, max(x0 - pad, 0): x1 + pad]
    if recorte.size == 0:
        return
    try:
        segunda = pytesseract.image_to_string(recorte, lang="por", config="--oem 1 --psm 8").strip()
        if len(_digitos(segunda)) < max(1, len(_digitos(campo.valor)) // 2):
            segunda = pytesseract.image_to_string(recorte, lang="por", config="--oem 1 --psm 7").strip()
    except Exception as e:  # noqa: BLE001
        log.debug("segunda leitura falhou: %s", e)
        return
    if _digitos(segunda) == _digitos(campo.valor):
        campo.conf_fixa = max(campo.confianca, 92.0)
    else:
        campo.conf_fixa = min(campo.confianca, 50.0)
        campo.nota = f"segunda leitura divergente: '{segunda}'"


def _conferir(ex: ExtracaoBruta, paginas: list[PaginaLida], remover_azul: bool) -> None:
    por_numero = {p.numero: p for p in paginas}
    alvos = [ex.cpf_cnpj, ex.latitude, ex.longitude, ex.data_documento] + [li.area for li in ex.irrigacao]
    for b in ex.blocos:  # números dos detalhes das finalidades (cabeças, habitantes, áreas...)
        if b.definicao is None or b.chave == "irrigacao":
            continue
        numericos = {c.chave for c in (*b.definicao.campos, *b.definicao.colunas) if c.tipo in ("numero", "inteiro", "data")}
        alvos += [v for k, v in b.valores.items() if k in numericos]
        alvos += [v for ln in b.linhas for k, v in ln.items() if k in numericos]
    for c in alvos:
        conferir_campo_numerico(c, por_numero, remover_azul)


def _assinatura(leitura: LeituraArquivo, ex: ExtracaoBruta, paginas: list[PaginaLida]) -> ResultadoAssinatura:
    if leitura.assinaturas_digitais:
        return ResultadoAssinatura("digital", {"assinaturas": leitura.assinaturas_digitais})
    if ex.linha_assinante is None:
        return ResultadoAssinatura("indeterminada", {"motivo": "nome do assinante não localizado"})
    pag = next((p for p in paginas if p.numero == ex.linha_assinante.pagina), None)
    img = pag.imagem if pag is not None else None
    if img is None:
        return ResultadoAssinatura("indeterminada", {"motivo": "imagem da página indisponível"})
    return detectar_manuscrita(img, ex.linha_assinante.bbox)


def processar_paginas(
    leitura: LeituraArquivo,
    paginas: list[PaginaLida],
    refs: Referencias,
    *,
    limiar: float = 80.0,
    conferir_numeros: bool = True,
    remover_azul: bool = True,
) -> Segmento:
    linhas = [ln for p in paginas for ln in p.linhas]
    try:
        titulos = [f.nome for f in refs.finalidades]
    except Exception:  # noqa: BLE001 - referências indisponíveis não impedem a leitura
        titulos = []
    ex = extrair(linhas, titulos_extra=titulos)
    if conferir_numeros:
        _conferir(ex, paginas, remover_azul)
    resultado = validar(ex, refs, limiar)
    assinatura = _assinatura(leitura, ex, paginas)
    numeros = {p.numero for p in paginas}
    qrs = [q for q in leitura.qrcodes]  # QR é por arquivo; na divisão, cada segmento herda os seus abaixo
    if len(numeros) < len(leitura.paginas):
        qrs = []
        for p in paginas:
            from ..imagem.qrcode import ler_qrcodes

            if p.imagem is not None:
                qrs.extend(ler_qrcodes(p.imagem))
    return Segmento(paginas, ex, resultado, assinatura, qrs)


def processar_arquivo(
    conteudo: bytes,
    motor: MotorOCR,
    refs: Referencias,
    nome: str = "",
    content_type: str | None = None,
    *,
    limiar: float = 80.0,
    conferir_numeros: bool = True,
    remover_azul: bool = True,
    confiar_texto_scanner: bool = False,
    dividir: bool = True,
) -> ResultadoArquivo:
    leitura = ler_arquivo(
        conteudo, motor, nome, content_type,
        confiar_texto_scanner=confiar_texto_scanner, remover_azul=remover_azul,
    )
    grupos = dividir_por_requerimento(leitura.paginas) if dividir else [leitura.paginas]
    segmentos = [
        processar_paginas(leitura, g, refs, limiar=limiar, conferir_numeros=conferir_numeros, remover_azul=remover_azul)
        for g in grupos
    ]
    return ResultadoArquivo(leitura, segmentos)


def palavras_json(pagina: PaginaLida) -> list[dict[str, Any]]:
    return [
        {"t": p.texto, "c": round(p.conf, 1), "b": [round(v, 1) for v in p.bbox]}
        for p in pagina.palavras
    ]


def imagem_jpeg(img: np.ndarray, qualidade: int = 80) -> bytes:
    import cv2

    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, qualidade])[1].tobytes()
