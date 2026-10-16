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
        return _nome_incompleto(alvo, candidatos, dono) or _letras_espacadas(alvo, candidatos, dono, limiar) \
            or (None, float(score))
    return dono[idx], float(round(score, 2))


def _nome_incompleto(alvo: str, candidatos: list[str], dono: list[Ref]) -> tuple[Ref, float] | None:
    """Nome escrito pela metade, que só um item da lista completa: "Betânia" (Betânia do Piauí), "Capitão
    Gervásio" (Capitão Gervásio Oliveira), "Unidade Residencial" (... não atendida por rede de água)."""
    if len(alvo) < 5:
        return None
    donos = {id(dono[i]): dono[i] for i, c in enumerate(candidatos) if c.startswith(alvo + " ")}
    return (next(iter(donos.values())), 85.0) if len(donos) == 1 else None


def _letras_espacadas(alvo: str, candidatos: list[str], dono: list[Ref], limiar: float) -> tuple[Ref, float] | None:
    """Texto com as letras separadas por espaço ("S Ã O R A I M U N D O"): compara sem os espaços."""
    partes = alvo.split()
    if len(partes) < 4 or sum(len(p) == 1 for p in partes) < 0.7 * len(partes):
        return None
    junto = alvo.replace(" ", "")
    pontos = [fuzz.ratio(junto, c.replace(" ", "")) for c in candidatos]
    i = max(range(len(candidatos)), key=pontos.__getitem__)
    return (dono[i], float(round(min(pontos[i], 90.0), 2))) if pontos[i] >= max(limiar, 90) else None


def _pontuar(a: str, b: str, **_: Any) -> float:
    # ratio puro penaliza menos falsos positivos que WRatio em nomes de município curtos
    # ("altos" x "alto longa"); token_sort cobre palavras trocadas de lugar.
    return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))
