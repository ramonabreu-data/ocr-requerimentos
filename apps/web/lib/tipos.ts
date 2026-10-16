export type StatusDocumento =
  | "recebido"
  | "processando"
  | "extraido"
  | "revisao"
  | "validado"
  | "erro"
  | "dividido"
  /** descartado na revisão (não é requerimento, repetido, ilegível): não é validado nem vai ao SIGA */
  | "desconsiderado";

export type BBox = [number, number, number, number];

export interface DocumentoResumo {
  uuid: string;
  /** número de registro legível: REQ-2026-000123 (parte de arquivo dividido: REQ-2026-000123-2) */
  numero: string | null;
  nome_original: string;
  status: StatusDocumento;
  erro: string | null;
  tipo_entrada: string | null;
  metodo_extracao: string | null;
  paginas: number | null;
  assinatura_tipo: string | null;
  lote_uuid: string | null;
  documento_pai_uuid: string | null;
  requerente_nome: string | null;
  cpf_cnpj: string | null;
  municipio: string | null;
  procedimento: string | null;
  data_documento: string | null;
  validado_em: string | null;
  confianca_geral: number | null;
  pendencias: string[];
  /** lido com confiança abaixo do limiar: nunca é validado sozinho, nem enviado como já conferido */
  conferencia_obrigatoria: boolean;
  created_at: string;
  updated_at: string;
  duracao_ms: number | null;
}

export interface Campo {
  campo: string;
  rotulo: string;
  indice: number | null;
  valor_bruto: string | null;
  valor_normalizado: string | null;
  confianca: number | null;
  pagina: number | null;
  bbox: BBox | null;
  valido: boolean | null;
  obrigatorio: boolean;
  corrigido_manual: boolean;
  mensagem: string | null;
}

export interface ItemIrrigacao {
  ordem: number;
  sistema: string | null;
  sistema_id: number | null;
  area_ha: number | null;
  cultura: string | null;
  cultura_id: number | null;
  confianca: number | null;
  valido: boolean;
}

export interface Requerimento {
  requerente_nome: string | null;
  cpf_cnpj: string | null;
  tipo_pessoa: string | null;
  pessoa_id: number | null;
  procedimento: string | null;
  tipo_intervencao: string | null;
  municipio: string | null;
  municipio_id: number | null;
  localidade: string | null;
  latitude: number | null;
  longitude: number | null;
  descricao_usos: string | null;
  assinante_nome: string | null;
  data_documento: string | null;
  confianca_geral: number | null;
  pendencias: string[];
  avisos: string[];
  status_validacao: string;
  validado_em: string | null;
  /** conferencia: validado na tela; envio: enviado como já conferido e validado ao fim da leitura */
  validacao_modo: "conferencia" | "envio";
  /** muda a cada gravação; enviada nas correções/validação para detectar edição simultânea */
  versao: number;
  finalidades: FinalidadeLida[];
  irrigacao: ItemIrrigacao[];
  campos: Campo[];
}

export interface CampoDetalhe {
  chave: string;
  rotulo: string;
  tipo: "texto" | "numero" | "inteiro" | "data" | "lista";
  dominio: string | null;
  obrigatorio: boolean;
}

/** Como a finalidade aparece no formulário: campos "Rótulo: valor" e itens (tabela, lista ou pares). */
export interface EstruturaFinalidade {
  nome: string;
  campos: CampoDetalhe[];
  colunas: CampoDetalhe[];
  modo_linhas: "tabela" | "lista" | "pares" | null;
  rotulo_linhas: string;
}

export interface FinalidadeLida {
  texto: string | null;
  tipo_finalidade_id: number | null;
  confianca: number | null;
  valido: boolean;
  chave: string | null;
  detalhes: Record<string, unknown> | null;
  estrutura: EstruturaFinalidade | null;
}

export interface PaginaLida {
  numero: number;
  largura: number;
  altura: number;
  metodo: string;
  motor_ocr: string | null;
  confianca_media: number | null;
  angulo_correcao: number | null;
  tem_imagem: boolean;
}

export interface DocumentoDetalhe extends DocumentoResumo {
  filhos: DocumentoResumo[];
  assinatura_detalhes: Record<string, unknown> | null;
  qr_conteudo: string | null;
  processo_uuid: string | null;
  processo_id: number | null;
  /** enviado como já conferido e ainda não validado (a validação acontece ao fim da leitura) */
  validar_ao_ler: boolean;
  /** confiança abaixo do limiar: precisa passar pela conferência na tela antes de validar */
  conferencia_obrigatoria: boolean;
  paginas_lidas: PaginaLida[];
  requerimento: Requerimento | null;
}

export interface LoteResumo {
  uuid: string;
  nome: string | null;
  origem: string;
  status: string;
  total: number;
  processados: number;
  em_revisao: number;
  validados: number;
  com_erro: number;
  desconsiderados: number;
  /** documentos do lote abaixo do limiar de confiança que ainda aguardam a conferência obrigatória */
  conferencia_obrigatoria: number;
  created_at: string;
  finalizado_em: string | null;
}

export interface LoteDetalhe extends LoteResumo {
  documentos: DocumentoResumo[];
}

export interface RespostaLote extends LoteResumo {
  recebidos: number;
  novos: number;
  duplicados: { arquivo: string; documento_uuid: string; status: string }[];
  formato_nao_suportado: string[];
}

export interface OpcoesFiltro {
  procedimentos: { nome: string; total: number }[];
  municipios: { nome: string; total: number }[];
}

export interface Referencia {
  id: number | null;
  nome: string;
}

export interface RegistroRevisao {
  campo: string;
  valor_anterior: string | null;
  valor_novo: string | null;
  usuario_id: number | null;
  created_at: string;
}
