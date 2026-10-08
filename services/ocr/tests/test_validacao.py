from datetime import date

from ocr_requerimentos.extracao.parser import ExtracaoBruta, LinhaIrrigacao
from ocr_requerimentos.extracao.tipos import CampoBruto
from ocr_requerimentos.extracao.validacao import validar


def _c(v):
    return CampoBruto(v, conf_fixa=100.0)


def _base(**kw) -> ExtracaoBruta:
    ex = ExtracaoBruta(
        requerente_nome=_c("Ramon Teste"), cpf_cnpj=_c("05974965361"), procedimento=_c("Regularização de Poço Tubular"),
        tipo_intervencao=_c("Poço Tubular"), municipio=_c("ALTOS"), localidade=_c("teste"),
        latitude=_c("-5°02'41.06\""), longitude=_c("-42°42'32.38\""), finalidades=[_c("Irrigação")],
        irrigacao=[LinhaIrrigacao(_c("Micro-aspersão"), _c("1"), _c("Abacaxi (solo limpo)"), "")],
        data_documento=_c("01/10/2026"),
    )
    for k, v in kw.items():
        setattr(ex, k, v)
    return ex


def test_documento_valido_fica_extraido(refs):
    r = validar(_base(), refs, hoje=date(2026, 10, 1))
    assert r.status == "extraido", r.pendencias
    assert r.pessoa_id == 1 and r.campos["municipio"].ref_id == 1
    assert r.irrigacao[0].sistema.ref_id is not None


def test_ct12_coordenada_fora_do_piaui(refs):
    r = validar(_base(latitude=_c("-15°02'41\""), longitude=_c("-47°00'00\"")), refs, hoje=date(2026, 10, 1))
    assert r.status == "revisao"
    assert any("fora dos limites do Piauí" in p for p in r.pendencias)


def test_ct13_irrigacao_sem_tabela(refs):
    r = validar(_base(irrigacao=[]), refs, hoje=date(2026, 10, 1))
    assert any("Irrigação sem itens" in p for p in r.pendencias)


def test_ct14_finalidade_sem_tabela_nao_exige_irrigacao(refs):
    r = validar(_base(irrigacao=[], finalidades=[_c("Abastecimento Humano")]), refs, hoje=date(2026, 10, 1))
    assert r.status == "extraido", r.pendencias


def test_ct15_data_no_futuro(refs):
    r = validar(_base(data_documento=_c("01/10/2030")), refs, hoje=date(2026, 10, 1))
    assert not r.campos["data_documento"].valido
    assert r.status == "revisao"


def test_ct46_nome_diferente_do_cadastro(refs):
    r = validar(_base(requerente_nome=_c("José Pereira Lima")), refs, hoje=date(2026, 10, 1))
    c = r.campos["requerente_nome"]
    assert c.confianca < 85 and "Ramon Teste" in c.mensagem


def test_ponto_fora_do_municipio(refs):
    refs.poligonos[1] = False
    r = validar(_base(), refs, hoje=date(2026, 10, 1))
    assert any("fora do município declarado" in p for p in r.pendencias)


def test_procedimento_desconhecido(refs):
    r = validar(_base(procedimento=_c("Licença de Instalação")), refs, hoje=date(2026, 10, 1))
    assert not r.campos["procedimento"].valido
