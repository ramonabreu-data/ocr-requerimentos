import type {
  DocumentoDetalhe,
  DocumentoResumo,
  LoteDetalhe,
  LoteResumo,
  OpcoesFiltro,
  Referencia,
  RegistroRevisao,
  RespostaLote,
} from "./tipos";

const BASE = "/api/ocr";

export class ErroApi extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${caminho}`, { cache: "no-store", ...init });
  if (!r.ok) {
    let msg = `A API respondeu com erro ${r.status}.`;
    try {
      const corpo = await r.json();
      if (typeof corpo?.detail === "string") msg = corpo.detail;
      else if (Array.isArray(corpo?.detail)) msg = corpo.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* corpo não-JSON */
    }
    throw new ErroApi(r.status, msg);
  }
  return r.json() as Promise<T>;
}

const json = (corpo: unknown, method = "POST"): RequestInit => ({
  method,
  headers: { "content-type": "application/json" },
  body: JSON.stringify(corpo),
});

export interface CorpoCorrecao {
  campos?: Record<string, string | null>;
  finalidades?: string[];
  irrigacao?: { sistema: string; area: string; cultura: string }[];
  /** detalhes das finalidades: {"criacao_animal.cabecas#2": "150"}; item com tudo vazio é removido */
  detalhes?: Record<string, string>;
  /** versão do requerimento que a tela carregou (a API recusa com 409 se outro gravou depois) */
  versao?: number;
}

export const api = {
  enviarDocumento(arquivo: File) {
    const f = new FormData();
    f.append("arquivo", arquivo);
    return pedir<DocumentoResumo & { duplicado: boolean }>("/documentos", { method: "POST", body: f });
  },
  criarLote(arquivos: File[], nome?: string) {
    const f = new FormData();
    arquivos.forEach((a) => f.append("arquivos", a));
    if (nome) f.append("nome", nome);
    return pedir<RespostaLote>("/lotes", { method: "POST", body: f });
  },
  lotes: (pagina = 1) => pedir<{ total: number; itens: LoteResumo[] }>(`/lotes?pagina=${pagina}`),
  lote: (uuid: string) => pedir<LoteDetalhe>(`/lotes/${uuid}`),
  reprocessarErros: (uuid: string) =>
    pedir<{ reenfileirados: number }>(`/lotes/${uuid}/reprocessar-erros`, { method: "POST" }),
  exportarUrl: (uuid: string, formato: "csv" | "xlsx" | "json") => `${BASE}/lotes/${uuid}/exportar?formato=${formato}`,
  revisao: () => pedir<{ total: number; itens: DocumentoResumo[] }>("/revisao"),
  documentos: (params: Record<string, string>) =>
    pedir<{ total: number; itens: DocumentoResumo[] }>(`/documentos?${new URLSearchParams(params)}`),
  documento: (uuid: string) => pedir<DocumentoDetalhe>(`/documentos/${uuid}`),
  imagemUrl: (uuid: string, pagina: number) => `${BASE}/documentos/${uuid}/paginas/${pagina}/imagem`,
  arquivoUrl: (uuid: string) => `${BASE}/documentos/${uuid}/arquivo`,
  // a versão na URL garante que o navegador baixe o arquivo gravado mais recente
  // JSON padrão do SIGA com todos os requerimentos validados, gerado na hora
  jsonConsolidadoUrl: `${BASE}/siga/requerimentos.json`,
  jsonUrl: (uuid: string, versao?: number) => `${BASE}/documentos/${uuid}/json${versao ? `?v=${versao}` : ""}`,
  reprocessar: (uuid: string) => pedir<DocumentoResumo>(`/documentos/${uuid}/reprocessar`, { method: "POST" }),
  corrigir: (uuid: string, corpo: CorpoCorrecao) =>
    pedir<DocumentoDetalhe>(`/documentos/${uuid}/correcoes`, json(corpo, "PATCH")),
  validar: (uuid: string, forcar = false, justificativa?: string, versao?: number) =>
    pedir<DocumentoDetalhe>(`/documentos/${uuid}/validar`, json({ forcar, justificativa, versao })),
  revisoes: (uuid: string) => pedir<RegistroRevisao[]>(`/documentos/${uuid}/revisoes`),
  referencias: (tipo: string) => pedir<Referencia[]>(`/referencias/${tipo}`),
  filtros: () => pedir<OpcoesFiltro>("/filtros"),
  estatisticas: () => pedir<{ por_status: Record<string, number>; lotes: number }>("/estatisticas"),
};
