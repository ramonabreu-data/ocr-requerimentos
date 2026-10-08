"use client";
import type { MutableRefObject } from "react";
import { nivelConfianca } from "@/lib/formato";
import type { Campo, CampoDetalhe, FinalidadeLida } from "@/lib/tipos";

/** Chave usada na correção: "criacao_animal.cabecas#2" (item) ou "termoeletrica.potencia". */
export const chaveDetalhe = (campo: string, indice: number | null) => (indice == null ? campo : `${campo}#${indice}`);

/** Lista do formulário usada em cada campo do tipo "lista" (datalist da página). */
export const listaDoCampo = (c: CampoDetalhe) => (c.tipo !== "lista" ? undefined : c.dominio === "municipio" ? "lista-municipios" : `lista-${c.dominio}`);

interface Props {
  fin: FinalidadeLida;
  porChave: Record<string, Campo>;
  valores: Record<string, string>;
  itens: number[];
  validado: boolean;
  ativo: string | null;
  entradas: MutableRefObject<Record<string, HTMLInputElement | HTMLTextAreaElement | null>>;
  onAtivar: (k: string) => void;
  onMudar: (chave: string, valor: string) => void;
  onAdicionarItem: () => void;
  onRemoverItem: (n: number) => void;
}

export default function DetalhesFinalidade({ fin, porChave, valores, itens, validado, ativo, entradas, onAtivar, onMudar, onAdicionarItem, onRemoverItem }: Props) {
  const e = fin.estrutura!;
  const prefixo = fin.chave!;

  const entrada = (def: CampoDetalhe, indice: number | null, rotuloAcessivel: string) => {
    const nome = `${prefixo}.${def.chave}`;
    const k = `${nome}:${indice ?? ""}`; // mesma chave do visor (campo:indice)
    const c = porChave[k];
    const nivel = c?.corrigido_manual ? "ok" : c ? nivelConfianca(c.confianca, c.valido) : "ok";
    const vazioObrigatorio = def.obrigatorio && !(valores[chaveDetalhe(nome, indice)] ?? "").trim();
    const numerico = def.tipo === "numero" || def.tipo === "inteiro";
    return (
      <div className={`campo${k === ativo ? " campo--ativo" : ""}${nivel !== "ok" ? ` campo--${nivel}` : ""}`}>
        {indice == null && (
          <label htmlFor={`det-${k}`}>
            <span>
              {def.rotulo} {c?.corrigido_manual && <span className="selo">corrigido</span>}
            </span>
          </label>
        )}
        <input
          id={`det-${k}`}
          aria-label={indice == null ? undefined : rotuloAcessivel}
          aria-invalid={c?.valido === false || undefined}
          list={listaDoCampo(def)}
          className={numerico || def.tipo === "data" ? "mono" : undefined}
          inputMode={numerico ? "decimal" : undefined}
          placeholder={def.tipo === "data" ? "aaaa-mm-dd" : undefined}
          value={valores[chaveDetalhe(nome, indice)] ?? ""}
          readOnly={validado}
          title={c?.mensagem ?? undefined}
          ref={(el) => {
            entradas.current[k] = el;
          }}
          onFocus={() => onAtivar(k)}
          onChange={(ev) => onMudar(chaveDetalhe(nome, indice), ev.target.value)}
        />
        {c?.valido === false && c.mensagem ? (
          <p className="mensagem mensagem--erro">{c.mensagem}</p>
        ) : c?.mensagem && nivel === "atencao" ? (
          <p className="mensagem mensagem--atencao">{c.mensagem}</p>
        ) : !c && vazioObrigatorio && indice == null ? (
          <p className="mensagem mensagem--erro">não preenchido</p>
        ) : null}
      </div>
    );
  };

  const titulo = `det-${prefixo}`;
  return (
    <section className="grupo" aria-labelledby={titulo}>
      <h2 id={titulo}>{e.nome}</h2>
      {e.campos.length > 0 && <div className="grade">{e.campos.map((def) => <div key={def.chave}>{entrada(def, null, def.rotulo)}</div>)}</div>}
      {e.modo_linhas && (
        <>
          <h3 className="subtitulo">{e.rotulo_linhas[0].toUpperCase() + e.rotulo_linhas.slice(1)}</h3>
          {itens.length === 0 ? (
            <p className="dica">Nenhum item lido. {validado ? "" : "Use “Adicionar item” para informar."}</p>
          ) : (
            <div className="rolagem-x">
              <table className="irrigacao detalhes">
                <thead>
                  <tr>
                    {e.colunas.map((c) => (
                      <th scope="col" key={c.chave}>
                        {c.rotulo}
                      </th>
                    ))}
                    <th scope="col" className="col-remover">
                      <span className="pular">Ações</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {itens.map((n, pos) => (
                    <tr key={n}>
                      {e.colunas.map((c) => (
                        <td key={c.chave} data-rotulo={c.rotulo} className={c.tipo === "numero" || c.tipo === "inteiro" ? "area" : undefined}>
                          {entrada(c, n, `${c.rotulo}, item ${pos + 1}`)}
                        </td>
                      ))}
                      <td className="remover">
                        {!validado && (
                          <button className="botao botao--texto botao--pequeno" onClick={() => onRemoverItem(n)} aria-label={`Remover item ${pos + 1} de ${e.nome}`}>
                            Remover
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!validado && (
            <button className="botao botao--secundario botao--pequeno" style={{ marginTop: "0.6rem" }} onClick={onAdicionarItem}>
              Adicionar item
            </button>
          )}
        </>
      )}
    </section>
  );
}
