import pytest

from ocr_requerimentos.extracao.normalizadores import (
    normalizar_coordenada, normalizar_cpf_cnpj, normalizar_data, normalizar_numero,
)
from ocr_requerimentos.extracao.texto import Ref, melhor_correspondencia


def test_ct01_cpf_valido():
    d = normalizar_cpf_cnpj("05974965361")
    assert d.valido and d.tipo == "F" and d.formatado == "059.749.653-61"


def test_ct02_cpf_com_letra_o_do_ocr():
    d = normalizar_cpf_cnpj("O5974965361")
    assert d.valido and d.digitos == "05974965361"


@pytest.mark.parametrize("cpf", ["05974965362", "11111111111", "1234567"])
def test_ct03_cpf_invalido(cpf):
    d = normalizar_cpf_cnpj(cpf)
    assert not d.valido and d.mensagem


def test_ct04_cnpj_valido_com_mascara():
    d = normalizar_cpf_cnpj("11.222.333/0001-81")
    assert d.valido and d.tipo == "J" and d.formatado == "11.222.333/0001-81"


def test_ct05_segundos_acima_de_60():
    c = normalizar_coordenada("-5°02'91.06\"", "lat")
    assert not c.valida
    assert any("segundos" in e for e in c.erros)


def test_ct06_longitude_valida():
    c = normalizar_coordenada("-42°42'32.38\".", "lon")
    assert c.valida and c.decimal == pytest.approx(-42.7089944, abs=1e-7)


def test_ct07_sinal_ausente_assume_sul_oeste():
    c = normalizar_coordenada("5°02'41\"", "lat")
    assert c.valida and c.decimal < 0
    assert any("assumido" in a for a in c.avisos)


@pytest.mark.parametrize("texto", ["5o02'41,5\" S", "-5º02’41.5”", "5°02'41.5\"S"])
def test_ct08_variantes_de_simbolos(texto):
    c = normalizar_coordenada(texto, "lat")
    assert c.valida and c.decimal == pytest.approx(-5.0448611, abs=1e-6)


@pytest.mark.parametrize("bruto,esperado", [("10", 10.0), ("2,5", 2.5), ("1.234,5", 1234.5), ("1O", 10.0), ("abc", None)])
def test_ct09_numeros(bruto, esperado):
    assert normalizar_numero(bruto) == esperado


def test_ct10_municipio_com_ruido():
    opcoes = [Ref(1, "Altos"), Ref(2, "Alto Longá"), Ref(3, "Teresina")]
    ref, score = melhor_correspondencia("ALT0S", opcoes, 80)
    assert ref.nome == "Altos" and score >= 80


def test_ct11_nome_parcial_nao_casa_errado():
    opcoes = [Ref(1, "Altos"), Ref(2, "Alto Longá"), Ref(3, "Teresina")]
    ref, _ = melhor_correspondencia("Alto L", opcoes, 90)
    assert ref is None or ref.nome == "Alto Longá"


def test_datas():
    assert normalizar_data("01/1O/2026").isoformat() == "2026-10-01"
    assert normalizar_data("31/02/2026") is None
