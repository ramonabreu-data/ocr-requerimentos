"""PDFs reais do formulário público (https://aguas.semarh.pi.gov.br/requerimentos/criar).

`fixtures/formulario/cenarios.json` é exatamente o que foi enviado ao formulário para gerar cada PDF
(`fixtures/formulario/gerar.py` gera de novo). Ele serve de gabarito: o que o OCR leu tem de bater
com o que foi digitado. Cenários (CT-8x), cada um com pelo menos dois PDFs:

- fin01..fin10: cada finalidade sozinha, com 1 ou 3 itens; juntos cobrem os 9 procedimentos,
  os 3 assuntos (Poço Tubular, Captação Superficial, Diluição de Efluentes), CPF e CNPJ;
- todas: as 10 finalidades no mesmo requerimento (PDF de 2 e 3 páginas);
- incompleto: finalidade marcada sem os dados próprios -> revisão com pendências;
- coord: coordenadas sem sinal e sem casas decimais nos segundos."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import fabrica as F
from ocr_requerimentos import dados_referencia as D
from ocr_requerimentos.extracao.referencias import ReferenciasEstaticas
from ocr_requerimentos.extracao.texto import Ref, chave
from ocr_requerimentos.pipeline.extracao import processar_arquivo

PASTA = Path(__file__).parent / "fixtures" / "formulario"
CENARIOS: dict[str, dict] = json.loads((PASTA / "cenarios.json").read_text(encoding="utf-8"))
NOMES_FIN = {i: n for i, n in enumerate(D.FINALIDADES, start=1)}


@pytest.fixture(scope="module")
def refs_form() -> ReferenciasEstaticas:
    """Referências com as listas do formulário (as mesmas do SIGA em produção)."""
    return ReferenciasEstaticas(
        municipios=[Ref(i, n) for i, n in enumerate(D.MUNICIPIOS_PI, 1)],
        procedimentos=[Ref(i, n) for i, n in enumerate(D.PROCEDIMENTOS, 1)],
        intervencoes=[Ref(i, n) for i, n in enumerate(D.ASSUNTOS, 1)],
        finalidades=[Ref(i, n) for i, n in enumerate(D.FINALIDADES, 1)],
        sistemas_irrigacao=[Ref(i, n, s) for i, (n, s) in enumerate(D.SISTEMAS_IRRIGACAO, 1)],
        culturas=[Ref(i, n, s) for i, (n, s) in enumerate(D.CULTURAS, 1)],
        dominios={t: [Ref(i, n, s) for i, (n, s) in enumerate(v, 1)] for t, v in D.DOMINIOS.items()},
    )


# ------------------------------------------------------------------ gabarito a partir do formulário
def _num(v: str) -> float | None:
    return float(v) if v not in ("", None) else None


def _coord(g: str, m: str, s1: str, s2: str) -> float:
    valor = abs(float(g)) + float(m) / 60 + float(f"{s1}.{s2 or 0}") / 3600
    return round(-valor, 7)  # Piauí: Sul/Oeste, mesmo quando o sinal não foi digitado


def _itens(linhas: list[dict], conv: dict) -> list[dict]:
    return [{k: f(ln[orig]) for k, (orig, f) in conv.items()} for ln in linhas]


def detalhes_esperados(fin: int, d: dict) -> dict:
    txt = lambda v: v or None  # noqa: E731
    if fin == 1:
        return {"prestador": txt(d["prestador"]), "concessao_numero": txt(d["concessao"]["numero"]),
                "concessao_data_final": txt(d["concessao"]["data_final"]),
                "itens": _itens([x for x in d["abastecimentos_publicos"] if x["municipio"]],
                                {"municipio": ("municipio", str), "localidade": ("localidade", str),
                                 "habitantes": ("qtd_habitantes", int)})}
    if fin == 2:
        a = d["aquicultura-escavado"]
        return {"profundidade": _num(a["profundidade"]), "area_tanques": _num(a["area_total_tanques"]),
                "itens": [{"especie": e} for e in a["especies"]]}
    if fin == 3:
        return {"itens": _itens([x for x in d["consumos_humanos"] if x["estabelecimento"]],
                                {"estabelecimento": ("estabelecimento", str), "pessoas": ("qtd_pessoas_dia", int)})}
    if fin == 4:
        return {"itens": _itens([x for x in d["criacoes_animais"] if x["especie"]],
                                {"especie": ("especie", str), "sistema": ("sistema_criacao", str),
                                 "cabecas": ("numero_cabecas", int)})}
    if fin == 5:
        return {"itens": _itens([x for x in d["industrias"] if x["tipologia"]],
                                {"tipologia": ("tipologia", str), "producao_anual": ("producao_anual", float),
                                 "unidade": ("unidade", str)})}
    if fin == 6:
        return {}
    if fin == 7:
        return {"itens": _itens([x for x in d["irrigacoes"] if x["sistema"]],
                                {"sistema": ("sistema", str), "area": ("area", float), "cultura": ("cultura", str)})}
    if fin == 8:
        m = d["mineracao_areia"]
        return {"producao_mensal": _num(m["producao"]), "proporcao_agua": _num(m["proporcao"]),
                "umidade": _num(m["umidade"])}
    if fin == 9:
        return {"itens": _itens([x for x in d["outros"] if x["uso"]],
                                {"uso": ("uso", str), "descricao": ("descricao", lambda v: v or None)})}
    t = d["termoeletricas"]
    return {"combustivel": txt(t["combustivel"]), "potencia": _num(t["potencia"]), "producao_energia": _num(t["producao"])}


def _sem_espacos_duplos(v):
    if isinstance(v, str):
        return " ".join(v.split())
    if isinstance(v, list):
        return [_sem_espacos_duplos(x) for x in v]
    if isinstance(v, dict):
        return {k: _sem_espacos_duplos(x) for k, x in v.items()}
    return v


CHAVES_FIN = ["abastecimento_publico", "aquicultura_tanque", "consumo_humano", "criacao_animal", "industria",
              "mineracao_outros", "irrigacao", "mineracao_areia", "outros_usos", "termoeletrica"]


def divergencias(seg, d: dict, *, ocr: bool = False) -> list[tuple[str, object, object]]:
    """(rótulo usado nas pendências, lido, esperado) de cada campo que não bate com o formulário."""
    r = seg.resultado
    c = {k: v.valor_normalizado for k, v in r.campos.items()}
    lat = _coord(d["lat_grau"], d["lat_min"], d["lat_seg1"], d["lat_seg2"])
    lon = _coord(d["long_grau"], d["long_min"], d["long_seg1"], d["long_seg2"])
    checagens = [
        ("Nome do requerente", chave(c["requerente_nome"]), chave(d["nome"])),
        ("CPF/CNPJ", (c["cpf_cnpj"] or "").replace(".", "").replace("-", "").replace("/", ""), d["cpf_cnpj"]),
        ("Procedimento", c["procedimento"], d["procedimento"]),
        ("Tipo de intervenção", c["tipo_intervencao"], d["assunto"]),
        ("Município", c["municipio"], d["municipio"]),
        ("Localidade", chave(c["localidade"]), chave(d["localidade"])),
        ("Latitude", r.latitude is not None and round(r.latitude, 6), round(lat, 6)),
        ("Longitude", r.longitude is not None and round(r.longitude, 6), round(lon, 6)),
    ]
    if not ocr:
        checagens += [
            ("Descrição", c["descricao_usos"], d["descricao"].rstrip(".")),  # o parser tira a pontuação das bordas
            ("Assinante", chave(c["assinante_nome"]), chave(d["nome"])),
            ("Tipo de pessoa", r.tipo_pessoa, "F" if len(d["cpf_cnpj"]) == 11 else "J"),
        ]
    fins = sorted(int(k) for k, v in d["finalidade"].items() if v)
    checagens.append(("Finalidade", [f.valor_normalizado for f in r.finalidades], [NOMES_FIN[f] for f in fins]))
    detalhes = {det.chave: det.dados for det in r.detalhes}
    for f in fins:
        lido = _sem_espacos_duplos(detalhes.get(CHAVES_FIN[f - 1]))
        rotulo = "Irrigação" if f == 7 else NOMES_FIN[f]
        checagens.append((rotulo, lido, _sem_espacos_duplos(detalhes_esperados(f, d))))
    return [(rot, lido, esp) for rot, lido, esp in checagens if lido != esp]


def conferir(seg, d: dict) -> None:
    """Texto nativo: tudo tem de bater exatamente com o que foi digitado no formulário."""
    assert divergencias(seg, d) == []


def conferir_ocr(seg, d: dict) -> list[str]:
    """OCR: cada campo bate com o formulário ou está nas pendências (nunca errado em silêncio)."""
    r = seg.resultado
    silenciosas = []
    for rotulo, lido, esperado in divergencias(seg, d, ocr=True):
        if r.status != "revisao" or not any(p.startswith(rotulo) for p in r.pendencias):
            silenciosas.append(f"{rotulo}: lido {lido!r}, esperado {esperado!r}")
    assert silenciosas == [], (silenciosas, r.pendencias)
    return [rot for rot, _, _ in divergencias(seg, d, ocr=True)]


def _rodar(nome: str, motor, refs, conteudo: bytes | None = None, arquivo: str | None = None):
    conteudo = conteudo or (PASTA / f"{nome}.pdf").read_bytes()
    res = processar_arquivo(conteudo, motor, refs, arquivo or f"{nome}.pdf")
    assert len(res.segmentos) == 1, "documento de várias páginas não pode ser dividido"
    return res, res.segmentos[0]


# ------------------------------------------------------------------ CT-80: texto nativo, todos os cenários
COMPLETOS = [n for n in CENARIOS if n.startswith(("fin", "todas"))]


@pytest.mark.parametrize("nome", COMPLETOS)
def test_ct80_formulario_texto_nativo(nome, motor, refs_form):
    res, seg = _rodar(nome, motor, refs_form)
    assert res.leitura.metodo == "texto_nativo"
    conferir(seg, CENARIOS[nome])
    assert seg.resultado.status == "extraido", seg.resultado.pendencias
    assert seg.resultado.confianca_geral == 100.0


def test_ct81_cobertura_dos_cenarios():
    """Pelo menos dois PDFs por procedimento, assunto, finalidade e tipo de pessoa."""
    from collections import Counter

    procs = Counter(d["procedimento"] for d in CENARIOS.values())
    assuntos = Counter(d["assunto"] for d in CENARIOS.values())
    fins = Counter(int(k) for d in CENARIOS.values() for k, v in d["finalidade"].items() if v)
    pessoas = Counter(len(d["cpf_cnpj"]) for d in CENARIOS.values())
    assert set(procs) == set(D.PROCEDIMENTOS) and min(procs.values()) >= 2
    assert set(assuntos) == set(D.ASSUNTOS) and min(assuntos.values()) >= 2
    assert set(fins) == set(range(1, 11)) and min(fins.values()) >= 2
    assert pessoas[11] >= 2 and pessoas[14] >= 2


@pytest.mark.parametrize("nome", ["todas_1", "todas_2"])
def test_ct82_varias_paginas_sem_ocr(nome, motor, refs_form):
    res, seg = _rodar(nome, motor, refs_form)
    assert len(res.leitura.paginas) >= 2
    assert {p.metodo for p in res.leitura.paginas} == {"texto_nativo"}  # inclusive a página só com nome e data
    assert seg.resultado.data_documento is not None


def test_ct83_incompleto_vai_para_revisao(motor, refs_form):
    _, seg = _rodar("incompleto_1", motor, refs_form)  # Irrigação e Criação Animal sem itens
    r = seg.resultado
    assert r.status == "revisao"
    assert "finalidade Irrigação sem itens na tabela de irrigação" in r.pendencias
    assert "Criação Animal: nenhum item em criações" in r.pendencias

    _, seg = _rodar("incompleto_2", motor, refs_form)  # Abastecimento, Aquicultura e Termoelétrica vazias
    p = seg.resultado.pendencias
    assert "Abastecimento Público — Tipo de Prestador de Serviços: não preenchido" in p
    assert "Abastecimento Público: nenhum item em localidades atendidas" in p
    assert "Aquicultura em Tanque Escavado — Profundidade (m): não preenchido" in p
    assert "Aquicultura em Tanque Escavado: nenhum item em espécies" in p
    assert "Termoelétrica — Potência Instalada (MW): não preenchido" in p
    # concessão é opcional no formulário
    assert not any("Concessão" in x for x in p)


@pytest.mark.parametrize("nome", ["coord_1", "coord_2"])
def test_ct84_coordenadas_sem_sinal(nome, motor, refs_form):
    _, seg = _rodar(nome, motor, refs_form)
    conferir(seg, CENARIOS[nome])  # sinal recolocado: valores iguais aos digitados com '-'
    r = seg.resultado
    assert r.status == "revisao"  # sinal assumido pede conferência humana
    assert "sinal negativo ausente" in (r.campos["latitude"].mensagem or "")


# ------------------------------------------------------------------ CT-85: mesmos PDFs impressos e digitalizados
DIGITALIZADOS = ["fin01_2", "fin02_2", "fin03_2", "fin04_2", "fin05_2", "fin07_2", "fin08_1", "fin09_2", "fin10_1",
                 "fin06_1", "fin01_1", "fin04_1", "fin07_1", "fin09_1", "todas_1"]


@pytest.mark.parametrize("nome", DIGITALIZADOS)
def test_ct85_formulario_digitalizado(nome, motor, refs_form):
    """Página renderizada a 300 dpi (como scanner), levemente girada e com ruído, lida por OCR."""
    pdf = (PASTA / f"{nome}.pdf").read_bytes()
    imgs = [F.ruido(F.girar(F.renderizar(pdf, i), 1.2), 8) for i in range(_paginas(pdf))]
    res, seg = _rodar(nome, motor, refs_form, F.pdf_de_imagens(*imgs), f"{nome}-scanner.pdf")
    assert res.leitura.metodo == "ocr"
    erradas = conferir_ocr(seg, CENARIOS[nome])
    assert len(erradas) <= 1, erradas  # no máximo um campo para corrigir na revisão


def _paginas(pdf: bytes) -> int:
    import pymupdf

    return pymupdf.open(stream=pdf, filetype="pdf").page_count
