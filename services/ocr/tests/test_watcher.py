import pytest

import fabrica as F

pytestmark = pytest.mark.db


def test_ct60_e_ct61_pasta_monitorada(limpar, tmp_path):
    from sqlalchemy import select

    from ocr_requerimentos.modelos import Documento, Lote, sessao
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
    with sessao() as s:
        doc = s.get(Documento, ids[0])
        assert doc.status == "extraido"
        lote = s.scalar(select(Lote))
        assert lote.origem == "pasta_monitorada" and lote.nome.startswith("Pasta monitorada")
        assert lote.total == 1
