"""Repositório de JSON (bucket) + índice no Redis: contrato, travas, concorrência, filtros e reconstrução.
Rodam sem banco e sem OCR (armazenamento em pasta temporária, Redis em memória)."""
import json
import threading
import uuid as _uuid
from datetime import date

import pytest
from pydantic import ValidationError

from ocr_requerimentos.ferramentas import acuracia, carga_sintetica, gravar_json_schema
from ocr_requerimentos.modelos import (
    ArquivoOriginal,
    Campo,
    Documento,
    LeituraOriginalOcr,
    Lote,
    Requerimento,
    Validacao,
    VinculoLote,
    agora,
)
from ocr_requerimentos.pipeline import persistencia as P


def _doc(lote=None, status="extraido", nome="Maria das Graças", cpf="059.749.653-61", municipio="Altos",
         procedimento="Outorga Preventiva", data=date(2026, 10, 1), arquivo="a.pdf"):
    u = str(_uuid.uuid4())
    return Documento(
        uuid=u, status=status,
        arquivo=ArquivoOriginal(nome_original=arquivo, chave=f"documentos/{u}/original.pdf",
                                content_type="application/pdf", tamanho_bytes=1, sha256=_uuid.uuid4().hex * 2),
        lote_origem_uuid=lote, lotes=[VinculoLote(lote_uuid=lote)] if lote else [],
        requerimento=Requerimento(requerente_nome=nome, cpf_cnpj=cpf, municipio=municipio, procedimento=procedimento,
                                  data_documento=data),
    )


def _salvar(repo, doc):
    with repo.travar(doc.uuid):
        return repo.salvar(doc)


def _mudar_status(repo, u, status):
    with repo.travar(u):
        d = repo.obter(u)
        d.status = status
        return repo.salvar(d)


# ------------------------------------------------------------------ contrato
def test_ct100_json_gravado_com_nomes_explicitos(repo):
    d = _doc()
    d.requerimento.campos.append(Campo(
        campo="latitude", valor_atual="-5°02'41.06\"", valor_atual_normalizado="-5.0447389", confianca_atual=100,
        corrigido_manualmente=True,
        leitura_original_ocr=LeituraOriginalOcr(valor_lido="-5°02'91.06\"", confianca_ocr=71.5),
    ))
    _salvar(repo, d)
    gravado = json.loads(repo.store.ler(f"dados/documentos/{d.uuid}.json"))
    lat = gravado["requerimento"]["campos"][0]
    assert lat["leitura_original_ocr"] == {"valor_lido": "-5°02'91.06\"", "confianca_ocr": 71.5}
    assert lat["valor_atual"] == "-5°02'41.06\"" and lat["confianca_atual"] == 100 and lat["corrigido_manualmente"]
    assert gravado["schema_versao"] == 1 and "historico_de_revisoes" in gravado
    assert "Graças" in repo.store.ler(f"dados/documentos/{d.uuid}.json").decode("utf-8")  # UTF-8 legível
    assert repo.obter(d.uuid).requerimento.campos[0].leitura_original_ocr.confianca_ocr == 71.5


def test_ct101_contrato_recusa_dados_invalidos(repo):
    with pytest.raises(ValidationError):
        Requerimento(cpf_cnpj="059.749.653-6l")
    with pytest.raises(ValidationError):
        Requerimento(confianca_geral=100.5)
    with pytest.raises(ValidationError):
        Validacao(situacao="validado")
    with pytest.raises(ValidationError):
        Documento.model_validate({**_doc().model_dump(), "campo_que_nao_existe": 1})
    d = _salvar(repo, _doc())
    d.status = "qualquer"
    with pytest.raises(ValidationError), repo.travar(d.uuid):
        repo.salvar(d)
    assert repo.obter(d.uuid).status == "extraido"


def test_ct102_json_schema_publicado(tmp_path):
    arquivos = gravar_json_schema(tmp_path)
    schema = json.loads((tmp_path / "documento.schema.json").read_text(encoding="utf-8"))
    assert [p.name for p in arquivos] == ["documento.schema.json", "paginas.schema.json", "lote.schema.json",
                                          "siga-requerimento.schema.json", "siga-requerimentos.schema.json"]
    siga = json.loads((tmp_path / "siga-requerimento.schema.json").read_text(encoding="utf-8"))
    assert {"schema", "formulario", "campos", "validacao"} <= set(siga["properties"])
    assert "leitura_original_ocr" in schema["$defs"]["Campo"]["properties"]
    assert "Texto lido pelo OCR" in json.dumps(schema, ensure_ascii=False)


# ------------------------------------------------------------------ travas e concorrência
def test_ct103_trava_evita_atualizacao_perdida(repo):
    d = _salvar(repo, _doc())
    erros = []

    def corrigir(i):
        try:
            with repo.travar(d.uuid):
                atual = repo.obter(d.uuid)
                atual.historico_de_revisoes.append(P.Revisao(tipo="correcao", campo="localidade", valor_novo=str(i)))
                repo.salvar(atual)
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    threads = [threading.Thread(target=corrigir, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not erros
    assert len(repo.obter(d.uuid).historico_de_revisoes) == 12  # nenhuma gravação sobrescreveu outra


def test_ct104_mesmo_arquivo_enviado_ao_mesmo_tempo(repo):
    lote = Lote(uuid=str(_uuid.uuid4()), origem="upload")
    repo.salvar_lote(lote)
    resultados = []

    def enviar():
        resultados.append(P.registrar_documento(b"%PDF-1.4 mesmo arquivo", "a.pdf", "application/pdf",
                                                lote_uuid=lote.uuid, repo=repo))

    threads = [threading.Thread(target=enviar) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({r.documento.uuid for r in resultados}) == 1
    assert sorted(r.duplicado for r in resultados) == [False] + [True] * 7
    assert repo.contagem_lote(lote.uuid) == {"recebido": 1}
    assert len(list(repo.documentos_no_bucket())) == 1


def test_ct105_versao_antiga_recusada(repo):
    d = _salvar(repo, _doc())
    v = d.requerimento.versao
    P.conferir_versao(d.requerimento, v)
    P.conferir_versao(d.requerimento, None)  # clientes sem versão continuam aceitos
    with pytest.raises(P.ConflitoVersao):
        P.conferir_versao(d.requerimento, v - 1)


# ------------------------------------------------------------------ índice
def test_ct106_contadores_do_lote_acompanham_a_situacao(repo):
    a, b = str(_uuid.uuid4()), str(_uuid.uuid4())
    for u in (a, b):
        repo.salvar_lote(Lote(uuid=u, origem="upload"))
    d1 = _salvar(repo, _doc(a, status="recebido"))
    _salvar(repo, _doc(a, status="recebido"))
    assert repo.contagem_lote(a) == {"recebido": 2} and repo.finalizado_em(a) is None
    _mudar_status(repo, d1.uuid, "revisao")
    # o mesmo documento entra no lote b (reenvio): conta nos dois
    P.vincular_lote(b, d1.uuid, "reenvio.pdf", repo=repo)
    assert repo.contagem_lote(a) == {"recebido": 1, "revisao": 1}
    assert repo.contagem_lote(b) == {"revisao": 1} and repo.finalizado_em(b)
    _mudar_status(repo, d1.uuid, "validado")
    assert repo.contagem_lote(a) == {"recebido": 1, "validado": 1} and repo.contagem_lote(b) == {"validado": 1}


def test_ct107_filtros_e_paginacao(repo):
    docs = [
        _salvar(repo, _doc(nome="José Pereira Lima", municipio="Teresina", procedimento="Outorga de Direito de Uso",
                           data=date(2026, 9, 15), arquivo="b.pdf")),
        _salvar(repo, _doc(nome="João da Silva", municipio="Teresina", data=date(2026, 10, 3), arquivo="c.pdf",
                           status="revisao")),
        _salvar(repo, _doc(arquivo="a.pdf")),
        _salvar(repo, _doc(arquivo="d.pdf", status="dividido")),
    ]
    total, itens = repo.consultar()
    assert total == 3 and [i["nome_original"] for i in itens] == ["a.pdf", "c.pdf", "b.pdf"]  # mais novo primeiro
    assert repo.consultar(municipio="Teresina")[0] == 2
    assert repo.consultar(municipio="Teresina", procedimento="Outorga de Direito de Uso")[0] == 1
    assert repo.consultar(status=["revisao"])[0] == 1
    assert repo.consultar(status=["revisao", "extraido"])[0] == 3
    assert repo.consultar(status=["dividido"])[0] == 0  # dividido só agrupa as partes
    total, itens = repo.consultar(filtro=lambda r: "jose" in r["_requerente"])
    assert total == 1 and itens[0]["nome_original"] == "b.pdf"
    total, pag2 = repo.consultar(pagina=2, tamanho=2)
    assert total == 3 and [i["nome_original"] for i in pag2] == ["b.pdf"]
    total, pag2 = repo.consultar(filtro=lambda r: True, pagina=2, tamanho=2, bloco=1)  # varredura em blocos
    assert total == 3 and [i["nome_original"] for i in pag2] == ["b.pdf"]
    assert repo.opcoes("mun") == [{"nome": "Altos", "total": 1}, {"nome": "Teresina", "total": 2}]
    assert repo.por_status() == {"extraido": 2, "revisao": 1, "dividido": 1}
    # mudar o município numa correção atualiza as opções de filtro
    with repo.travar(docs[0].uuid):
        d = repo.obter(docs[0].uuid)
        d.requerimento.municipio = "Altos"
        repo.salvar(d)
    assert repo.opcoes("mun") == [{"nome": "Altos", "total": 2}, {"nome": "Teresina", "total": 1}]
    assert not repo.r.keys("ocr:tmp:*")  # conjuntos temporários das consultas são apagados


def test_ct108_reconstruir_indice_a_partir_do_bucket(repo):
    lote = str(_uuid.uuid4())
    repo.salvar_lote(Lote(uuid=lote, nome="Malote", origem="zip"))
    for status in ("extraido", "revisao", "validado", "erro"):
        _salvar(repo, _doc(lote, status=status, municipio="Picos"))
    antes = (repo.consultar(), repo.contagem_lote(lote), repo.opcoes("mun"), repo.por_status(), repo.listar_lotes(1, 5))
    fim_antes = repo.finalizado_em(lote)
    repo.r.flushall()  # Redis perdido
    assert repo.consultar()[0] == 0
    assert repo.reconstruir_indice() == {"lotes": 1, "documentos": 4}
    depois = (repo.consultar(), repo.contagem_lote(lote), repo.opcoes("mun"), repo.por_status(), repo.listar_lotes(1, 5))
    assert depois == antes and repo.finalizado_em(lote) and fim_antes


def test_ct109_carga_sintetica(repo):
    res = carga_sintetica(repo, 450, por_lote=200, paralelismo=8)
    assert res["documentos"] == 450 and res["lotes"] == 3
    consultas = {c["consulta"]: c for c in res["consultas_ms"]}
    assert consultas["lista geral, página 1"]["total"] == 450
    assert sum(repo.contagem_lote(u).get("erro", 0) for u in repo.r.zrange("ocr:lotes", 0, -1)) == \
        repo.consultar(status=["erro"])[0]


def test_ct110_acuracia_sobre_validados():
    def campo(nome, lido, conf, corrigido=False, valor=None):
        return Campo(campo=nome, valor_atual=valor or lido, valor_atual_normalizado=valor or lido,
                     confianca_atual=100 if corrigido else conf, corrigido_manualmente=corrigido,
                     leitura_original_ocr=LeituraOriginalOcr(valor_lido=lido, confianca_ocr=conf) if lido else None)

    validado = _doc(status="validado")
    validado.leitura.versao_pipeline = "1.0.0"
    validado.requerimento.validacao = Validacao(situacao="validado", validado_em=agora())
    validado.requerimento.campos = [
        campo("latitude", "-5°02'91", 62, corrigido=True, valor="-5°02'41"),
        campo("municipio", "Altos", 95),
        campo("localidade", None, None, corrigido=True, valor="Sede"),  # incluído na revisão
    ]
    pendente = _doc()
    pendente.leitura.versao_pipeline = "1.0.0"
    pendente.requerimento.campos = [campo("municipio", "Altos", 95, corrigido=True, valor="Teresina")]
    campos, faixas = acuracia([validado, pendente])
    por = {c["campo"]: c for c in campos}
    assert por["latitude"]["pct_acerto"] == 0 and por["municipio"]["pct_acerto"] == 100
    assert por["localidade"]["nao_lidos"] == 1 and por["municipio"]["conferidos"] == 1  # o pendente não conta
    assert {f["faixa_confianca"]: f["corrigidos"] for f in faixas} == {"50-69": 1, "90-100": 0}
