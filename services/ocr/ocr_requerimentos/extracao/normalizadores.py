"""Normalização de campos com correção de erros típicos de OCR."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

# Confusões de OCR em campos que só podem ter dígitos
_PARA_DIGITO = str.maketrans({
    "o": "0", "O": "0", "D": "0", "Q": "0", "U": "0",
    "i": "1", "I": "1", "l": "1", "|": "1", "!": "1", "L": "1",
    "z": "2", "Z": "2",
    "s": "5", "S": "5",
    "b": "6", "G": "6",
    "T": "7",
    "B": "8",
    "g": "9", "q": "9",
})


def corrigir_digitos(s: str) -> str:
    return (s or "").translate(_PARA_DIGITO)


# ---------------------------------------------------------------- CPF / CNPJ
@dataclass
class DocumentoPessoa:
    digitos: str
    tipo: str | None  # F | J | None
    valido: bool
    formatado: str | None
    mensagem: str | None = None


def _dv_cpf(base: str) -> str:
    d1 = (sum(int(c) * p for c, p in zip(base, range(10, 1, -1))) * 10) % 11 % 10
    d2 = (sum(int(c) * p for c, p in zip(base + str(d1), range(11, 1, -1))) * 10) % 11 % 10
    return f"{d1}{d2}"


def _dv_cnpj(base: str) -> str:
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    p2 = [6, *p1]
    r1 = sum(int(c) * p for c, p in zip(base, p1)) % 11
    d1 = 0 if r1 < 2 else 11 - r1
    r2 = sum(int(c) * p for c, p in zip(base + str(d1), p2)) % 11
    d2 = 0 if r2 < 2 else 11 - r2
    return f"{d1}{d2}"


def normalizar_cpf_cnpj(bruto: str | None) -> DocumentoPessoa:
    digitos = re.sub(r"\D", "", corrigir_digitos(bruto or ""))
    if len(digitos) == 11:
        valido = len(set(digitos)) > 1 and _dv_cpf(digitos[:9]) == digitos[9:]
        fmt = f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
        return DocumentoPessoa(digitos, "F", valido, fmt, None if valido else "CPF com dígito verificador inválido")
    if len(digitos) == 14:
        valido = len(set(digitos)) > 1 and _dv_cnpj(digitos[:12]) == digitos[12:]
        fmt = f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
        return DocumentoPessoa(digitos, "J", valido, fmt, None if valido else "CNPJ com dígito verificador inválido")
    return DocumentoPessoa(digitos, None, False, None, f"esperado CPF (11) ou CNPJ (14 dígitos), lido {len(digitos)}")


# ---------------------------------------------------------------- números
def normalizar_numero(bruto: str | None) -> float | None:
    """'10' -> 10.0 ; '2,5' -> 2.5 ; '1.234,56' -> 1234.56 ; '1O' -> 10.0"""
    if not bruto:
        return None
    original = re.sub(r"[\s.,]", "", bruto)
    if not original or sum(c.isdigit() for c in original) * 2 < len(original):
        return None  # texto, não número (evita 'abc' -> 6)
    s = corrigir_digitos(bruto.strip()).replace(" ", "")
    s = re.sub(r"[^0-9.,]", "", s)
    if not s or not re.search(r"\d", s):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parece_numero(bruto: str) -> bool:
    s = bruto.strip()
    if not s or len(s) > 12:
        return False
    convertido = corrigir_digitos(s)
    return bool(re.fullmatch(r"\d[\d.,]*", convertido)) and sum(c.isdigit() for c in s) >= max(1, len(s) // 2)


# ---------------------------------------------------------------- datas
def normalizar_data(bruto: str | None) -> date | None:
    if not bruto:
        return None
    s = corrigir_digitos(bruto)
    iso = re.search(r"(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})", s)  # 2033-06-04 (campo de data do formulário)
    m = re.search(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})", s)
    if iso and not m:
        a, mth, d = (int(x) for x in iso.groups())
    elif m:
        d, mth, a = (int(x) for x in m.groups())
    else:
        return None
    try:
        return date(a, mth, d)
    except ValueError:
        return None


# ---------------------------------------------------------------- coordenadas
@dataclass
class Coordenada:
    decimal: float | None
    graus: float | None = None
    minutos: float | None = None
    segundos: float | None = None
    erros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def valida(self) -> bool:
        return self.decimal is not None and not self.erros


AVISO_SINAL_AUSENTE = "sinal negativo ausente; assumido Sul/Oeste"


def normalizar_coordenada(bruto: str | None, eixo: str) -> Coordenada:
    """Converte graus/minutos/segundos (ou graus decimais) para decimal.

    eixo = 'lat' ou 'lon'. O Piauí fica inteiro nos hemisférios Sul e Oeste, então um sinal
    negativo perdido pelo OCR é recolocado, com aviso."""
    if not bruto or not bruto.strip():
        return Coordenada(None, erros=["coordenada não encontrada"])
    s = bruto.strip().rstrip(".;,")
    negativo = s[:1] in "-–—~"
    letra = None
    m_hem = re.search(r"(?:^|[\s\d\"'”″’])([NSEWLO])$", s.upper()) or re.match(r"^([NSEWLO])\s", s.upper())
    if m_hem:
        letra = m_hem.group(1)
        s = s[: m_hem.start(1)] + s[m_hem.end(1):]

    # símbolo de grau lido como o, º ou *; separadores lidos como ’ ` ´ ” ″
    s = re.sub(r"(?<=\d)\s*[oº*°]\s*", "°", s)
    tokens = re.findall(r"[\dOoIlSsBZz]+(?:[.,][\dOoIlSsBZz]+)?", s)
    numeros = []
    for t in tokens:
        if not any(c.isdigit() for c in t):
            continue
        try:
            numeros.append(float(corrigir_digitos(t).replace(",", ".")))
        except ValueError:
            pass

    coord = Coordenada(None)
    if not numeros:
        coord.erros.append(f"nenhum número reconhecido em '{bruto.strip()}'")
        return coord
    if len(numeros) >= 3:
        g, m, seg = numeros[:3]
    elif len(numeros) == 2:
        g, m, seg = numeros[0], numeros[1], 0.0
    else:
        g, m, seg = numeros[0], 0.0, 0.0
    coord.graus, coord.minutos, coord.segundos = g, m, seg

    limite_graus = 90 if eixo == "lat" else 180
    if g > limite_graus:
        coord.erros.append(f"graus ({g:g}) acima de {limite_graus}")
    if m >= 60:
        coord.erros.append(f"minutos ({m:g}) fora do intervalo 0–59")
    if seg >= 60:
        coord.erros.append(f"segundos ({seg:g}) fora do intervalo 0–59,99")
    if (m or seg) and not float(g).is_integer():
        coord.erros.append("graus com casas decimais junto com minutos/segundos")

    valor = g + m / 60 + seg / 3600
    if letra in ("N", "E", "L"):
        coord.avisos.append("hemisfério Norte/Leste informado; o Piauí fica no Sul/Oeste")
    elif negativo or letra in ("S", "W", "O"):
        valor = -valor
    else:
        coord.avisos.append(AVISO_SINAL_AUSENTE)
        valor = -valor
    coord.decimal = round(valor, 7)
    return coord


# Envelope aproximado do Piauí (SIRGAS 2000). A checagem fina é feita no banco (ST_Contains).
LIMITES_PI = {"lat": (-10.95, -2.70), "lon": (-45.99, -40.35)}


def dentro_do_piaui(lat: float, lon: float) -> bool:
    (la0, la1), (lo0, lo1) = LIMITES_PI["lat"], LIMITES_PI["lon"]
    return la0 <= lat <= la1 and lo0 <= lon <= lo1
