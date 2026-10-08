"""Estruturas de dados compartilhadas entre leitura (texto nativo / OCR), parser e validação."""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1 em pixels da imagem da página


@dataclass
class Palavra:
    texto: str
    conf: float  # 0–100 (texto nativo = 100)
    bbox: BBox
    pagina: int = 1

    @property
    def altura(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def centro_y(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2


@dataclass
class Linha:
    palavras: list[Palavra]

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palavras)

    @property
    def pagina(self) -> int:
        return self.palavras[0].pagina if self.palavras else 1

    @property
    def bbox(self) -> BBox:
        return uniao_bbox([p.bbox for p in self.palavras])

    @property
    def altura_mediana(self) -> float:
        return median(p.altura for p in self.palavras) if self.palavras else 0.0

    def celulas(self, fator_espaco: float = 1.6) -> list["Linha"]:
        """Divide a linha em células quando o espaço entre palavras é muito maior que o normal.

        Usado na tabela de irrigação: colunas ficam separadas por espaços largos."""
        if not self.palavras:
            return []
        limite = max(self.altura_mediana * fator_espaco, 1.0)
        grupos: list[list[Palavra]] = [[self.palavras[0]]]
        for anterior, atual in zip(self.palavras, self.palavras[1:]):
            if atual.bbox[0] - anterior.bbox[2] > limite:
                grupos.append([atual])
            else:
                grupos[-1].append(atual)
        return [Linha(g) for g in grupos]


@dataclass
class PaginaLida:
    numero: int
    largura: int
    altura: int
    linhas: list[Linha]
    metodo: str  # texto_nativo | ocr
    imagem: Any = None  # np.ndarray BGR (imagem já corrigida, usada na revisão)
    angulo_correcao: float = 0.0
    motor: str | None = None

    @property
    def palavras(self) -> list[Palavra]:
        return [p for linha in self.linhas for p in linha.palavras]

    @property
    def texto(self) -> str:
        return "\n".join(linha.texto for linha in self.linhas)

    @property
    def confianca_media(self) -> float:
        ps = self.palavras
        return round(sum(p.conf for p in ps) / len(ps), 2) if ps else 0.0


@dataclass
class CampoBruto:
    """Trecho localizado pelo parser, antes de normalizar/validar.

    `conf_fixa`, `pagina_fixa` e `bbox_fixa` são usados quando o valor vem de uma correção
    manual (sem palavras de OCR associadas)."""

    valor: str | None
    palavras: list[Palavra] = field(default_factory=list)
    conf_fixa: float | None = None
    pagina_fixa: int | None = None
    bbox_fixa: BBox | None = None
    nota: str | None = None  # observação da leitura (ex.: segunda leitura divergente)

    @property
    def confianca(self) -> float:
        if self.conf_fixa is not None:
            return self.conf_fixa
        if not self.palavras:
            return 0.0
        return round(sum(p.conf for p in self.palavras) / len(self.palavras), 2)

    @property
    def pagina(self) -> int | None:
        if self.pagina_fixa is not None:
            return self.pagina_fixa
        return self.palavras[0].pagina if self.palavras else None

    @property
    def bbox(self) -> BBox | None:
        if self.bbox_fixa is not None:
            return self.bbox_fixa
        if not self.palavras:
            return None
        pag = self.palavras[0].pagina
        return uniao_bbox([p.bbox for p in self.palavras if p.pagina == pag])


def uniao_bbox(caixas: list[BBox]) -> BBox:
    if not caixas:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(c[0] for c in caixas),
        min(c[1] for c in caixas),
        max(c[2] for c in caixas),
        max(c[3] for c in caixas),
    )


def agrupar_linhas(palavras: list[Palavra]) -> list[Linha]:
    """Agrupa palavras em linhas visuais pela sobreposição vertical.

    Funciona igual para texto nativo do PDF e para a saída do OCR, o que deixa o parser
    independente da origem. Linhas de tabela viram uma linha só (colunas lado a lado)."""
    linhas: list[Linha] = []
    por_pagina: dict[int, list[Palavra]] = {}
    for p in palavras:
        if p.texto.strip():
            por_pagina.setdefault(p.pagina, []).append(p)

    for pagina in sorted(por_pagina):
        atuais: list[list[Palavra]] = []
        for p in sorted(por_pagina[pagina], key=lambda w: (w.centro_y, w.bbox[0])):
            colocado = False
            for grupo in reversed(atuais[-3:]):
                ref_top = median(w.bbox[1] for w in grupo)
                ref_bot = median(w.bbox[3] for w in grupo)
                sobreposicao = min(ref_bot, p.bbox[3]) - max(ref_top, p.bbox[1])
                menor = max(min(ref_bot - ref_top, p.altura), 1.0)
                if sobreposicao / menor > 0.5:
                    grupo.append(p)
                    colocado = True
                    break
            if not colocado:
                atuais.append([p])
        for grupo in atuais:
            grupo.sort(key=lambda w: w.bbox[0])
            linhas.append(Linha(grupo))
    return linhas
