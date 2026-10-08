"""Normaliza e valida a extração bruta contra as regras de negócio e as referências do SIGA."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from rapidfuzz import fuzz

from .normalizadores import (
    dentro_do_piaui,
    normalizar_coordenada,
    normalizar_cpf_cnpj,
    normalizar_data,
    normalizar_numero,
)
from .finalidades import CampoDef, FinalidadeDef, definicao_por_titulo, rotulo_campo
from .parser import BlocoFinalidade, ExtracaoBruta
from .texto import Ref, chave, melhor_correspondencia, proporcao_letras
from .tipos import BBox, CampoBruto

CAMPOS_OBRIGATORIOS = (
    "requerente_nome",
    "cpf_cnpj",
    "procedimento",
    "tipo_intervencao",
    "municipio",
    "localidade",
    "latitude",
    "longitude",
)
ROTULOS = {
    "requerente_nome": "Nome do requerente",
    "cpf_cnpj": "CPF/CNPJ",
    "procedimento": "Procedimento",
    "tipo_intervencao": "Tipo de intervenção",
    "municipio": "Município",
    "localidade": "Localidade",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "descricao_usos": "Descrição dos usos da água",
    "assinante_nome": "Nome do assinante",
    "data_documento": "Data do documento",
    "finalidade": "Finalidade",
    "finalidades": "Finalidades",
    "irrigacao": "Tabela de irrigação",
    "irrigacao_sistema": "Sistema de irrigação",
    "irrigacao_area": "Área irrigada (ha)",
    "irrigacao_cultura": "Cultura",
}


class Referencias(Protocol):
    municipios: list[Ref]
    procedimentos: list[Ref]
    intervencoes: list[Ref]
    finalidades: list[Ref]
    sistemas_irrigacao: list[Ref]
    culturas: list[Ref]

    def dominio(self, tipo: str) -> list[Ref]: ...
    def pessoa_por_documento(self, digitos: str) -> Ref | None: ...
    def ponto_no_municipio(self, lat: float, lon: float, municipio_id: int | None) -> bool | None: ...


@dataclass
class CampoValidado:
    campo: str
    valor_bruto: str | None
    valor_normalizado: str | None
    confianca: float
    valido: bool
    obrigatorio: bool = False
    mensagem: str | None = None
    pagina: int | None = None
    bbox: BBox | None = None
    ref_id: int | None = None
    item: int | None = None  # linha da tabela/lista dos detalhes de finalidade (1, 2, ...)

    def dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = list(self.bbox) if self.bbox else None
        return d


@dataclass
class ItemIrrigacao:
    ordem: int
    sistema: CampoValidado
    area: CampoValidado
    cultura: CampoValidado

    @property
    def area_ha(self) -> float | None:
        return float(self.area.valor_normalizado) if self.area.valor_normalizado else None

    @property
    def confianca(self) -> float:
        return round(min(self.sistema.confianca, self.area.confianca, self.cultura.confianca), 2)

    @property
    def valido(self) -> bool:
        return self.sistema.valido and self.area.valido and self.cultura.valido


@dataclass
class DetalheFinalidade:
    """Dados próprios de uma finalidade (ex.: espécies da aquicultura), já validados.

    `campos` vai para `campo_extraido` (nome "<finalidade>.<campo>", índice = item); `dados` é a
    versão normalizada gravada em `requerimento_finalidade.detalhes`."""

    indice: int  # posição na lista de finalidades
    chave: str
    campos: list[CampoValidado]
    dados: dict[str, Any]


@dataclass
class Resultado:
    campos: dict[str, CampoValidado]
    finalidades: list[CampoValidado]
    irrigacao: list[ItemIrrigacao]
    detalhes: list[DetalheFinalidade]
    latitude: float | None
    longitude: float | None
    tipo_pessoa: str | None
    pessoa_id: int | None
    data_documento: date | None
    pendencias: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    confianca_geral: float = 0.0
    status: str = "revisao"


def _base(nome: str, bruto: CampoBruto, obrigatorio: bool) -> CampoValidado:
    return CampoValidado(
        campo=nome,
        valor_bruto=bruto.valor,
        valor_normalizado=bruto.valor,
        confianca=bruto.confianca,
        valido=bool(bruto.valor),
        obrigatorio=obrigatorio,
        mensagem=(bruto.nota if bruto.valor else "campo não encontrado no documento"),
        pagina=bruto.pagina,
        bbox=bruto.bbox,
    )


def _msg(cv: CampoValidado, texto: str | None) -> None:
    """Acrescenta mensagem sem apagar a anterior (ex.: nota de segunda leitura)."""
    if not texto:
        return
    cv.mensagem = f"{cv.mensagem}; {texto}" if cv.mensagem else texto


def _casar(nome: str, bruto: CampoBruto, opcoes: list[Ref], limiar: float, obrig: bool, rotulo: str) -> CampoValidado:
    cv = _base(nome, bruto, obrig)
    if not bruto.valor:
        return cv
    if not opcoes:
        _msg(cv, f"lista de referência de {rotulo} vazia; valor mantido como lido")
        cv.confianca = min(cv.confianca, 60.0)
        return cv
    ref, score = melhor_correspondencia(bruto.valor, opcoes, limiar)
    if ref is None:
        cv.valido = False
        cv.confianca = min(cv.confianca, score)
        _msg(cv, f"'{bruto.valor}' não corresponde a nenhum(a) {rotulo} cadastrado(a)")
        return cv
    cv.valor_normalizado = ref.nome
    cv.ref_id = ref.id
    cv.confianca = round(min(cv.confianca, score), 2)
    if score < 100:
        _msg(cv, f"lido '{bruto.valor}', associado a '{ref.nome}' ({score:.0f}%)")
    return cv


def validar(ex: ExtracaoBruta, refs: Referencias, limiar_confianca: float = 80.0, hoje: date | None = None) -> Resultado:
    hoje = hoje or date.today()
    campos: dict[str, CampoValidado] = {}
    pendencias: list[str] = []
    avisos: list[str] = list(ex.avisos)

    # --- CPF/CNPJ e pessoa
    cv_doc = _base("cpf_cnpj", ex.cpf_cnpj, True)
    tipo_pessoa = pessoa_id = None
    pessoa: Ref | None = None
    if ex.cpf_cnpj.valor:
        doc = normalizar_cpf_cnpj(ex.cpf_cnpj.valor)
        cv_doc.valor_normalizado = doc.formatado or doc.digitos
        cv_doc.valido = doc.valido
        _msg(cv_doc, doc.mensagem)
        tipo_pessoa = doc.tipo
        if doc.valido:
            pessoa = refs.pessoa_por_documento(doc.digitos)
            if pessoa:
                pessoa_id = cv_doc.ref_id = pessoa.id
            else:
                _msg(cv_doc, "documento válido, mas não encontrado no cadastro de pessoas do SIGA")
        else:
            cv_doc.confianca = min(cv_doc.confianca, 40.0)
    campos["cpf_cnpj"] = cv_doc

    # --- nome
    cv_nome = _base("requerente_nome", ex.requerente_nome, True)
    if ex.requerente_nome.valor:
        if proporcao_letras(ex.requerente_nome.valor) < 0.7 or len(chave(ex.requerente_nome.valor)) < 3:
            cv_nome.valido = False
            _msg(cv_nome, "nome com caracteres inesperados")
        elif pessoa:
            score = fuzz.token_sort_ratio(chave(ex.requerente_nome.valor), chave(pessoa.nome))
            if score < 85:
                cv_nome.confianca = min(cv_nome.confianca, float(score))
                _msg(cv_nome, f"nome difere do cadastro do SIGA ('{pessoa.nome}', {score:.0f}%)")
    campos["requerente_nome"] = cv_nome

    # --- listas de referência
    campos["procedimento"] = _casar("procedimento", ex.procedimento, refs.procedimentos, 75, True, "procedimento")
    campos["tipo_intervencao"] = _casar(
        "tipo_intervencao", ex.tipo_intervencao, refs.intervencoes, 75, True, "tipo de intervenção"
    )
    campos["municipio"] = _casar("municipio", ex.municipio, refs.municipios, 80, True, "município do PI")

    # --- localidade
    cv_loc = _base("localidade", ex.localidade, True)
    if ex.localidade.valor and len(ex.localidade.valor) > 100:
        cv_loc.valido = False
        _msg(cv_loc, "localidade com mais de 100 caracteres (limite do SIGA)")
    campos["localidade"] = cv_loc

    # --- coordenadas
    lat = lon = None
    for nome, eixo in (("latitude", "lat"), ("longitude", "lon")):
        bruto: CampoBruto = getattr(ex, nome)
        cv = _base(nome, bruto, True)
        if bruto.valor:
            c = normalizar_coordenada(bruto.valor, eixo)
            msgs = c.erros + c.avisos
            _msg(cv, "; ".join(msgs) or None)
            if c.valida:
                cv.valor_normalizado = f"{c.decimal:.7f}"
                if eixo == "lat":
                    lat = c.decimal
                else:
                    lon = c.decimal
            else:
                cv.valido = False
                cv.valor_normalizado = f"{c.decimal:.7f}" if c.decimal is not None else None
            if c.avisos:
                cv.confianca = min(cv.confianca, 70.0)
        campos[nome] = cv
    if lat is not None and lon is not None:
        if not dentro_do_piaui(lat, lon):
            pendencias.append(f"coordenadas ({lat:.5f}, {lon:.5f}) fora dos limites do Piauí")
            campos["latitude"].valido = campos["longitude"].valido = False
        else:
            dentro = refs.ponto_no_municipio(lat, lon, campos["municipio"].ref_id)
            if dentro is False:
                pendencias.append(
                    f"o ponto ({lat:.5f}, {lon:.5f}) fica fora do município declarado "
                    f"({campos['municipio'].valor_normalizado})"
                )

    # --- descrição (opcional)
    campos["descricao_usos"] = _base("descricao_usos", ex.descricao_usos, False)
    if not ex.descricao_usos.valor:
        campos["descricao_usos"].valido = True

    # --- finalidades
    finalidades: list[CampoValidado] = []
    for f in ex.finalidades:
        d = definicao_por_titulo(f.valor)
        alvo = CampoBruto(d.nome if d else f.valor, f.palavras, f.conf_fixa, f.pagina_fixa, f.bbox_fixa, f.nota)
        cv = _casar("finalidade", alvo, refs.finalidades, 75, True, "finalidade de uso")
        cv.valor_bruto = f.valor
        finalidades.append(cv)
    validas = [f for f in finalidades if f.valido]
    if not validas:
        pendencias.append("nenhuma finalidade de uso reconhecida")
    irrigacao_declarada = any("irrig" in chave(f.valor_normalizado or "") for f in validas)

    # --- tabela de irrigação
    itens: list[ItemIrrigacao] = []
    for i, linha in enumerate(ex.irrigacao, start=1):
        sis = _casar("irrigacao_sistema", linha.sistema, refs.sistemas_irrigacao, 75, True, "sistema de irrigação")
        cult = _casar("irrigacao_cultura", linha.cultura, refs.culturas, 75, True, "cultura")
        area = _base("irrigacao_area", linha.area, True)
        valor = normalizar_numero(linha.area.valor)
        if valor is None or valor <= 0:
            area.valido = False
            _msg(area, f"área irrigada inválida ('{linha.area.valor}')")
        else:
            area.valor_normalizado = f"{valor:g}"
            if valor > 100000:
                _msg(area, "área irrigada muito alta; confira a unidade (ha)")
                area.confianca = min(area.confianca, 50.0)
        itens.append(ItemIrrigacao(i, sis, area, cult))
    if irrigacao_declarada and not itens:
        pendencias.append("finalidade Irrigação sem itens na tabela de irrigação")
    if itens and not irrigacao_declarada:
        avisos.append("tabela de irrigação presente, mas a finalidade Irrigação não foi reconhecida")

    # --- dados próprios de cada finalidade
    detalhes = _validar_detalhes(ex, finalidades, refs, itens)
    for det in detalhes:
        for cv in det.campos:
            if not cv.valido:
                pendencias.append(f"{_onde(cv)}: {cv.mensagem}")
            elif cv.valor_bruto and cv.confianca < limiar_confianca:
                pendencias.append(f"{_onde(cv)}: confiança baixa ({cv.confianca:.0f}%)")
        fdef = _DEFS[det.chave]
        if det.chave != "irrigacao" and fdef.modo_linhas and len(det.dados.get("itens", [])) < fdef.min_linhas:
            pendencias.append(f"{fdef.nome}: nenhum item em {fdef.rotulo_linhas}")

    # --- rodapé
    campos["assinante_nome"] = _base("assinante_nome", ex.assinante_nome, False)
    if not ex.assinante_nome.valor:
        campos["assinante_nome"].valido = True
    cv_data = _base("data_documento", ex.data_documento, False)
    data_doc = normalizar_data(ex.data_documento.valor)
    if ex.data_documento.valor:
        if data_doc is None:
            cv_data.valido = False
            _msg(cv_data, f"data inválida ('{ex.data_documento.valor}')")
        else:
            cv_data.valor_normalizado = data_doc.isoformat()
            if data_doc > hoje + timedelta(days=1):
                cv_data.valido = False
                _msg(cv_data, "data no futuro")
            elif data_doc.year < 2000:
                _msg(cv_data, "data anterior a 2000; confira")
                cv_data.confianca = min(cv_data.confianca, 60.0)
    else:
        cv_data.valido = True
    campos["data_documento"] = cv_data

    # --- consolidação
    obrig = [campos[c] for c in CAMPOS_OBRIGATORIOS]
    todos_conf = (
        [c.confianca for c in obrig] + [f.confianca for f in validas] + [it.confianca for it in itens]
        + [cv.confianca for det in detalhes for cv in det.campos if cv.valor_bruto]
    )
    conf_geral = round(sum(todos_conf) / len(todos_conf), 2) if todos_conf else 0.0

    for c in obrig:
        if not c.valido:
            pendencias.append(f"{ROTULOS[c.campo]}: {c.mensagem or 'inválido'}")
        elif c.confianca < limiar_confianca:
            pendencias.append(f"{ROTULOS[c.campo]}: confiança baixa ({c.confianca:.0f}%)")
    for f in finalidades:
        if not f.valido:
            pendencias.append(f"Finalidade: {f.mensagem}")
        elif f.confianca < limiar_confianca:
            pendencias.append(f"Finalidade '{f.valor_normalizado}': confiança baixa ({f.confianca:.0f}%)")
    for it in itens:
        for sub in (it.sistema, it.area, it.cultura):
            if not sub.valido:
                pendencias.append(f"Irrigação, linha {it.ordem}: {sub.mensagem}")
            elif sub.confianca < limiar_confianca:
                pendencias.append(f"Irrigação, linha {it.ordem}: confiança baixa em {sub.campo.split('_')[1]} ({sub.confianca:.0f}%)")
    if not cv_data.valido:
        pendencias.append(f"Data do documento: {cv_data.mensagem}")

    # remove duplicadas preservando ordem
    pendencias = list(dict.fromkeys(pendencias))
    return Resultado(
        campos=campos,
        finalidades=finalidades,
        irrigacao=itens,
        detalhes=detalhes,
        latitude=lat,
        longitude=lon,
        tipo_pessoa=tipo_pessoa,
        pessoa_id=pessoa_id,
        data_documento=data_doc,
        pendencias=pendencias,
        avisos=avisos,
        confianca_geral=conf_geral,
        status="revisao" if pendencias else "extraido",
    )


# ----------------------------------------------------------------- detalhes das finalidades
from .finalidades import POR_CHAVE as _DEFS  # noqa: E402


def _onde(cv: CampoValidado) -> str:
    """'Criação Animal, item 2: Número de Cabeças' (ou sem item, para campos "Rótulo: valor")."""
    rot = rotulo_campo(cv.campo) or cv.campo
    fin, _, campo = rot.partition(" — ")
    return f"{fin}, item {cv.item}: {campo}" if cv.item else rot


def _tipado(nome: str, bruto: CampoBruto, cdef: CampoDef, refs: Referencias, item: int | None) -> CampoValidado:
    rotulo = cdef.rotulo.lower()
    if cdef.tipo == "lista" and bruto.valor:
        opcoes = refs.municipios if cdef.dominio == "municipio" else refs.dominio(cdef.dominio or "")
        cv = _casar(nome, bruto, opcoes, 75, cdef.obrigatorio, rotulo)
    else:
        cv = _base(nome, bruto, cdef.obrigatorio)
    cv.item = item
    if not bruto.valor:
        cv.valido = not cdef.obrigatorio
        cv.mensagem = "não preenchido" if cdef.obrigatorio else None
        return cv
    if cdef.tipo in ("numero", "inteiro"):
        v = normalizar_numero(bruto.valor)
        if v is None or v < 0:
            cv.valido = False
            _msg(cv, f"número inválido ('{bruto.valor}')")
        elif cdef.tipo == "inteiro" and not float(v).is_integer():
            cv.valido = False
            _msg(cv, f"esperado número inteiro ('{bruto.valor}')")
        else:
            cv.valor_normalizado = f"{v:g}" if cdef.tipo == "numero" else str(int(v))
    elif cdef.tipo == "data":
        d = normalizar_data(bruto.valor)
        if d is None:
            cv.valido = False
            _msg(cv, f"data inválida ('{bruto.valor}')")
        else:
            cv.valor_normalizado = d.isoformat()
    return cv


def _converter(cv: CampoValidado, cdef: CampoDef) -> Any:
    v = cv.valor_normalizado
    if v is None or not cv.valido:
        return v
    if cdef.tipo == "numero":
        return float(v)
    if cdef.tipo == "inteiro":
        return int(v)
    return v


def _validar_detalhes(
    ex: ExtracaoBruta, finalidades: list[CampoValidado], refs: Referencias, irrigacao: list[ItemIrrigacao]
) -> list[DetalheFinalidade]:
    blocos = list(ex.blocos)
    saida: list[DetalheFinalidade] = []
    vistas: set[str] = set()
    for i, f in enumerate(ex.finalidades):
        fdef = definicao_por_titulo(f.valor)
        if fdef is None or fdef.chave in vistas:  # finalidade repetida: os detalhes ficam na primeira
            continue
        vistas.add(fdef.chave)
        bloco = next((b for b in blocos if b.chave == fdef.chave), None)
        if bloco is not None:
            blocos.remove(bloco)
        else:
            bloco = BlocoFinalidade(f, fdef)
        saida.append(_detalhe(i, fdef, bloco, refs, irrigacao))
    return saida


def _detalhe(i: int, fdef: FinalidadeDef, bloco: BlocoFinalidade, refs: Referencias,
             irrigacao: list[ItemIrrigacao]) -> DetalheFinalidade:
    campos: list[CampoValidado] = []
    dados: dict[str, Any] = {}
    for cdef in fdef.campos:
        cv = _tipado(f"{fdef.chave}.{cdef.chave}", bloco.valores.get(cdef.chave, CampoBruto(None)), cdef, refs, None)
        campos.append(cv)
        dados[cdef.chave] = _converter(cv, cdef)
    if fdef.chave == "irrigacao":
        # validada à parte (tabela própria); aqui só a versão normalizada para os detalhes
        dados["itens"] = [
            {"sistema": it.sistema.valor_normalizado, "area": it.area_ha, "cultura": it.cultura.valor_normalizado}
            for it in irrigacao
        ]
        return DetalheFinalidade(i, fdef.chave, [], dados)
    if fdef.modo_linhas:
        itens = []
        for n, linha in enumerate(bloco.linhas, start=1):
            item = {}
            for cdef in fdef.colunas:
                cv = _tipado(f"{fdef.chave}.{cdef.chave}", linha.get(cdef.chave, CampoBruto(None)), cdef, refs, n)
                campos.append(cv)
                item[cdef.chave] = _converter(cv, cdef)
            itens.append(item)
        dados["itens"] = itens
    return DetalheFinalidade(i, fdef.chave, campos, dados)
