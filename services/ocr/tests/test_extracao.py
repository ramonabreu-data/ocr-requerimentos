"""Extração ponta a ponta sem banco: leitura (texto nativo / OCR), parser, validação, assinatura e QR."""
import cv2
import pytest

import fabrica as F
from ocr_requerimentos.extracao.parser import extrair
from ocr_requerimentos.extracao.tipos import CampoBruto, PaginaLida, Palavra, agrupar_linhas
from ocr_requerimentos.imagem.qrcode import conteudo_padrao, gerar_png
from ocr_requerimentos.pipeline.extracao import conferir_campo_numerico, processar_arquivo
from ocr_requerimentos.pipeline.leitura import ArquivoInvalido

ESPERADO_REAL = {
    "requerente_nome": "ramon teste",
    "cpf_cnpj": "059.749.653-61",
    "procedimento": "Regularização de Poço Tubular",
    "tipo_intervencao": "Poço Tubular",
    "municipio": "Altos",
    "localidade": "teste",
    "longitude": "-42.7089944",
    "descricao_usos": "uso para irrigação de hortas",
    "data_documento": "2026-10-01",
}
IRRIGACAO_REAL = [
    ("Aspersão por canhão hidráulico", "10", "Alface"),
    ("Aspersão por sistema autopropelido", "3", "Acerola"),
    ("Micro-aspersão", "1", "Abacaxi (solo limpo)"),
]
PRINCIPAIS = ("cpf_cnpj", "procedimento", "tipo_intervencao", "municipio", "longitude")


def _rodar(conteudo, motor, refs, nome="doc.pdf"):
    res = processar_arquivo(conteudo, motor, refs, nome)
    return res, res.segmentos[0]


def _valores(seg):
    return {k: c.valor_normalizado for k, c in seg.resultado.campos.items()}


def _irrigacao(seg):
    return [(i.sistema.valor_normalizado, i.area.valor_normalizado, i.cultura.valor_normalizado)
            for i in seg.resultado.irrigacao]


def test_ct20_pdf_real_texto_nativo(pdf_exemplo, motor, refs):
    res, seg = _rodar(pdf_exemplo, motor, refs)
    assert res.leitura.tipo_entrada == "pdf_texto" and res.leitura.metodo == "texto_nativo"
    v = _valores(seg)
    for k, esperado in ESPERADO_REAL.items():
        assert v[k] == esperado, k
    assert _irrigacao(seg) == IRRIGACAO_REAL
    assert [f.valor_normalizado for f in seg.resultado.finalidades] == ["Irrigação"]
    assert seg.resultado.status == "revisao"
    assert seg.resultado.pendencias == ["Latitude: segundos (91.06) fora do intervalo 0–59,99"]
    assert seg.resultado.pessoa_id == 1


def test_ct21_pdf_sintetico_valido(motor, refs):
    _, seg = _rodar(F.pdf_requerimento(F.DadosReq()), motor, refs)
    assert seg.resultado.status == "extraido", seg.resultado.pendencias
    assert seg.resultado.confianca_geral == 100
    assert seg.resultado.latitude == pytest.approx(-5.0447389, abs=1e-6)


def test_ct22_pdf_real_como_imagem_300dpi(pdf_exemplo, motor, refs):
    img = F.renderizar(pdf_exemplo, dpi=300)
    res, seg = _rodar(F.png(img), motor, refs, "scan.png")
    assert res.leitura.tipo_entrada == "imagem"
    v = _valores(seg)
    for k, esperado in ESPERADO_REAL.items():
        assert v[k] == esperado, k
    assert _irrigacao(seg) == IRRIGACAO_REAL
    assert any("Latitude" in p for p in seg.resultado.pendencias)


def test_ct23_digitalizacao_girada_ruidosa(pdf_exemplo, motor, refs):
    img = F.renderizar(pdf_exemplo, dpi=200)
    img = F.jpeg(F.ruido(F.girar(img, 3.0)), 45)
    _, seg = _rodar(F.jpg_bytes(img, 95), motor, refs, "scan.jpg")
    assert abs(abs(seg.paginas[0].angulo_correcao) - 3.0) < 0.6
    v = _valores(seg)
    for k in PRINCIPAIS:
        assert v[k] == ESPERADO_REAL[k], k
    assert len(seg.resultado.irrigacao) == 3


def test_ct24_pagina_de_cabeca_para_baixo(motor, refs):
    img = cv2.rotate(F.renderizar(F.pdf_requerimento(F.DadosReq())), cv2.ROTATE_180)
    _, seg = _rodar(F.png(img), motor, refs, "invertida.png")
    assert seg.paginas[0].angulo_correcao % 360 == pytest.approx(180, abs=1)
    v = _valores(seg)
    assert v["municipio"] == "Altos" and v["cpf_cnpj"] == "529.982.247-25"


def test_ct25_foto_em_perspectiva(pdf_exemplo, motor, refs):
    img = F.foto_perspectiva(F.amarelar(F.renderizar(pdf_exemplo, dpi=200)))
    _, seg = _rodar(F.jpg_bytes(img, 85), motor, refs, "foto.jpg")
    v = _valores(seg)
    for k in PRINCIPAIS:
        assert v[k] == ESPERADO_REAL[k], k


def test_ct26_pdf_de_scanner_so_imagem(motor, refs):
    pdf = F.pdf_de_imagens(F.renderizar(F.pdf_requerimento(F.DadosReq())))
    res, seg = _rodar(pdf, motor, refs)
    assert res.leitura.tipo_entrada == "pdf_imagem" and res.leitura.metodo == "ocr"
    assert _valores(seg)["localidade"] == "Povoado Boa Esperança"


def test_ct27_assinatura_azul_manuscrita(motor, refs):
    pdf = F.pdf_requerimento(F.DadosReq())
    img = F.renderizar(pdf)
    img = F.rabisco_assinatura(img, F.bbox_texto_pdf(pdf, "Maria das Graças Sousa"))
    _, seg = _rodar(F.png(img), motor, refs, "assinado.png")
    assert seg.assinatura.tipo == "manuscrita", seg.assinatura.detalhes
    v = _valores(seg)
    assert v["assinante_nome"] == "Maria das Graças Sousa"
    assert v["data_documento"] == "2026-10-01"


def test_ct28_sem_assinatura(motor, refs):
    _, seg = _rodar(F.png(F.renderizar(F.pdf_requerimento(F.DadosReq()))), motor, refs, "impresso.png")
    assert seg.assinatura.tipo == "ausente", seg.assinatura.detalhes


def test_ct29_pdf_assinado_digitalmente(pdf_exemplo, motor, refs):
    assinado = F.assinar_pdf_digitalmente(pdf_exemplo)
    res, seg = _rodar(assinado, motor, refs)
    assert res.leitura.metodo == "texto_nativo"
    assert seg.assinatura.tipo == "digital"
    info = seg.assinatura.detalhes["assinaturas"][0]
    assert "Teste Assinante" in info["assinante"]
    assert info.get("integra") is True


def test_ct30_qrcode(motor, refs):
    u = "6f1c2a3e-9b7d-4c1e-8f2a-1b2c3d4e5f60"
    pdf = F.pdf_requerimento(F.DadosReq(), qr_png=gerar_png(u, "a" * 64))
    res, seg = _rodar(pdf, motor, refs)
    assert seg.qrcodes and seg.qrcodes[0].processo_uuid == u
    assert seg.qrcodes[0].bruto == conteudo_padrao(u, "a" * 64)


def test_ct31_segunda_leitura_divergente():
    """Quando o recorte relido não confirma os dígitos, a confiança cai e a divergência fica registrada."""
    import numpy as np

    img = np.full((200, 900, 3), 255, np.uint8)
    cv2.putText(img, "-5 02 41.06", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 0), 5)
    pal = Palavra("-5°02'47.06\"", 90.0, (10, 50, 600, 140), 1)  # 1º OCR "leu" 47 em vez de 41
    pag = PaginaLida(1, 900, 200, agrupar_linhas([pal]), "ocr", img)
    campo = CampoBruto(pal.texto, [pal])
    conferir_campo_numerico(campo, {1: pag})
    assert campo.confianca <= 50 and "divergente" in campo.nota


def test_ct32_arquivo_invalido(motor, refs):
    with pytest.raises(ArquivoInvalido):
        processar_arquivo(b"isto nao e um documento", motor, refs, "notas.txt")


def test_ct33_area_decimal_e_cultura_composta(motor, refs):
    d = F.DadosReq(irrigacao=[("Gotejamento", "2,5", "Cana-de-açúcar"), ("Aspersão por sistema pivô central", "120", "Milho-verde")])
    _, seg = _rodar(F.pdf_requerimento(d), motor, refs)
    assert _irrigacao(seg) == [("Gotejamento", "2.5", "Cana-de-açúcar"), ("Aspersão por sistema pivô central", "120", "Milho-verde")]


def test_ct33b_tabela_decimal_por_ocr(motor, refs):
    d = F.DadosReq(irrigacao=[("Gotejamento", "2,5", "Cana-de-açúcar"), ("Aspersão por sistema pivô central", "120", "Milho-verde")])
    _, seg = _rodar(F.png(F.renderizar(F.pdf_requerimento(d))), motor, refs, "t.png")
    assert _irrigacao(seg) == [("Gotejamento", "2.5", "Cana-de-açúcar"), ("Aspersão por sistema pivô central", "120", "Milho-verde")]


def test_ct34_duas_finalidades(motor, refs):
    d = F.DadosReq(finalidades=["Irrigação", "Abastecimento Humano"])
    _, seg = _rodar(F.pdf_requerimento(d), motor, refs)
    assert [f.valor_normalizado for f in seg.resultado.finalidades] == ["Irrigação", "Abastecimento Humano"]
    assert len(seg.resultado.irrigacao) == 3
    assert seg.resultado.status == "extraido", seg.resultado.pendencias


def test_divisao_de_varios_requerimentos(motor, refs):
    pdf = F.pdf_requerimento(F.DadosReq(), F.DadosReq(nome="Ramon Teste"), F.DadosReq(municipio="Teresina"))
    res = processar_arquivo(pdf, motor, refs, "lote.pdf")
    assert len(res.segmentos) == 3
    assert res.segmentos[2].resultado.campos["municipio"].valor_normalizado == "Teresina"


def test_parser_sem_paragrafo_registra_aviso():
    pal = [Palavra("texto", 90, (0, 0, 50, 10)), Palavra("qualquer", 90, (60, 0, 120, 10))]
    ex = extrair(agrupar_linhas(pal))
    assert any("parágrafo principal" in a for a in ex.avisos)


def test_texto_atual_com_razao_social_e_carimbo_de_assinatura(motor, refs):
    """Modelo em uso desde set/2026: "município de X, localidade Y latitude ..." sem vírgula,
    coordenadas com S/W, requerente pessoa jurídica com nome em duas linhas no rodapé e
    assinatura digital com carimbo visível (Foxit) entre a tabela e o nome."""
    nome = "SECRETARIA DA IRRIGAÇÃO E INFRAESTRUTURA HÍDRICA – SEFIR"
    d = F.DadosReq(
        nome=nome, documento="22.911.207/0001-50", municipio="TERESINA", localidade="COMUNIDADE SAPÉ",
        latitude="05°06'30.47\"S", longitude="42°56'43.75\"W", texto_atual=True,
    )
    pdf = F.pdf_requerimento(d)
    x0, y0, x1, _ = F.bbox_texto_pdf(pdf, "SECRETARIA", dpi=72)
    assinado = F.assinar_pdf_digitalmente(pdf, carimbo=(x0 + 40, y0 - 55, x0 + 260, y0 - 8))
    res, seg = _rodar(assinado, motor, refs)
    v = _valores(seg)
    assert v["requerente_nome"] == nome
    assert v["cpf_cnpj"] == "22.911.207/0001-50"
    assert v["municipio"] == "Teresina"
    assert v["localidade"] == "COMUNIDADE SAPÉ"
    assert v["latitude"] == "-5.1084639" and v["longitude"] == "-42.9454861"
    assert v["assinante_nome"] == nome
    assert _irrigacao(seg) == IRRIGACAO_REAL
    assert not any("Assinado" in p.texto for pg in res.leitura.paginas for p in pg.palavras)
    assert seg.assinatura.tipo == "digital"


# ------------------------------------------------------------------ parágrafo fora do modelo (lido por partes)
def _linhas(texto: str, pagina: int = 1):
    """Linhas de texto nativo: uma palavra ao lado da outra, uma linha abaixo da outra."""
    pal = []
    for i, linha in enumerate(texto.strip().splitlines()):
        x = 0.0
        for w in linha.split():
            pal.append(Palavra(w, 100, (x, i * 20.0, x + 6 * len(w), i * 20.0 + 10), pagina))
            x += 6 * len(w) + 6
    return agrupar_linhas(pal)


def _bruto(ex):
    return {k: getattr(ex, k).valor for k in ("requerente_nome", "cpf_cnpj", "procedimento", "tipo_intervencao",
                                              "municipio", "localidade", "latitude", "longitude")}


def test_ct120_paragrafo_com_localidade_antes_do_municipio():
    ex = extrair(_linhas("""
REQUERIMENTO
A Secretaria do Saneamento Básico do Piauí, inscrito sob o CNPJ n° 22.057.819/0001-28, vem requerer
Autorização e Outorga Preventiva para perfuração de Poço Tubular na localidade Lagoa do Canto,
zona rural do município de Santo Antônio de Lisboa, Latitude 06°58'30.42"S e Longitude: 41°16'55.31"O.
Descrição dos usos da água
Captação subterrânea para abastecimento.
"""))
    assert _bruto(ex) == {
        "requerente_nome": "Secretaria do Saneamento Básico do Piauí", "cpf_cnpj": "22.057.819/0001-28",
        "procedimento": "Autorização e Outorga Preventiva para perfuração de Poço Tubular",
        "tipo_intervencao": "Poço Tubular", "municipio": "Santo Antônio de Lisboa", "localidade": "Lagoa do Canto",
        "latitude": "06°58'30.42\"S", "longitude": "41°16'55.31\"O",
    }
    assert any("por partes" in a for a in ex.avisos)


def test_ct121_carta_com_localizacao_do_poco_e_uf():
    """"inscrita no CNPJ sob nº", sede e poço em municípios diferentes, sem o rótulo "município"."""
    ex = extrair(_linhas("""
REQUERIMENTO
ILUSTRÍSSIMO(A) DIRETOR(A) DE RECURSOS HÍDRICOS DA SECRETARIA ESTADUAL DO MEIO AMBIENTE
TERESINA-PI
AGRO EXEMPLO LTDA., pessoa jurídica de direito privado, inscrita no CNPJ sob nº 11.222.333/0001-81, com
sede na Fazenda Boa Vista, S/N, Zona Rural de Palmeira do Piauí – PI, CEP: 64.925-000, vem requerer a
Autorização para Perfuração de Poço Tubular e Outorga Preventiva – AUTPOOP, para captação de água.
Localização do Poço:
Fazenda Boa Vista II, S/N, Zona Rural de Uruçuí – PI, CEP: 64.925-000.
Coordenadas Geográficas: Latitude 8°25′37,6833″S e Longitude 44°28′18,7389″W.
Descrição dos usos da água
Irrigação de soja.
"""))
    b = _bruto(ex)
    assert b["requerente_nome"] == "AGRO EXEMPLO LTDA" and b["cpf_cnpj"] == "11.222.333/0001-81"
    assert b["procedimento"] == "Autorização para Perfuração de Poço Tubular e Outorga Preventiva"
    assert b["tipo_intervencao"] == "Poço Tubular"
    assert b["municipio"] == "Uruçuí" and ex.municipio.confianca == 85  # o do poço, não o da sede
    assert b["localidade"] == "Fazenda Boa Vista II, S/N"
    assert b["latitude"] == "8°25′37,6833″S" and b["longitude"] == "44°28′18,7389″W"


def test_ct122_nome_quebrado_localidade_sem_rotulo_e_coordenada_sem_longitude():
    ex = extrair(_linhas("""
REQUERIMENTO
Distribuidora Exemplo Comércio e Representações Ltda-
Distribuidora Exemplo, inscrita sob o CNPJ n° 11.222.333/0001-81
vem requerer, a Autorização de Perfuração e Outorga Preventiva
de um poço tubular a ser localizado no município Teresina, na BR
316 km 23- Chapadinha, com as coordenadas geográficas: Latitude
05°17'39,95"S e 42°42'49,46"W.
"""))
    b = _bruto(ex)
    assert b["requerente_nome"] == "Distribuidora Exemplo Comércio e Representações Ltda- Distribuidora Exemplo"
    assert b["municipio"] == "Teresina" and b["tipo_intervencao"] == "poço tubular"
    assert b["localidade"] == "BR 316 km 23- Chapadinha" and ex.localidade.confianca == 75  # deduzida: conferir
    assert b["latitude"] == "05°17'39,95\"S" and b["longitude"] == "42°42'49,46\"W"


def test_ct123_pagina_seguinte_repete_o_titulo(motor, refs):
    """O SIGA repete "REQUERIMENTO" no topo de cada página: a segunda página continua o mesmo requerimento."""
    import pymupdf

    doc = pymupdf.open(stream=F.pdf_requerimento(F.DadosReq()), filetype="pdf")
    doc.new_page().insert_text((72, 72), "REQUERIMENTO\nCaracterísticas gerais do projeto: 57 pivôs centrais.")
    res = processar_arquivo(doc.tobytes(), motor, refs, "longo.pdf")
    assert len(res.segmentos) == 1 and [p.numero for p in res.segmentos[0].paginas] == [1, 2]
    assert res.segmentos[0].resultado.campos["municipio"].valor_normalizado == "Altos"


def test_ct124_finalidade_antes_da_descricao_e_titulo_na_mesma_linha():
    ex = extrair(_linhas("""
REQUERIMENTO
JOSÉ EXEMPLO, inscrito sob o CPF/CNPJ n° 529.982.247-25, vem requerer Regularização de Poço Tubular para
Poço Tubular localizado no município ALTOS, localidade SÍTIO NOVO, latitude -5°02'41.06" e longitude -42°27'32.38".
Finalidade do Uso - Consumo Animal
Espécie Sistema de Criação Número de Cabeças
Descrição dos usos da água
Dessedentação do rebanho.
JOSÉ EXEMPLO
01/10/2026
"""))
    assert [f.valor for f in ex.finalidades] == ["Consumo Animal"] and ex.blocos[0].chave == "criacao_animal"
    assert ex.descricao_usos.valor == "Dessedentação do rebanho" and ex.data_documento.valor == "01/10/2026"


def test_ct125_correspondencia_nome_incompleto_e_letras_espacadas():
    from ocr_requerimentos.extracao.texto import Ref, melhor_correspondencia

    muni = [Ref(1, "Betânia do Piauí"), Ref(2, "Capitão Gervásio Oliveira"), Ref(3, "São Raimundo Nonato"),
            Ref(4, "São João do Piauí"), Ref(5, "São João da Varjota")]
    assert melhor_correspondencia("Betânia", muni) == (muni[0], 85.0)
    assert melhor_correspondencia("CAPITÃO GERVÁSIO", muni) == (muni[1], 85.0)
    assert melhor_correspondencia("S Ã O R A I M U N D O N O N A T O", muni)[0] is muni[2]
    assert melhor_correspondencia("São João", muni)[0] is None  # completa dois nomes: não escolhe
