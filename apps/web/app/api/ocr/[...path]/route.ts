// Proxy do navegador para a API Python. A chave de API e a identidade do usuário ficam no
// servidor; o navegador nunca fala direto com a API.
import type { NextRequest } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const API_KEY = process.env.API_KEY ?? "";

export const dynamic = "force-dynamic";

const REPASSAR_RESPOSTA = ["content-type", "content-disposition", "cache-control", "content-length"];

async function usuarioAtual(_req: NextRequest): Promise<string | null> {
  // Integração com o login do SIGA (Better Auth): troque por
  //   const sessao = await auth.api.getSession({ headers: _req.headers });
  //   if (!sessao) return null;  // e responda 401 abaixo
  //   return String(sessao.user.id);
  return process.env.DEV_USUARIO_ID ?? null;
}

type Contexto = { params: Promise<{ path: string[] }> };

async function repassar(req: NextRequest, ctx: Contexto): Promise<Response> {
  const { path } = await ctx.params;
  if (path.some((p) => p === ".." || p.includes("/"))) {
    return Response.json({ detail: "caminho inválido" }, { status: 400 });
  }
  const destino = new URL(`${API_URL.replace(/\/$/, "")}/${path.map(encodeURIComponent).join("/")}`);
  destino.search = req.nextUrl.search;

  const cabecalhos = new Headers();
  const tipo = req.headers.get("content-type");
  if (tipo) cabecalhos.set("content-type", tipo);
  if (API_KEY) cabecalhos.set("x-api-key", API_KEY);
  const usuario = await usuarioAtual(req);
  if (usuario) cabecalhos.set("x-usuario-id", usuario);

  const temCorpo = !["GET", "HEAD"].includes(req.method);
  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers: cabecalhos,
    cache: "no-store",
  };
  if (temCorpo) {
    init.body = req.body;
    init.duplex = "half"; // necessário no Node para repassar o corpo em stream (uploads grandes)
  }

  let resposta: Response;
  try {
    resposta = await fetch(destino, init);
  } catch {
    return Response.json({ detail: "O serviço de OCR não respondeu. Verifique se a API está no ar." }, { status: 502 });
  }
  const saida = new Headers();
  for (const h of REPASSAR_RESPOSTA) {
    const v = resposta.headers.get(h);
    if (v) saida.set(h, v);
  }
  return new Response(resposta.body, { status: resposta.status, headers: saida });
}

export { repassar as GET, repassar as POST, repassar as PATCH, repassar as PUT, repassar as DELETE };
