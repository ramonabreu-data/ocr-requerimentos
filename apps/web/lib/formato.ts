export const ROTULO_STATUS: Record<string, string> = {
  recebido: "Na fila",
  processando: "Lendo",
  extraido: "Pronto para validar",
  revisao: "Com possíveis divergências",
  validado: "Validado",
  erro: "Erro",
  dividido: "Dividido em partes",
  desconsiderado: "Desconsiderado",
  pendente: "Pendente",
  concluido: "Concluído",
  concluido_com_erros: "Concluído com erros",
};

export const EM_ANDAMENTO = new Set(["recebido", "processando"]);

/** Lista para onde a conferência volta depois de validar: a de onde o documento foi aberto (`?de=`),
 *  ou a de requerimentos. Só aceita caminhos conhecidos. */
export function listaDeOrigem(de: string | null | undefined): { href: string; rotulo: string } {
  if (de === "/revisao") return { href: de, rotulo: "Ir para a fila de revisão" };
  if (de && /^\/lotes\/[0-9a-f-]{36}$/.test(de)) return { href: de, rotulo: "Ir para o lote" };
  // lista de requerimentos com os filtros que estavam aplicados
  if (de && /^\/requerimentos\?[^#\\]*$/.test(de) && !de.includes("//"))
    return { href: de, rotulo: "Ir para a lista de requerimentos" };
  return { href: "/requerimentos", rotulo: "Ir para a lista de requerimentos" };
}

export function dataHora(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function data(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

export function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v)}%`;
}

export function coord(v: number | null | undefined): string {
  return v == null ? "—" : v.toLocaleString("pt-BR", { minimumFractionDigits: 6, maximumFractionDigits: 7 });
}

export function nivelConfianca(v: number | null | undefined, valido: boolean | null = true): "ok" | "atencao" | "erro" {
  if (valido === false) return "erro";
  if (v == null || v < 80) return "atencao";
  return "ok";
}

export const ORIGEM: Record<string, string> = {
  upload: "Envio pela tela",
  zip: "Arquivo ZIP",
  pasta_monitorada: "Pasta do scanner",
};

export const ASSINATURA: Record<string, string> = {
  digital: "Assinatura digital",
  manuscrita: "Assinada à mão",
  ausente: "Sem assinatura",
  indeterminada: "Assinatura não verificada",
};

export const METODO: Record<string, string> = {
  texto_nativo: "Texto do PDF",
  ocr: "Reconhecimento óptico",
  "qrcode+texto_nativo": "QR code e texto do PDF",
  "qrcode+ocr": "QR code e reconhecimento óptico",
};
