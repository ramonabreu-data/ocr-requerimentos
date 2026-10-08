"""Blocos da seção "Finalidade(s) do Uso da Água", descritos como dados.

Cada finalidade marcada no formulário (https://aguas.semarh.pi.gov.br/requerimentos/criar) vira,
no PDF, um título seguido dos seus dados em três formatos possíveis:

- campos "Rótulo: valor" (ex.: "Profundidade (m): 2.8");
- tabela com cabeçalho e uma linha por item (células podem quebrar em várias linhas);
- lista de itens soltos, um por linha (espécies da aquicultura) ou "uso: descrição" (outros usos).

O parser e a validação leem estas definições; para um campo novo no formulário basta descrevê-lo aqui.
No banco, cada valor vira um `campo_extraido` com nome "<finalidade>.<campo>" e, nas linhas, `indice`."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .texto import chave

# tipos: texto | numero | inteiro | data | lista (compara com o dicionário `dominio`)


@dataclass(frozen=True)
class CampoDef:
    chave: str
    rotulo: str
    tipo: str = "texto"
    dominio: str | None = None  # tipo em ocr.dominio, ou "municipio"
    obrigatorio: bool = True


@dataclass(frozen=True)
class FinalidadeDef:
    chave: str
    nome: str  # como aparece na lista de finalidades do formulário (e do SIGA)
    titulos: tuple[str, ...]  # como o título sai impresso no PDF
    campos: tuple[CampoDef, ...] = ()  # "Rótulo: valor"
    colunas: tuple[CampoDef, ...] = ()  # campos de cada linha (tabela, lista ou pares)
    modo_linhas: str | None = None  # tabela | lista | pares
    cabecalho: str | None = None  # regex (sobre chave()) da linha de cabeçalho da tabela / rótulo da lista
    coluna_numerica: str | None = None  # coluna sempre numérica: marca o início de cada linha da tabela
    rotulo_linhas: str = "itens"
    min_linhas: int = 1
    sinonimos: tuple[str, ...] = field(default_factory=tuple)

    def campo(self, nome: str) -> CampoDef | None:
        return next((c for c in (*self.campos, *self.colunas) if c.chave == nome), None)


FINALIDADES: tuple[FinalidadeDef, ...] = (
    FinalidadeDef(
        "abastecimento_publico", "Abastecimento Público", ("Abastecimento Público",),
        campos=(
            CampoDef("prestador", "Tipo de Prestador de Serviços", "lista", "prestador"),
            CampoDef("concessao_numero", "Número da Concessão", "texto", obrigatorio=False),
            CampoDef("concessao_data_final", "Data Final da Concessão", "data", obrigatorio=False),
        ),
        colunas=(
            CampoDef("municipio", "Município", "lista", "municipio"),
            CampoDef("localidade", "Localidade"),
            CampoDef("habitantes", "Qtd. habitantes (horizonte 10 anos)", "inteiro"),
        ),
        modo_linhas="tabela", cabecalho=r"municipio.*localidade", coluna_numerica="habitantes",
        rotulo_linhas="localidades atendidas",
    ),
    FinalidadeDef(
        "aquicultura_tanque", "Aquicultura em Tanque Escavado", ("Aquicultura em Tanque Escavado",),
        campos=(
            CampoDef("profundidade", "Profundidade (m)", "numero"),
            CampoDef("area_tanques", "Área total dos tanques (m2)", "numero"),
        ),
        colunas=(CampoDef("especie", "Espécie", "lista", "especie_aquicultura"),),
        modo_linhas="lista", cabecalho=r"^especies?$", rotulo_linhas="espécies",
    ),
    FinalidadeDef(
        "consumo_humano", "Consumo Humano", ("Consumo Humano",),
        colunas=(
            CampoDef("estabelecimento", "Tipo de estabelecimento", "lista", "estabelecimento"),
            CampoDef("pessoas", "Quantidade de pessoas", "inteiro"),
        ),
        modo_linhas="tabela", cabecalho=r"estabelecimento", coluna_numerica="pessoas",
        rotulo_linhas="estabelecimentos",
    ),
    FinalidadeDef(
        "criacao_animal", "Criação Animal", ("Criação Animal",),
        colunas=(
            CampoDef("especie", "Espécie", "lista", "especie_animal"),
            CampoDef("sistema", "Sistema de Criação", "lista", "sistema_criacao"),
            CampoDef("cabecas", "Número de Cabeças", "inteiro"),
        ),
        modo_linhas="tabela", cabecalho=r"especie.*sistema", coluna_numerica="cabecas",
        rotulo_linhas="criações",
    ),
    FinalidadeDef(
        "industria", "Indústria", ("Indústria", "Indútria"),  # o PDF imprime "Indútria"
        colunas=(
            CampoDef("tipologia", "Tipologia (CNAE)"),
            CampoDef("producao_anual", "Produção anual", "numero"),
            CampoDef("unidade", "Unidade", "lista", "unidade"),
        ),
        modo_linhas="tabela", cabecalho=r"tipologia", coluna_numerica="producao_anual",
        rotulo_linhas="tipologias",
    ),
    FinalidadeDef(
        "mineracao_outros", "Mineração - Outros Processos Extrativos", ("Mineração - Outros Processos Extrativos",),
        min_linhas=0,
    ),
    FinalidadeDef(
        "irrigacao", "Irrigação", ("Irrigação",),
        colunas=(
            CampoDef("sistema", "Sistema de Irrigação", "lista", "sistema_irrigacao"),
            CampoDef("area", "Área Irrigada (ha)", "numero"),
            CampoDef("cultura", "Tipo de Cultura", "lista", "cultura"),
        ),
        modo_linhas="tabela", cabecalho=r"sistema de irriga", coluna_numerica="area",
        rotulo_linhas="tabela de irrigação",
    ),
    FinalidadeDef(
        "mineracao_areia", "Mineração - Extração de Areia/Cascalho em Leito de Rio",
        ("Mineração - Extração de Areia/Cascalho em Leito de Rio",),
        campos=(
            CampoDef("producao_mensal", "Produção Máxima Mensal (m³/mês)", "numero"),
            CampoDef("proporcao_agua", "Proporção de água na polpa", "numero"),
            CampoDef("umidade", "Teor de umidade (%)", "numero"),
        ),
        min_linhas=0,
    ),
    FinalidadeDef(
        "outros_usos", "Outras", ("Outros Usos",),
        colunas=(
            CampoDef("uso", "Outro uso", "lista", "uso_outro"),
            CampoDef("descricao", "Descrição", obrigatorio=False),
        ),
        modo_linhas="pares", rotulo_linhas="outros usos", sinonimos=("Outros Usos", "Outros"),
    ),
    FinalidadeDef(
        "termoeletrica", "Termoelétrica", ("Termoelétricas", "Termoelétrica"),
        campos=(
            CampoDef("combustivel", "Combustível Principal", "lista", "combustivel"),
            CampoDef("potencia", "Potência Instalada (MW)", "numero"),
            CampoDef("producao_energia", "Produção Mensal Média de Energia (MWH)", "numero"),
        ),
        min_linhas=0,
    ),
)
POR_CHAVE = {f.chave: f for f in FINALIDADES}


def _nomes(f: FinalidadeDef) -> list[str]:
    return [chave(t) for t in (*f.titulos, f.nome, *f.sinonimos)]


def definicao_por_titulo(texto: str | None, limiar: float = 85) -> FinalidadeDef | None:
    """Reconhece o título impresso de uma finalidade (tolerando erros de OCR)."""
    alvo = chave(texto or "")
    if not alvo:
        return None
    melhor, pontos = None, 0.0
    for f in FINALIDADES:
        for n in _nomes(f):
            p = fuzz.ratio(alvo, n)
            if p > pontos:
                melhor, pontos = f, p
    return melhor if pontos >= limiar else None


def rotulo_campo(nome: str) -> str | None:
    """'aquicultura_tanque.profundidade' -> 'Aquicultura em Tanque Escavado — Profundidade (m)'."""
    if "." not in nome:
        return None
    fin, campo = nome.split(".", 1)
    f = POR_CHAVE.get(fin)
    c = f.campo(campo) if f else None
    return f"{f.nome} — {c.rotulo}" if f and c else None


def casa_cabecalho(f: FinalidadeDef, texto: str) -> bool:
    return bool(f.cabecalho and re.search(f.cabecalho, chave(texto)))
