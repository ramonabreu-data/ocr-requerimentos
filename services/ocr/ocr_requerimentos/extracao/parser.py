"""Parser do modelo de REQUERIMENTO baseado em âncoras de texto.

Trabalha sobre linhas visuais (texto nativo ou OCR) e devolve os trechos encontrados junto
com as palavras de origem, para calcular confiança e desenhar a caixa na tela de revisão.
As expressões rodam sobre uma cópia minúscula e sem acentos do texto, com o mesmo comprimento,
e os valores são recortados do texto original (preservando acentos e caixa)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from statistics import median

from rapidfuzz import fuzz

from .finalidades import POR_CHAVE, FinalidadeDef, casa_cabecalho, definicao_por_titulo
from .normalizadores import parece_numero
from .texto import chave, normalizar_paralelo, proporcao_letras
from .tipos import CampoBruto, Linha, Palavra, uniao_bbox


@dataclass
class LinhaIrrigacao:
    sistema: CampoBruto
    area: CampoBruto
    cultura: CampoBruto
    texto_linha: str


@dataclass
class BlocoFinalidade:
    """Uma finalidade da seção "Finalidade(s) do Uso da Água" com os dados que vêm abaixo do título."""

    titulo: CampoBruto
    definicao: FinalidadeDef | None
    valores: dict[str, CampoBruto] = field(default_factory=dict)  # campos "Rótulo: valor"
    linhas: list[dict[str, CampoBruto]] = field(default_factory=list)  # tabela, lista ou pares
    tem_linhas: bool = False  # cabeçalho da tabela/lista encontrado

    @property
    def chave(self) -> str | None:
        return self.definicao.chave if self.definicao else None


@dataclass
class ExtracaoBruta:
    requerente_nome: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    cpf_cnpj: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    procedimento: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    tipo_intervencao: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    municipio: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    localidade: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    latitude: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    longitude: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    descricao_usos: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    finalidades: list[CampoBruto] = field(default_factory=list)
    blocos: list[BlocoFinalidade] = field(default_factory=list)
    irrigacao: list[LinhaIrrigacao] = field(default_factory=list)
    tem_tabela_irrigacao: bool = False
    assinante_nome: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    data_documento: CampoBruto = field(default_factory=lambda: CampoBruto(None))
    linha_assinante: Linha | None = None
    avisos: list[str] = field(default_factory=list)
    texto: str = ""


class TextoMapeado:
    """Texto contínuo (linhas separadas por \\n) com mapa de caractere -> palavra."""

    def __init__(self, linhas: list[Linha]):
        self.linhas = linhas
        partes: list[str] = []
        self.intervalos: list[tuple[int, int, Palavra]] = []
        self.inicio_linha: list[int] = []
        pos = 0
        for i, linha in enumerate(linhas):
            if i:
                partes.append("\n")
                pos += 1
            self.inicio_linha.append(pos)
            for j, p in enumerate(linha.palavras):
                if j:
                    partes.append(" ")
                    pos += 1
                partes.append(p.texto)
                self.intervalos.append((pos, pos + len(p.texto), p))
                pos += len(p.texto)
        self.texto = "".join(partes)
        self.norm = normalizar_paralelo(self.texto)

    def campo(self, a: int, b: int, limpar: str = " ,.;:\n") -> CampoBruto:
        trecho = self.texto[a:b]
        # ajusta o intervalo para descartar pontuação das bordas
        esq = len(trecho) - len(trecho.lstrip(limpar))
        trecho = trecho.strip(limpar)
        a2 = a + esq
        b2 = a2 + len(trecho)
        palavras = [p for (i, f, p) in self.intervalos if i < b2 and f > a2]
        valor = re.sub(r"\s+", " ", trecho).strip() or None
        return CampoBruto(valor, palavras)

    def linha_do_indice(self, idx: int) -> int:
        n = 0
        for i, ini in enumerate(self.inicio_linha):
            if ini <= idx:
                n = i
            else:
                break
        return n


# Âncoras toleram ruído de OCR: letras trocadas, espaços sobrando, símbolos lidos errado.
RE_PARAGRAFO = re.compile(
    r"(?P<nome>[^\n]*?(?:\n[^\n]*?)?)\s*,?\s*inscrit\w*\s+so\w\s+o\s+"
    r"c\W?p\W?f\s*[/|l1i]?\s*c\W?n\W?p\W?j\s*n?\S{0,3}\s*"
    r"(?P<doc>[0-9oilszb.\-/ ]{11,24}?)\s*[,.]\s*"
    r"vem\s+requer\w*\s+(?P<proc>.+)\s+para\s+(?P<interv>(?:(?!\s+para\s).)+?)\s+"
    # "município de X" ou "município X"; a vírgula antes de "localidade"/"latitude" nem sempre vem
    r"localizad\w\s+n\w\s+munic\w*\s+(?:d[aeo]\s+)?(?P<mun>.+?)\s*[,.]?\s*\blocalidade\s+(?P<loc>.+?)\s*[,.]?\s*"
    r"\blatitude\s*:?\s*(?P<lat>.+?)\s+e\s+longitude\s*:?\s*(?P<lon>[-–—~]?\s*[0-9oilszb][^\n]*|[^\n]+)",
    re.DOTALL,
)
RE_TITULO = re.compile(r"r\s*e\s*q\s*u\s*e\s*r\s*i\s*m\s*e\s*n\s*t\s*o")
RE_DESCRICAO = re.compile(r"descri\w*\s+dos\s+usos\s+da\s+[aá]gua")
# cabeçalho no começo da linha; "da Água" às vezes falta ("Finalidade do Uso - Consumo Animal")
RE_FINALIDADE = re.compile(r"(?m)^[^\w\n]{0,3}finalidade\s*[\(\[]?\s*s?\s*[\)\]]?\s+do\s+uso(?:\s+da\s+[aá]gua)?")
RE_CAB_TABELA = re.compile(r"sistema\s+de\s+irriga")
RE_DATA = re.compile(r"\b[0-9oil]{1,2}\s*/\s*[0-9oil]{1,2}\s*/\s*[0-9oil]{4}\b")
# início do parágrafo do requerente: distingue a primeira página de um requerimento de uma página seguinte
# que só repete o cabeçalho "REQUERIMENTO"
RE_INICIO_PARAGRAFO = re.compile(r"vem\s+requer|inscrit\w*\s+(?:so\w|n[oa])\s")

# ---- leitura do parágrafo por partes, quando o texto foge do modelo (ordem trocada, trechos a mais ou a menos)
RE_VEM_REQUERER = re.compile(r"vem\s*,?\s+requer\w*\s*,?\s*(?:(?:a|o)\s+(?=\S))?")
RE_FIM_NOME = re.compile(
    r"\s*,?\s*(?:inscrit\w*|pessoa\s+(?:jur|f\w?s)\w*|brasileir\w*|portador\w*|residente|com\s+sede|"
    r"c\W?p\W?f\b|c\W?n\W?p\W?j\b)"
)
RE_DOC_ROTULO = re.compile(r"(?:c\W?p\W?f\s*[/|l1i]?\s*)?c\W?n\W?p\W?j|c\W?p\W?f")
RE_DOC_VALOR = re.compile(
    r"[\s:]*(?:sob\s+)?(?:o\s+)?(?:(?:n|numero)\s*[°º.o]?\s*:?\s+|n[°º.]\s*)?(?:sob\s+)?"
    r"(?P<doc>[0-9][0-9oilszb.\-/ \n]*[0-9oilszb]|[0-9])"
)
RE_SAUDACAO = re.compile(r"ilustr|exm|senhor|diretor|secretari\w*\s*\(|teresina\s*[-–—]\s*pi")
RE_MUNICIPIO = re.compile(r"\bmunic[i]pio\s*(?:\(s\)\s*)?:?\s*(?:d[aeo]\s+)?")
RE_LOCALIDADE = re.compile(r"\blocalidade\s*:?\s*(?:rural\s+)?(?:d[aeo]\s+)?|\blocaliza\w*\s+do\s+po[c]o\s*:?\s*")
RE_LATITUDE = re.compile(
    r"\blatitude\s*:?\s*(?P<lat>[^\n]{1,40}?(?:\n[^\n]{0,40}?)?)\s*,?\s+e\s+(?:(?:a\s+)?longitude\s*:?\s*)?"
    r"(?P<lon>[-–—~]?\s*[0-9oilszb][^\n]*)"
)
# onde terminam município e localidade
_FIM_LOCAL = (r"\s*,?\s*(?:zona\s+rural|(?:d|n)[oa]\s+munic|munic[i]pio|(?:com\s+as\s+)?coordenadas|latitude|cep\b)"
              r"|\s*[-–—/]\s*pi\b|\s*[.;](?:\s|$)")
RE_FIM_MUNICIPIO = re.compile(r"\s*,|\s+(?:n[ao]\s+)?localidade|" + _FIM_LOCAL)
RE_FIM_LOCALIDADE = re.compile(_FIM_LOCAL)
RE_FIM_PROCEDIMENTO = re.compile(
    r"\s+para\s+(?:a\s+)?(?:perfura|po[c]o|capta|barrament|lan[c]ament|dilui)|\s+(?:n[ao]|em)\s+localidade|"
    r"\s+(?:a\s+s\s*e\s*r\s+)?localizad|\s+(?:d[oe]|de\s+um|em\s+um)\s+po[c]o|\s*[,.;]"
)
CONF_INFERIDO = 75.0  # valor deduzido do contexto (sem o rótulo do formulário): vai para a conferência


def _nomes_padrao(tipo: str) -> list[str]:
    from .. import dados_referencia as dr

    return {
        "procedimentos": dr.PROCEDIMENTOS,
        "intervencoes": [*dr.ASSUNTOS, "Poço Amazonas", "Barramento", "Lançamento de Efluentes"],
        "municipios": dr.MUNICIPIOS_PI,
    }[tipo]


def extrair(
    linhas: list[Linha],
    nome_esperado: str | None = None,
    titulos_extra: list[str] | None = None,
    procedimentos: list[str] | None = None,
    intervencoes: list[str] | None = None,
    municipios: list[str] | None = None,
) -> ExtracaoBruta:
    """`titulos_extra`: nomes de finalidade do SIGA aceitos como título além dos do formulário.
    `procedimentos`, `intervencoes`, `municipios`: nomes das listas do SIGA, usados para ler o parágrafo do
    requerente quando ele foge do modelo (sem elas, valem as listas do formulário)."""
    tm = TextoMapeado(linhas)
    ex = ExtracaoBruta(texto=tm.texto)
    norm = tm.norm

    inicio = 0
    m_titulo = RE_TITULO.search(norm)
    if m_titulo:
        inicio = m_titulo.end()
    else:
        ex.avisos.append("título REQUERIMENTO não encontrado")

    m = RE_PARAGRAFO.search(norm, inicio)
    if m:
        ex.requerente_nome = tm.campo(*m.span("nome"))
        ex.cpf_cnpj = tm.campo(*m.span("doc"))
        ex.procedimento = tm.campo(*m.span("proc"))
        ex.tipo_intervencao = tm.campo(*m.span("interv"))
        ex.municipio = tm.campo(*m.span("mun"))
        ex.localidade = tm.campo(*m.span("loc"))
        ex.latitude = tm.campo(*m.span("lat"), limpar=" ,;:\n")
        ex.longitude = tm.campo(*m.span("lon"), limpar=" ,;:\n")
        if ex.longitude.valor:
            ex.longitude.valor = ex.longitude.valor.rstrip(".")
        fim_paragrafo = m.end()
    else:
        fim_paragrafo = _paragrafo_por_partes(
            tm, ex, inicio, procedimentos or _nomes_padrao("procedimentos"),
            intervencoes or _nomes_padrao("intervencoes"), municipios or _nomes_padrao("municipios"),
        )

    m_desc = RE_DESCRICAO.search(norm, fim_paragrafo)
    m_fin = RE_FINALIDADE.search(norm, m_desc.end() if m_desc else fim_paragrafo)
    if m_fin is None and m_desc is not None:  # alguns requerimentos trazem as finalidades antes da descrição
        m_fin = RE_FINALIDADE.search(norm, fim_paragrafo, m_desc.start())
    fin_antes = m_fin is not None and m_desc is not None and m_fin.start() < m_desc.start()

    # rodapé: última data do documento + nome logo acima
    idx_data_linha = None
    idx_ass_ini = None
    datas = list(RE_DATA.finditer(norm, m_fin.end() if m_fin else fim_paragrafo))
    if datas:
        md = datas[-1]
        ex.data_documento = tm.campo(*md.span())
        idx_data_linha = tm.linha_do_indice(md.start())
        idx_ass = _linha_assinante(linhas, idx_data_linha, nome_esperado or ex.requerente_nome.valor)
        if idx_ass is not None:
            idx_ass_ini, idx_ass_fim = _bloco_assinante(linhas, idx_ass, idx_data_linha)
            ex.linha_assinante = Linha([p for ln in linhas[idx_ass_ini:idx_ass_fim + 1] for p in ln.palavras])
            a = tm.inicio_linha[idx_ass_ini]
            ex.assinante_nome = tm.campo(a, tm.inicio_linha[idx_ass_fim] + len(linhas[idx_ass_fim].texto))
    else:
        ex.avisos.append("data do documento não encontrada")
    # onde o corpo termina: no bloco do assinante ou na data
    idx_rodape = idx_data_linha if idx_data_linha is not None else len(linhas)
    if idx_ass_ini is not None:
        idx_rodape = min(idx_rodape, idx_ass_ini)

    if m_desc:
        if m_fin and not fin_antes:
            fim_desc = m_fin.start()
        else:
            fim_desc = tm.inicio_linha[idx_rodape] if idx_rodape < len(linhas) and fin_antes else len(norm)
        ex.descricao_usos = tm.campo(m_desc.end(), fim_desc)
    else:
        ex.avisos.append("seção 'Descrição dos usos da água' não encontrada")

    if m_fin:
        idx_cab = tm.linha_do_indice(m_fin.end())
        limite = tm.linha_do_indice(m_desc.start()) if fin_antes else idx_rodape
        secao = linhas[idx_cab + 1:limite]
        # título na mesma linha do cabeçalho: "Finalidade do Uso - Consumo Animal"
        fim_cab = tm.inicio_linha[idx_cab + 1] if idx_cab + 1 < len(linhas) else len(norm)
        resto = [p for (i, _, p) in tm.intervalos if m_fin.end() <= i < fim_cab and p.texto.strip(" -–—:;")]
        if resto:
            secao = [Linha(resto), *secao]
        _secao_finalidades(secao, ex, titulos_extra or [])
    else:
        ex.avisos.append("seção 'Finalidade(s) do Uso da Água' não encontrada")
    return ex


def _paragrafo_por_partes(tm: TextoMapeado, ex: ExtracaoBruta, inicio: int, procedimentos: list[str],
                          intervencoes: list[str], municipios: list[str]) -> int:
    """Lê o parágrafo do requerente por âncoras independentes, quando ele não segue o texto do modelo: cada
    órgão escreve o seu ("vem requerer ... na localidade X, zona rural do município de Y, Latitude ..."; "inscrita
    no CNPJ sob nº ..."; "Localização do Poço: ..."). Devolve onde o parágrafo termina."""
    norm = tm.norm
    fins = [m.start() for m in (RE_DESCRICAO.search(norm, inicio), RE_FINALIDADE.search(norm, inicio)) if m]
    fim = min(fins) if fins else min(len(norm), inicio + 3000)
    m_req = RE_VEM_REQUERER.search(norm, inicio, fim)
    m_lat = RE_LATITUDE.search(norm, inicio, fim)
    if m_req is None and m_lat is None:
        ex.avisos.append("parágrafo principal não reconhecido; campos de identificação ficaram vazios")
        return inicio
    ex.avisos.append("parágrafo principal fora do modelo; campos lidos por partes")
    antes_do_pedido = m_req.start() if m_req else fim  # nome e CPF/CNPJ vêm antes de "vem requerer"
    depois_do_pedido = m_req.end() if m_req else inicio
    fim_local = m_lat.start() if m_lat else fim

    # CPF/CNPJ: depois de "inscrito", se houver (o CPF de um procurador pode aparecer antes)
    m_insc = re.compile(r"inscrit\w*").search(norm, inicio, antes_do_pedido)
    m_rot = RE_DOC_ROTULO.search(norm, m_insc.start() if m_insc else inicio, antes_do_pedido)
    m_doc = RE_DOC_VALOR.match(norm, m_rot.end(), antes_do_pedido) if m_rot else None
    if m_doc:
        ex.cpf_cnpj = tm.campo(*m_doc.span("doc"))

    # nome: do começo da linha até a qualificação ("inscrito", "pessoa jurídica", "brasileiro", "CPF"...)
    m_nome = RE_FIM_NOME.search(norm, inicio, antes_do_pedido)
    if m_nome:
        ex.requerente_nome = _nome_requerente(tm, inicio, m_nome.start())

    # procedimento: o trecho logo depois de "vem requerer" que mais se parece com um procedimento do SIGA
    fim_proc = depois_do_pedido
    if m_req:
        a, b = _procedimento(norm, m_req.end(), fim_local, procedimentos)
        ex.procedimento = tm.campo(a, b)
        fim_proc = b
        ex.tipo_intervencao = _intervencao(tm, m_req.end(), fim_proc, fim_local, intervencoes)

    # município: "município (de) X"; sem o rótulo, um município do PI seguido de "- PI"
    m_mun = RE_MUNICIPIO.search(norm, fim_proc, fim_local)
    fim_mun = None
    if m_mun:
        fim_mun = _ate(norm, RE_FIM_MUNICIPIO, m_mun.end(), fim_local, 60)
        ex.municipio = tm.campo(m_mun.end(), fim_mun)
    else:
        m_loc_poco = re.compile(r"\blocaliza\w*\s+do\s+po[c]o").search(norm, depois_do_pedido, fim_local)
        achado = (_municipio_com_uf(norm, m_loc_poco.end(), fim_local, municipios) if m_loc_poco else None) \
            or _municipio_com_uf(norm, inicio, fim_local, municipios)
        if achado:
            ex.municipio = tm.campo(*achado)
            ex.municipio.conf_fixa = min(ex.municipio.confianca, 85.0)
            ex.municipio.nota = "município deduzido do endereço (sem o rótulo 'município')"

    # localidade: "localidade X" ou "Localização do Poço: X"; sem rótulo, "no município Y, na X"
    m_loc = RE_LOCALIDADE.search(norm, fim_proc, fim_local)
    if m_loc:
        ex.localidade = tm.campo(m_loc.end(), _ate(norm, RE_FIM_LOCALIDADE, m_loc.end(), fim_local, 150))
    elif fim_mun is not None:
        m_na = re.compile(r"\s*,?\s*n[ao]\s+").match(norm, fim_mun, fim_local)
        if m_na:
            ex.localidade = tm.campo(m_na.end(), _ate(norm, RE_FIM_LOCALIDADE, m_na.end(), fim_local, 150))
            if ex.localidade.valor:
                ex.localidade.conf_fixa = min(ex.localidade.confianca, CONF_INFERIDO)
                ex.localidade.nota = "localidade deduzida do texto (sem o rótulo 'localidade')"

    if m_lat is None:
        return max(fim_proc, inicio)
    ex.latitude = tm.campo(*m_lat.span("lat"), limpar=" ,;:\n")
    a, b = m_lat.span("lon")
    corte = re.compile(r",\s+[a-z]|\s+(?:n[ao]|em|com|para)\s").search(norm, a, b)
    ex.longitude = tm.campo(a, corte.start() if corte else b, limpar=" ,;:\n")
    if ex.longitude.valor:
        ex.longitude.valor = ex.longitude.valor.rstrip(".")
    return m_lat.end()


def _ate(norm: str, fim_re: re.Pattern, a: int, limite: int, maximo: int) -> int:
    """Fim do valor que começa em `a`: o primeiro terminador, sem passar de `limite` nem de `maximo` caracteres."""
    m = fim_re.search(norm, a, limite)
    return min(m.start() if m else limite, a + maximo)


def _nome_requerente(tm: TextoMapeado, inicio: int, fim: int) -> CampoBruto:
    """Nome que termina em `fim`: a linha toda e, se o nome quebrou, a linha de cima (menos saudações como
    "Ilustríssimo Senhor Diretor"); sem o artigo de "A Secretaria...", "O Instituto...". """
    norm = tm.norm
    li = tm.linha_do_indice(fim)
    ini = max(tm.inicio_linha[li], inicio)
    if li > 0 and tm.inicio_linha[li - 1] >= inicio:
        anterior = norm[tm.inicio_linha[li - 1]:tm.inicio_linha[li]].strip()
        quebrou = not norm[ini:fim].strip() or anterior.endswith(("-", "–"))
        if quebrou and not RE_SAUDACAO.search(anterior):
            ini = tm.inicio_linha[li - 1]
    m_art = re.match(r"\s*(?:a|o)\s+(?=\S)", norm[ini:fim])
    if m_art and tm.texto[ini + m_art.end()].isupper():
        ini += m_art.end()
    return tm.campo(ini, fim)


def _procedimento(norm: str, a: int, limite: int, procedimentos: list[str]) -> tuple[int, int]:
    """O trecho a partir de `a` (1 a 22 palavras) mais parecido com um procedimento da lista; sem nenhum
    parecido, vai até o primeiro terminador ("para perfuração", "na localidade", "localizado"...)."""
    palavras = [(a + m.start(), a + m.end()) for m in re.finditer(r"\S+", norm[a:limite])][:22]
    alvos = [chave(p) for p in procedimentos if chave(p)]
    melhor: tuple[float, int] | None = None
    for k in range(1, len(palavras) + 1):
        trecho = chave(norm[palavras[0][0]:palavras[k - 1][1]])
        for alvo in alvos:
            pontos = max(fuzz.ratio(trecho, alvo), fuzz.token_sort_ratio(trecho, alvo))
            if melhor is None or pontos > melhor[0]:
                melhor = (pontos, k)
    if melhor and melhor[0] >= 80:
        return palavras[0][0], palavras[melhor[1] - 1][1]
    return a, _ate(norm, RE_FIM_PROCEDIMENTO, a + 1, limite, 160)


def _intervencao(tm: TextoMapeado, a: int, fim_proc: int, limite: int, intervencoes: list[str]) -> CampoBruto:
    """Tipo de intervenção citado no pedido: o primeiro depois do procedimento ("... para Poço Tubular") ou,
    se não houver, o que faz parte do próprio procedimento ("Regularização de Poço Tubular")."""
    achados: list[tuple[int, int]] = []
    for nome in intervencoes:
        partes = chave(nome).split()
        if partes:
            padrao = re.compile(r"\b" + r"\W+".join(map(re.escape, partes)) + r"\b")
            achados += [m.span() for m in padrao.finditer(tm.norm, a, limite)]
    achados.sort()
    depois = [s for s in achados if s[0] >= fim_proc]
    escolha = (depois or achados or [None])[0]
    return tm.campo(*escolha) if escolha else CampoBruto(None)


@lru_cache(maxsize=8)
def _re_municipios(nomes: tuple[str, ...]) -> re.Pattern:
    partes = sorted({chave(n) for n in nomes if chave(n)}, key=len, reverse=True)  # o nome mais longo primeiro
    alternativas = "|".join(r"\W+".join(map(re.escape, p.split())) for p in partes)
    return re.compile(rf"\b(?:{alternativas})(?=\s*[-–—/]\s*pi\b)")


def _municipio_com_uf(norm: str, a: int, limite: int, municipios: list[str]) -> tuple[int, int] | None:
    m = _re_municipios(tuple(municipios)).search(norm, a, limite)
    return m.span() if m else None


def _linha_assinante(linhas: list[Linha], idx_data: int, nome_ref: str | None) -> int | None:
    """Nome impresso acima da data. Se houver rabisco de assinatura lido pelo OCR, escolhe a
    linha que mais se parece com o nome do requerente entre as 3 anteriores."""
    from rapidfuzz import fuzz

    candidatos = []
    for k in range(idx_data - 1, max(idx_data - 4, -1), -1):
        txt = linhas[k].texto
        if proporcao_letras(txt) < 0.6 or len(chave(txt)) < 3:
            continue
        if RE_CAB_TABELA.search(normalizar_paralelo(txt)):
            break
        score = fuzz.ratio(chave(txt), chave(nome_ref)) if nome_ref else 0
        candidatos.append((score, -abs(idx_data - k), k))
    if not candidatos:
        return None
    if nome_ref:
        candidatos.sort(reverse=True)
        return candidatos[0][2]
    return max(candidatos, key=lambda c: c[1])[2]


def _bloco_assinante(linhas: list[Linha], idx: int, idx_data: int, max_linhas: int = 3) -> tuple[int, int]:
    """Nome longo (razão social) quebra em várias linhas coladas: junta à linha escolhida as
    vizinhas (acima, e abaixo até a data) que sejam texto, da mesma página e sem espaço maior
    que meia linha entre elas."""

    def coladas(cima: Linha, baixo: Linha) -> bool:
        return (
            cima.pagina == baixo.pagina
            and baixo.bbox[1] - cima.bbox[3] <= 0.5 * max(cima.altura_mediana, baixo.altura_mediana)
        )

    def texto(ln: Linha) -> bool:
        return proporcao_letras(ln.texto) >= 0.8

    ini = fim = idx
    while fim + 1 < idx_data and fim - ini + 1 < max_linhas and texto(linhas[fim + 1]) and coladas(linhas[fim], linhas[fim + 1]):
        fim += 1
    while ini > 0 and fim - ini + 1 < max_linhas and texto(linhas[ini - 1]) and coladas(linhas[ini - 1], linhas[ini]):
        ini -= 1
    return ini, fim


# ----------------------------------------------------------------- seção de finalidades
def _eh_titulo(linha: Linha, titulos_extra: list[str]) -> tuple[bool, FinalidadeDef | None]:
    txt = linha.texto
    if ":" in txt or proporcao_letras(txt) < 0.85 or len(chave(txt)) < 4:
        return False, None
    d = definicao_por_titulo(txt)
    if d is not None:
        return True, d
    alvo = chave(txt)
    if any(fuzz.ratio(alvo, chave(t)) >= 88 for t in titulos_extra):
        return True, None
    return False, None


def _secao_finalidades(linhas: list[Linha], ex: ExtracaoBruta, titulos_extra: list[str]) -> None:
    grupos: list[tuple[BlocoFinalidade, list[Linha]]] = []
    orfas: list[Linha] = []  # linhas fora de qualquer finalidade reconhecida
    for linha in linhas:
        titulo, d = _eh_titulo(linha, titulos_extra)
        if titulo:
            bloco = BlocoFinalidade(CampoBruto(linha.texto.strip(" ,.;"), list(linha.palavras)), d)
            grupos.append((bloco, []))
        elif grupos and grupos[-1][0].definicao is not None:
            grupos[-1][1].append(linha)
        else:
            orfas.append(linha)

    for bloco, conteudo in grupos:
        if bloco.definicao is not None:
            _ler_bloco(bloco, conteudo)
        ex.blocos.append(bloco)
        ex.finalidades.append(bloco.titulo)

    irrig = next((b for b in ex.blocos if b.chave == "irrigacao"), None)
    if irrig is None:
        # tabela de irrigação sem o título reconhecido (título ilegível no OCR)
        solto = BlocoFinalidade(CampoBruto(None), POR_CHAVE["irrigacao"])
        _ler_bloco(solto, orfas)
        if solto.tem_linhas:
            irrig = solto
    if irrig is not None:
        ex.tem_tabela_irrigacao = irrig.tem_linhas
        ex.irrigacao = [
            LinhaIrrigacao(
                ln.get("sistema", CampoBruto(None)), ln.get("area", CampoBruto(None)),
                ln.get("cultura", CampoBruto(None)), " ".join(c.valor or "" for c in ln.values()),
            )
            for ln in irrig.linhas
        ]


def _ler_bloco(bloco: BlocoFinalidade, linhas: list[Linha]) -> None:
    d = bloco.definicao
    assert d is not None
    idx = None
    if d.modo_linhas == "tabela":
        idx = next((k for k, ln in enumerate(linhas) if casa_cabecalho(d, ln.texto)), None)
    elif d.modo_linhas == "lista":
        idx = next((k for k, ln in enumerate(linhas) if casa_cabecalho(d, ln.texto.split(":")[0])), None)
    if d.campos:
        _ler_campos(d, linhas[:idx] if idx is not None else linhas, bloco)
    if d.modo_linhas == "pares":
        bloco.tem_linhas = True
        _ler_pares(d, linhas, bloco)
    elif idx is not None:
        bloco.tem_linhas = True
        if d.modo_linhas == "tabela":
            _ler_tabela(d, linhas[idx], linhas[idx + 1:], bloco)
        else:
            col = d.colunas[0].chave
            for ln in linhas[idx + 1:]:
                if proporcao_letras(ln.texto) >= 0.5:
                    bloco.linhas.append({col: CampoBruto(ln.texto.strip(" ,.;"), list(ln.palavras))})


def _prefixo_rotulo(linha: Linha, rotulo: str) -> int | None:
    """Quantas palavras do início da linha formam o rótulo (tolerando OCR); None se não é o rótulo."""
    alvo = chave(rotulo)
    n = len(rotulo.split())
    melhor = None
    for k in (n, n - 1, n + 1):
        if 1 <= k <= len(linha.palavras):
            cand = chave(" ".join(p.texto for p in linha.palavras[:k]))
            pontos = fuzz.ratio(cand, alvo)
            if pontos >= 85 and (melhor is None or pontos > melhor[0]):
                melhor = (pontos, k)
    return melhor[1] if melhor else None


def _vazio_em(palavras: list[Palavra]) -> CampoBruto:
    """Campo sem valor, mas com a posição do rótulo para a tela de revisão."""
    if not palavras:
        return CampoBruto(None)
    return CampoBruto(None, pagina_fixa=palavras[0].pagina, bbox_fixa=uniao_bbox([p.bbox for p in palavras]))


def _ler_campos(d: FinalidadeDef, linhas: list[Linha], bloco: BlocoFinalidade) -> None:
    for ln in linhas:
        for c in d.campos:
            if c.chave in bloco.valores:
                continue
            k = _prefixo_rotulo(ln, c.rotulo)
            if k is None:
                continue
            resto = list(ln.palavras[k:])
            while resto and resto[0].texto.strip() in (":", ";", "-"):
                resto.pop(0)
            if resto:
                bloco.valores[c.chave] = CampoBruto(" ".join(p.texto for p in resto).lstrip(": "), resto)
            else:
                bloco.valores[c.chave] = _vazio_em(ln.palavras[:k])
            break
    for c in d.campos:
        bloco.valores.setdefault(c.chave, CampoBruto(None))


def _centros_cabecalho(cab: Linha, d: FinalidadeDef) -> list[float]:
    """Centro de cada coluna pela linha de cabeçalho."""
    n = len(d.colunas)
    celulas = cab.celulas()
    if len(celulas) == n:
        return [(c.bbox[0] + c.bbox[2]) / 2 for c in celulas]
    # OCR juntou células: procura a primeira palavra do rótulo de cada coluna
    centros: list[float] = []
    inicio = 0
    for col in d.colunas:
        primeira = chave(col.rotulo.split()[0])
        for j in range(inicio, len(cab.palavras)):
            if fuzz.ratio(chave(cab.palavras[j].texto), primeira) >= 75:
                centros.append((cab.palavras[j].bbox[0] + cab.palavras[j].bbox[2]) / 2)
                inicio = j + 1
                break
    if len(centros) == n:
        return centros
    x0, _, x1, _ = cab.bbox
    passo = (x1 - x0) / n
    return [x0 + (i + 0.5) * passo for i in range(n)]


def _centros_dados(linhas: list[Linha], n: int) -> list[float] | None:
    """Centro das colunas aprendido das linhas que têm uma célula por coluna (mais fiel que o
    cabeçalho, que pode ter largura e alinhamento diferentes dos dados)."""
    completas = [c for c in (ln.celulas() for ln in linhas) if len(c) == n]
    if not completas:
        return None
    return [median((c[j].bbox[0] + c[j].bbox[2]) / 2 for c in completas) for j in range(n)]


def _distribuir(linha: Linha, centros: list[float]) -> dict[int, list[Palavra]]:
    """Coloca cada célula da linha na coluna de centro mais próximo."""
    saida: dict[int, list[Palavra]] = {}
    passos = [b - a for a, b in zip(centros, centros[1:])]
    tolerancia = 0.3 * min(passos) if passos else float("inf")

    def mais_perto(x: float) -> int:
        return min(range(len(centros)), key=lambda k: abs(x - centros[k]))

    for cel in linha.celulas():
        meio = (cel.bbox[0] + cel.bbox[2]) / 2
        j = mais_perto(meio)
        if abs(meio - centros[j]) > tolerancia and len(cel.palavras) > 1:
            # centro longe de qualquer coluna: o OCR juntou células vizinhas; divide palavra a palavra
            for p in cel.palavras:
                saida.setdefault(mais_perto((p.bbox[0] + p.bbox[2]) / 2), []).append(p)
        else:
            saida.setdefault(j, []).extend(cel.palavras)
    return saida


def _ler_tabela(d: FinalidadeDef, cab: Linha, linhas: list[Linha], bloco: BlocoFinalidade) -> None:
    pos = _centros_dados(linhas, len(d.colunas)) or _centros_cabecalho(cab, d)
    num = next((i for i, c in enumerate(d.colunas) if c.chave == d.coluna_numerica), None)
    atual: dict[int, list[Palavra]] | None = None
    linhas_tab: list[dict[int, list[Palavra]]] = []
    anterior: Linha | None = None
    # linha afastada da anterior = novo item mesmo sem número; a referência é o menor passo entre
    # linhas da tabela (quebra de célula), que vale igual para texto nativo e OCR
    passos = [b.bbox[1] - a.bbox[1] for a, b in zip(linhas, linhas[1:]) if a.pagina == b.pagina and b.bbox[1] > a.bbox[1]]
    passo_min = min(passos) if passos else 0.0
    for ln in linhas:
        if atual is None and ln.texto.lstrip().startswith("("):
            continue  # continuação do cabeçalho: "(ha)", "(horizonte 10 anos)"
        cels = _distribuir(ln, pos)
        tem_num = num is not None and num in cels and parece_numero(cels[num][0].texto)
        afastada = (
            anterior is not None and ln.pagina == anterior.pagina and passo_min > 0
            and ln.bbox[1] - anterior.bbox[1] > 1.35 * passo_min
        )
        if tem_num or (atual is not None and afastada):
            atual = {k: list(v) for k, v in cels.items()}
            linhas_tab.append(atual)
        elif atual is not None:
            for k, v in cels.items():  # continuação de células quebradas em várias linhas
                atual.setdefault(k, []).extend(v)
        # antes da primeira linha com número: continuação do cabeçalho ("(ha)", "(horizonte 10 anos)")
        anterior = ln
    for item in linhas_tab:
        bloco.linhas.append({
            c.chave: CampoBruto(" ".join(p.texto for p in item[i]), item[i]) if item.get(i) else CampoBruto(None)
            for i, c in enumerate(d.colunas)
        })


def _ler_pares(d: FinalidadeDef, linhas: list[Linha], bloco: BlocoFinalidade) -> None:
    """Linhas "uso: descrição"; linha sem dois-pontos continua a descrição anterior."""
    c_uso, c_desc = d.colunas[0].chave, d.colunas[1].chave
    atual: tuple[list[Palavra], list[Palavra]] | None = None
    pares: list[tuple[list[Palavra], list[Palavra]]] = []
    for ln in linhas:
        k = next((i for i, p in enumerate(ln.palavras) if ":" in p.texto), None)
        if k is not None:
            p = ln.palavras[k]
            antes, _, depois = p.texto.partition(":")
            uso = list(ln.palavras[:k]) + ([Palavra(antes, p.conf, p.bbox, p.pagina)] if antes else [])
            desc = ([Palavra(depois, p.conf, p.bbox, p.pagina)] if depois else []) + list(ln.palavras[k + 1:])
            atual = (uso, desc)
            pares.append(atual)
        elif atual is not None:
            atual[1].extend(ln.palavras)
    for uso, desc in pares:
        bloco.linhas.append({
            c_uso: CampoBruto(" ".join(p.texto for p in uso) or None, uso),
            c_desc: CampoBruto(" ".join(p.texto for p in desc) or None, desc),
        })
