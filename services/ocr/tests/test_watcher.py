import pytest

import fabrica as F

pytestmark = pytest.mark.db


def test_ct60_e_ct61_pasta_monitorada(limpar, tmp_path):
    from ocr_requerimentos.watcher import varrer

    arq = tmp_path / "scan001.pdf"
    arq.write_bytes(F.pdf_requerimento(F.DadosReq())[:500])  # cópia em andamento
    tamanhos = {}
    assert varrer(tmp_path, tamanhos) == []  # CT-61: primeira vez só registra o tamanho
    arq.write_bytes(F.pdf_requerimento(F.DadosReq()))  # cópia terminou, tamanho mudou
    assert varrer(tmp_path, tamanhos) == []  # CT-61: ainda instável
    ids = varrer(tmp_path, tamanhos)  # CT-60: estável -> registra
    assert len(ids) == 1
    assert not arq.exists()
    assert list((tmp_path / "processados").rglob("scan001.pdf"))
    assert limpar.obter(ids[0]).status == "extraido"
    total, lotes = limpar.listar_lotes(1, 10)
    assert total == 1 and lotes[0].origem == "pasta_monitorada" and lotes[0].nome.startswith("Pasta monitorada")
    assert limpar.contagem_lote(lotes[0].uuid) == {"extraido": 1}
    assert limpar.obter(ids[0]).lote_uuids() == [lotes[0].uuid]
