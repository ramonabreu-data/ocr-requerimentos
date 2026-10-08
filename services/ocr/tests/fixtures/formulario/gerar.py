"""Gera PDFs reais no formulário público https://aguas.semarh.pi.gov.br/ a partir de JSONs de cenário."""
import http.cookiejar
import json
import re
import sys
import time
import urllib.request

BASE = "https://aguas.semarh.pi.gov.br"


def sessao():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    html = op.open(BASE + "/").read().decode()
    token = re.search(r'csrf-token" content="([^"]+)"', html).group(1)
    return op, token


def gerar(op, token, dados: dict) -> bytes:
    req = urllib.request.Request(
        BASE + "/requerimentos/gerar-pdf", data=json.dumps(dados).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-CSRF-TOKEN": token, "Accept": "application/pdf",
                 "X-Requested-With": "XMLHttpRequest"},
    )
    r = op.open(req)
    corpo = r.read()
    if not corpo.startswith(b"%PDF"):
        raise RuntimeError(f"resposta não é PDF: {corpo[:300]!r}")
    return corpo


if __name__ == "__main__":
    # uso: gerar.py cenarios.json pasta_saida
    cenarios = json.load(open(sys.argv[1]))
    saida = sys.argv[2]
    op, token = sessao()
    for nome, dados in cenarios.items():
        pdf = gerar(op, token, dados)
        open(f"{saida}/{nome}.pdf", "wb").write(pdf)
        print(nome, len(pdf))
        time.sleep(1)
