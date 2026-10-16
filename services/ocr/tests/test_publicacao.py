"""Publicação para o SIGA: JSON padrão por requerimento validado e consolidado (sem banco; o "bucket do
SIGA" é uma pasta temporária, SIGA_DESTINO_DIR)."""
import json
import uuid as _uuid

from ocr_requerimentos import publicacao
from ocr_requerimentos.modelos import Campo, LeituraOriginalOcr, Revisao, Validacao, agora

from test_repositorio import _doc, _salvar


def _validado(nome="Maria das Graças", justificativa=None):
    d = _doc(status="validado", nome=nome)
    d.requerimento.validacao = Validacao(situacao="validado", validado_por_id=7, validado_em=agora())
    d.requerimento.campos = [Campo(
        campo="latitude", valor_atual="-5°02'41.06\"", valor_atual_normalizado="-5.0447389", confianca_atual=100,
        corrigido_manualmente=True, leitura_original_ocr=LeituraOriginalOcr(valor_lido="-5°02'91.06\"", confianca_ocr=62),
    )]
    if justificativa:
        d.historico_de_revisoes.append(Revisao(tipo="validacao_com_pendencias", valor_anterior="Latitude: conferir",
                                               valor_novo=justificativa, usuario_id=7))
    return d


def _no_siga(u):
    caminho = publicacao.destino().raiz / publicacao.chave_requerimento(u)
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else None


def test_ct111_formato_padrao_do_siga(repo):
    d = _salvar(repo, _validado(justificativa="conferido em campo"))
    j = json.loads(publicacao.json_siga(d))
    assert j["schema"] == "semarh.ocr.requerimento" and j["schema_versao"] == 1
    f = j["formulario"]
    assert f["requerente"] == {"nome": "Maria das Graças", "cpf_cnpj": "059.749.653-61", "tipo_pessoa": None,
                               "id_siga": None}
    assert f["localizacao"]["municipio"]["nome"] == "Altos" and f["procedimento"]["nome"] == "Outorga Preventiva"
    campo = j["campos"][0]
    assert campo["valor_final"] == "-5°02'41.06\"" and campo["corrigido_manualmente"]
    assert campo["leitura_original_ocr"] == {"valor_lido": "-5°02'91.06\"", "confianca_ocr": 62.0}
    assert j["validacao"]["com_pendencias"] and j["validacao"]["justificativa"] == "conferido em campo"
    assert j["validacao"]["pendencias"] == ["Latitude: conferir"]
    assert "local_na_folha" not in json.dumps(j)  # posição e texto do OCR ficam só no JSON interno


def test_ct112_publica_ao_validar_e_retira_ao_desfazer(repo):
    pendente = _salvar(repo, _doc(status="revisao"))
    assert _no_siga(pendente.uuid) is None  # só validados vão para o SIGA
    d = _salvar(repo, _validado())
    assert _no_siga(d.uuid)["uuid"] == d.uuid
    with repo.travar(d.uuid):  # correção depois de validado: volta a pendente e sai do SIGA
        atual = repo.obter(d.uuid)
        atual.status = "extraido"
        atual.requerimento.validacao = Validacao()
        repo.salvar(atual)
    assert _no_siga(d.uuid) is None


def test_ct113_consolidado_so_com_validados_e_atualizado(repo):
    a = _salvar(repo, _validado(nome="Ana"))
    _salvar(repo, _doc(status="revisao"))
    b = _salvar(repo, _validado(nome="Bruno"))
    texto = b"".join(publicacao.consolidado(repo)).decode()
    j = json.loads(texto)
    assert j["schema"] == "semarh.ocr.requerimentos" and j["total"] == 2
    assert [r["uuid"] for r in j["requerimentos"]] == [a.uuid, b.uuid]  # do mais antigo ao mais novo
    # o arquivo do bucket do SIGA é o mesmo conteúdo, regerado depois das mudanças
    assert publicacao.gravar_consolidado(repo) == 2
    gravado = json.loads((publicacao.destino().raiz / publicacao.chave_consolidado()).read_text(encoding="utf-8"))
    assert [r["uuid"] for r in gravado["requerimentos"]] == [a.uuid, b.uuid]
    assert publicacao.situacao(repo)["consolidado_gerado_em"]


def test_ct127_consolidado_com_todos_os_lidos(repo):
    a = _salvar(repo, _validado(nome="Ana"))
    r = _salvar(repo, _doc(status="revisao"))
    _salvar(repo, _doc(status="desconsiderado"))
    _salvar(repo, _doc(status="erro").model_copy(update={"requerimento": None}))
    j = json.loads(b"".join(publicacao.consolidado(repo, ("extraido", "revisao", "validado"))).decode())
    assert j["total"] == 2 and [x["uuid"] for x in j["requerimentos"]] == [a.uuid, r.uuid]
    assert [x["validacao"]["validado_em"] is None for x in j["requerimentos"]] == [False, True]  # o não validado
    # o arquivo do bucket do SIGA continua só com os validados
    assert publicacao.gravar_consolidado(repo) == 1


def test_ct114_consolidado_vazio_e_em_blocos(repo, monkeypatch):
    assert json.loads(b"".join(publicacao.consolidado(repo)))["total"] == 0
    monkeypatch.setattr(publicacao, "BLOCO", 2)
    uuids = [_salvar(repo, _validado(nome=f"P{i}")).uuid for i in range(5)]
    j = json.loads(b"".join(publicacao.consolidado(repo)))
    assert j["total"] == 5 and [r["uuid"] for r in j["requerimentos"]] == uuids


def test_ct115_publicacao_desligada_nao_grava(repo, tmp_path):
    d = _salvar(repo, _validado())
    assert publicacao.publicar_documento(d.uuid, repo, dest=None) in ("publicado", "desligada")
    from ocr_requerimentos.armazenamento import ArmazenamentoLocal

    outro = ArmazenamentoLocal(str(tmp_path))
    assert publicacao.publicar_documento(str(_uuid.uuid4()), repo, dest=outro) == "removido"
