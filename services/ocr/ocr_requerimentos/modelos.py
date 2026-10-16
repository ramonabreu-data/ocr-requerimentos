"""Contrato dos arquivos JSON que a ferramenta grava no armazenamento (bucket). Eles são a fonte da verdade:
não há banco de dados da ferramenta.

    dados/documentos/{uuid}.json   um documento lido: arquivo, situação, requerimento extraído, cada campo
                                   com valor atual, confiança, leitura original do OCR e posição na folha,
                                   e o histórico de revisões
    dados/paginas/{uuid}.json      texto e palavras do OCR, com posição, de cada página (grande; separado)
    dados/lotes/{uuid}.json        um envio (upload, ZIP ou pasta do scanner)

Toda gravação passa por estes modelos: um documento que não respeite as regras abaixo não chega ao
bucket (o que antes eram restrições CHECK/UNIQUE do banco). `SCHEMA_VERSAO` sobe quando o formato muda;
`atualizar_formato` converte arquivos antigos na leitura. O JSON Schema publicado em
docs/contrato-json/ é gerado daqui (python -m ocr_requerimentos.ferramentas json-schema)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSAO = 1

# desconsiderado: descartado na revisão (não é requerimento, repetido, ilegível): não é validado nem vai ao SIGA
StatusDocumento = Literal["recebido", "processando", "extraido", "revisao", "validado", "erro", "dividido",
                          "desconsiderado"]
STATUS_DOCUMENTO: tuple[str, ...] = StatusDocumento.__args__  # type: ignore[attr-defined]
Confianca = Annotated[float, Field(ge=0, le=100)]
# número de registro: REQ-2026-000123; a parte 2 de um arquivo com vários requerimentos: REQ-2026-000123-2
PADRAO_NUMERO = r"^REQ-\d{4}-\d{6,}(-\d+)?$"


def formatar_numero(ano: int, sequencia: int) -> str:
    return f"REQ-{ano}-{sequencia:06d}"


def ler_numero(numero: str) -> tuple[int, int, int | None]:
    """'REQ-2026-000123-2' -> (2026, 123, 2)."""
    partes = numero.split("-")
    return int(partes[1]), int(partes[2]), int(partes[3]) if len(partes) > 3 else None


def agora() -> datetime:
    return datetime.now(timezone.utc)


class Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)


# ----------------------------------------------------------------- campos lidos
class LeituraOriginalOcr(Modelo):
    """O que o OCR leu neste campo na última leitura do documento, antes de qualquer correção manual.
    Não muda quando o revisor corrige o campo: é a base das análises de acurácia."""

    valor_lido: str | None = Field(description="Texto lido pelo OCR (ou do PDF com texto), sem correção.")
    confianca_ocr: Confianca | None = Field(description="Confiança (0–100) da leitura pelo OCR.")


class LocalNaFolha(Modelo):
    pagina: int | None = Field(None, ge=1, description="Página do documento (1 = primeira).")
    caixa: list[float] | None = Field(
        None, min_length=4, max_length=4,
        description="Retângulo [x0, y0, x1, y1] onde o campo foi lido, em pixels da imagem da página (300 dpi).",
    )


class ValidacaoCampo(Modelo):
    valido: bool | None = Field(None, description="O valor atual passou nas regras (formato, listas do SIGA...).")
    obrigatorio: bool = False
    mensagem: str | None = Field(None, description="Motivo da pendência ou aviso, quando há.")


class Campo(Modelo):
    """Um campo do requerimento. `indice` diferencia itens de listas: posição da finalidade, linha da
    tabela de irrigação ou item dos detalhes de uma finalidade."""

    campo: str = Field(min_length=1)
    indice: int | None = None
    valor_atual: str | None = Field(
        description="Texto atual do campo: o lido pelo OCR ou, se `corrigido_manualmente`, o digitado na revisão."
    )
    valor_atual_normalizado: str | None = Field(description="valor_atual depois da normalização (CPF com máscara, "
                                                            "coordenada em graus decimais, nome da lista do SIGA...).")
    confianca_atual: Confianca | None = Field(description="Confiança do valor atual; 100 quando corrigido à mão.")
    corrigido_manualmente: bool = False
    leitura_original_ocr: LeituraOriginalOcr | None = Field(
        description="Leitura original do OCR; nula quando o campo não foi lido e foi incluído na revisão."
    )
    local_na_folha: LocalNaFolha = Field(default_factory=LocalNaFolha)
    validacao: ValidacaoCampo = Field(default_factory=ValidacaoCampo)


# ----------------------------------------------------------------- requerimento
class Finalidade(Modelo):
    texto: str | None
    tipo_finalidade_id: int | None = Field(None, description="outorga_tipofinalidadeuso.id no SIGA.")
    confianca: Confianca | None = None
    valido: bool = False
    chave: str | None = Field(None, description="Definição da finalidade (extracao/finalidades.py), ex.: criacao_animal.")
    detalhes: dict[str, Any] | None = Field(None, description="Dados próprios da finalidade, já normalizados.")


class LinhaIrrigacao(Modelo):
    ordem: int = Field(ge=1)
    sistema: str | None
    sistema_id: int | None = Field(None, description="Posição (1, 2, ...) na lista de sistemas do formulário.")
    area_ha: float | None = Field(None, ge=0)
    cultura: str | None
    cultura_id: int | None = Field(None, description="Posição (1, 2, ...) na lista de culturas do formulário.")
    confianca: Confianca | None = None
    valido: bool = False


class Validacao(Modelo):
    situacao: Literal["pendente", "validado"] = "pendente"
    validado_por_id: int | None = None
    validado_em: datetime | None = None
    modo: Literal["conferencia", "envio"] = Field(
        "conferencia", description="conferencia: validado na tela de conferência; envio: enviado como já conferido "
                                   "e validado automaticamente ao fim da leitura (validado_por_id = quem enviou).",
    )

    @model_validator(mode="after")
    def _validado_tem_data(self) -> "Validacao":
        if self.situacao == "validado" and self.validado_em is None:
            raise ValueError("requerimento validado sem data de validação")
        return self


class Requerimento(Modelo):
    """Dados extraídos (valor atual de cada campo, já normalizado) e o estado da conferência."""

    requerente_nome: str | None = None
    cpf_cnpj: str | None = Field(None, pattern=r"^[0-9./-]*$")
    tipo_pessoa: Literal["F", "J"] | None = None
    pessoa_id: int | None = Field(None, description="core_pessoa.id no SIGA.")
    procedimento: str | None = None
    procedimento_id: int | None = None
    tipo_intervencao: str | None = None
    tipo_intervencao_id: int | None = None
    municipio: str | None = None
    municipio_id: int | None = None
    localidade: str | None = None
    latitude: float | None = Field(None, description="Graus decimais, SIRGAS 2000 (srid).")
    longitude: float | None = None
    latitude_texto: str | None = Field(None, description="Coordenada como escrita no documento.")
    longitude_texto: str | None = None
    srid: int = 4674
    descricao_usos: str | None = None
    assinante_nome: str | None = None
    data_documento: date | None = None
    finalidades: list[Finalidade] = Field(default_factory=list)
    irrigacao: list[LinhaIrrigacao] = Field(default_factory=list)

    confianca_geral: Confianca | None = None
    pendencias: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
    validacao: Validacao = Field(default_factory=Validacao)
    versao: int = Field(1, ge=1, description="Sobe a cada gravação; usada para recusar edição concorrente (409).")
    campos: list[Campo] = Field(default_factory=list,
                                description="Um item por campo lido: confiança, leitura original e posição.")
    criado_em: datetime = Field(default_factory=agora)
    atualizado_em: datetime = Field(default_factory=agora)

    @model_validator(mode="after")
    def _sem_repeticao(self) -> "Requerimento":
        vistos: set[tuple[str, int | None]] = set()
        for c in self.campos:
            if (c.campo, c.indice) in vistos:
                raise ValueError(f"campo repetido no requerimento: {c.campo} (índice {c.indice})")
            vistos.add((c.campo, c.indice))
        ordens = [i.ordem for i in self.irrigacao]
        if len(ordens) != len(set(ordens)):
            raise ValueError("linha de irrigação repetida")
        return self


# ----------------------------------------------------------------- documento
class Revisao(Modelo):
    """Uma entrada do histórico. `tipo`:
    - correcao: o revisor mudou `campo` de `valor_anterior` para `valor_novo`;
    - validacao_com_pendencias: validado mesmo com pendências; `valor_anterior` = pendências na hora,
      `valor_novo` = justificativa;
    - reprocessamento: o documento foi lido de novo e as correções manuais foram reaplicadas;
    - desconsideracao: descartado na revisão; `valor_anterior` = situação que tinha, `valor_novo` = motivo;
    - reconsideracao: voltou para a revisão depois de desconsiderado; `valor_novo` = situação de volta."""

    em: datetime = Field(default_factory=agora)
    usuario_id: int | None = None
    tipo: Literal["correcao", "validacao_com_pendencias", "reprocessamento", "desconsideracao", "reconsideracao"]
    campo: str | None = None
    valor_anterior: str | None = None
    valor_novo: str | None = None


class ArquivoOriginal(Modelo):
    nome_original: str
    chave: str = Field(description="Onde o arquivo está no armazenamento.")
    content_type: str
    tamanho_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="O mesmo arquivo nunca é lido duas vezes.")


class Leitura(Modelo):
    """Como a última leitura foi feita (para comparar versões do pipeline nas análises de acurácia)."""

    versao_pipeline: str | None = None
    configuracao: dict[str, Any] | None = None
    tipo_entrada: Literal["pdf_texto", "pdf_imagem", "imagem"] | None = None
    metodo_extracao: Literal["texto_nativo", "ocr", "qrcode+texto_nativo", "qrcode+ocr"] | None = None
    paginas: int | None = Field(None, ge=0)
    tentativas: int = Field(0, ge=0)
    duracao_ms: int | None = None


class Assinatura(Modelo):
    tipo: Literal["digital", "manuscrita", "ausente", "indeterminada"] | None = None
    detalhes: dict[str, Any] | None = None


class QrCode(Modelo):
    conteudo: str | None = None
    processo_uuid: str | None = None
    processo_id: int | None = Field(None, description="protocolo_processo.id no SIGA.")


class PaginaLida(Modelo):
    numero: int = Field(ge=1)
    largura: int | None = None
    altura: int | None = None
    imagem_chave: str | None = Field(None, description="Imagem corrigida da página no armazenamento.")
    angulo_correcao: float | None = None
    metodo: Literal["texto_nativo", "ocr"] | None = None
    motor_ocr: str | None = None
    confianca_media: Confianca | None = None


class VinculoLote(Modelo):
    lote_uuid: str
    nome_arquivo: str | None = None
    em: datetime = Field(default_factory=agora)


class Documento(Modelo):
    schema_versao: int = SCHEMA_VERSAO
    uuid: str
    numero: str | None = Field(
        None, pattern=PADRAO_NUMERO,
        description="Número de registro legível e único: REQ-AAAA-NNNNNN (ano do recebimento, no fuso do Piauí, e "
                    "sequência dentro do ano). As partes de um arquivo com vários requerimentos levam o número dele "
                    "seguido de -1, -2... Nulo só em arquivos gravados antes da numeração (ferramentas numerar).",
    )
    status: StatusDocumento = "recebido"
    erro: str | None = None
    arquivo: ArquivoOriginal
    lote_origem_uuid: str | None = Field(None, description="Lote em que o arquivo chegou pela primeira vez.")
    lotes: list[VinculoLote] = Field(default_factory=list,
                                     description="Todos os lotes de que faz parte (reenvio entra no novo lote).")
    documento_pai_uuid: str | None = Field(None, description="Arquivo com vários requerimentos de onde esta parte saiu.")
    pagina_inicial: int | None = Field(None, description="Página do arquivo original onde esta parte começa.")
    partes: list[str] = Field(default_factory=list, description="Partes criadas quando o arquivo foi dividido.")
    validar_ao_ler: bool = Field(
        False, description="Enviado como já conferido: é validado assim que a leitura terminar, sem passar pela "
                           "conferência. Volta a false depois de validado (uma releitura posterior não valida de novo).",
    )
    conferencia_obrigatoria: bool = Field(
        False, description="A última leitura ficou com confiança geral abaixo de LIMIAR_CONFERENCIA_OBRIGATORIA: o "
                           "documento não é validado automaticamente (nem enviado como já conferido) e precisa ser "
                           "conferido na tela antes de validar. Recalculado a cada leitura.",
    )
    leitura: Leitura = Field(default_factory=Leitura)
    assinatura: Assinatura = Field(default_factory=Assinatura)
    qr_code: QrCode | None = None
    paginas_lidas: list[PaginaLida] = Field(default_factory=list)
    requerimento: Requerimento | None = None
    historico_de_revisoes: list[Revisao] = Field(default_factory=list)
    criado_por_id: int | None = None
    criado_em: datetime = Field(default_factory=agora)
    atualizado_em: datetime = Field(default_factory=agora)

    def lote_uuids(self) -> list[str]:
        return [v.lote_uuid for v in self.lotes]


class TextoPagina(Modelo):
    numero: int = Field(ge=1)
    texto: str | None = None
    palavras: list[dict[str, Any]] = Field(
        default_factory=list, description="Palavras do OCR: t = texto, c = confiança, b = caixa [x0, y0, x1, y1], p = página."
    )


class PaginasDocumento(Modelo):
    schema_versao: int = SCHEMA_VERSAO
    documento_uuid: str
    paginas: list[TextoPagina] = Field(default_factory=list)


class Lote(Modelo):
    """Contadores e situação do lote são calculados a partir dos documentos (índice), não gravados aqui."""

    schema_versao: int = SCHEMA_VERSAO
    uuid: str
    nome: str | None = None
    origem: Literal["upload", "zip", "pasta_monitorada"]
    criado_por_id: int | None = None
    criado_em: datetime = Field(default_factory=agora)


def atualizar_formato(dados: dict[str, Any]) -> dict[str, Any]:
    """Converte um JSON gravado numa versão anterior do contrato para a atual (nenhuma ainda)."""
    versao = dados.get("schema_versao", 1)
    if versao > SCHEMA_VERSAO:
        raise ValueError(f"arquivo gravado por uma versão mais nova da ferramenta (schema {versao})")
    return dados
