// Mostra um JSON como árvore: objetos e listas abrem e fecham (details/summary, acessível por teclado),
// valores coloridos pelo tipo. `abertoAte`: níveis abertos ao montar (Infinity = tudo aberto).

type Json = string | number | boolean | null | Json[] | { [chave: string]: Json };

function Valor({ v }: { v: Json }) {
  if (v === null) return <span className="json-nulo">null</span>;
  if (typeof v === "string") return <span className="json-texto">&quot;{v}&quot;</span>;
  if (typeof v === "number") return <span className="json-numero">{v}</span>;
  return <span className="json-logico">{String(v)}</span>;
}

function Rotulo({ chave, indice }: { chave?: string; indice: boolean }) {
  if (chave === undefined) return null;
  return (
    <>
      <span className={indice ? "json-indice" : "json-chave"}>{indice ? chave : `"${chave}"`}</span>
      <span className="json-pontuacao">: </span>
    </>
  );
}

// item de lista fechado mostra o que o identifica (ex.: "latitude" num item de campos)
const IDENTIFICADORES = ["campo", "nome", "texto", "tipo", "arquivo"];

function identificador(v: { [chave: string]: Json }): string | null {
  for (const k of IDENTIFICADORES) if (typeof v[k] === "string" && v[k]) return v[k] as string;
  return null;
}

function No({ chave, indice, v, nivel, abertoAte }: { chave?: string; indice: boolean; v: Json; nivel: number; abertoAte: number }) {
  if (v === null || typeof v !== "object") {
    return (
      <li className="json-linha">
        <Rotulo chave={chave} indice={indice} />
        <Valor v={v} />
      </li>
    );
  }
  const lista = Array.isArray(v);
  const filhos: [string, Json][] = lista ? v.map((x, i) => [String(i), x]) : Object.entries(v);
  const [abre, fecha] = lista ? ["[", "]"] : ["{", "}"];
  if (!filhos.length) {
    return (
      <li className="json-linha">
        <Rotulo chave={chave} indice={indice} />
        <span className="json-pontuacao">
          {abre}
          {fecha}
        </span>
      </li>
    );
  }
  const n = filhos.length;
  const id = indice && !lista ? identificador(v as { [chave: string]: Json }) : null;
  return (
    <li>
      <details open={nivel < abertoAte}>
        <summary>
          <Rotulo chave={chave} indice={indice} />
          <span className="json-pontuacao" data-fecha={fecha}>
            {abre}
          </span>
          {id && <span className="json-id">{id}</span>}
          <span className="json-resumo">{lista ? `${n} ${n === 1 ? "item" : "itens"}` : `${n} ${n === 1 ? "campo" : "campos"}`}</span>
        </summary>
        <ul>
          {filhos.map(([k, x]) => (
            <No key={k} chave={k} indice={lista} v={x} nivel={nivel + 1} abertoAte={abertoAte} />
          ))}
        </ul>
        <span className="json-pontuacao json-fecha">{fecha}</span>
      </details>
    </li>
  );
}

export default function ArvoreJson({ dados, abertoAte = 2, rotulo }: { dados: unknown; abertoAte?: number; rotulo: string }) {
  return (
    <ul className="arvore-json" aria-label={rotulo}>
      <No indice={false} v={dados as Json} nivel={0} abertoAte={abertoAte} />
    </ul>
  );
}
