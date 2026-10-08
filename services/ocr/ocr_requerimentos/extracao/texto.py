"""Normalização de texto e correspondência aproximada (fuzzy) contra listas de referência."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz, process


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def chave(s: str) -> str:
    """Forma canônica para comparação: minúsculas, sem acento, só letras/dígitos e espaços."""
    s = sem_acento(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalizar_paralelo(s: str) -> str:
    """Minúsculas e sem acento preservando o comprimento (1 caractere -> 1 caractere).

    Permite rodar regex no texto normalizado e recortar o trecho original pelos mesmos índices."""
    saida = []
    for c in s:
        base = unicodedata.normalize("NFD", c)[0] if c.strip() else c
        baixo = base.lower()
        saida.append(baixo[0] if baixo else base)
    return "".join(saida)


def proporcao_letras(s: str) -> float:
    s = s.strip()
    if not s:
        return 0.0
    return sum(c.isalpha() for c in s) / len(s.replace(" ", "") or "x")


@dataclass
class Ref:
    id: int | None
    nome: str
    sinonimos: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def melhor_correspondencia(texto: str | None, opcoes: list[Ref], limiar: float = 80.0) -> tuple[Ref | None, float]:
    """Retorna a referência mais parecida e a pontuação (0–100). Abaixo do limiar, devolve (None, score)."""
    if not texto or not opcoes:
        return None, 0.0
    alvo = chave(texto)
    if not alvo:
        return None, 0.0
    # mesmo texto (com acentos): a lista do formulário tem quase-duplicatas ("Cana de Açucar" e
    # "Cana-de-açúcar") e o valor impresso deve ser o escolhido
    exato = re.sub(r"\s+", " ", texto).strip().casefold()
    for ref in opcoes:
        if re.sub(r"\s+", " ", ref.nome).strip().casefold() == exato:
            return ref, 100.0
    candidatos: list[str] = []
    dono: list[Ref] = []
    for ref in opcoes:
        for nome in [ref.nome, *ref.sinonimos]:
            candidatos.append(chave(nome))
            dono.append(ref)
    # igualdade exata primeiro (evita empates do WRatio entre nomes curtos)
    for i, c in enumerate(candidatos):
        if c == alvo:
            return dono[i], 100.0
    resultado = process.extractOne(alvo, candidatos, scorer=_pontuar)
    if not resultado:
        return None, 0.0
    _, score, idx = resultado
    if score < limiar:
        return None, float(score)
    return dono[idx], float(round(score, 2))


def _pontuar(a: str, b: str, **_: Any) -> float:
    # ratio puro penaliza menos falsos positivos que WRatio em nomes de município curtos
    # ("altos" x "alto longa"); token_sort cobre palavras trocadas de lugar.
    return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))
