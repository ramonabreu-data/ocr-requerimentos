"use client";
import Link from "next/link";
import { useState } from "react";
import Progresso from "@/components/Progresso";
import Status from "@/components/Status";
import { api } from "@/lib/api";
import { dataHora, ORIGEM } from "@/lib/formato";
import { usePolling } from "@/lib/usePolling";

export default function Lotes() {
  const [pagina, setPagina] = useState(1);
  const { dados, erro } = usePolling(
    () => api.lotes(pagina),
    (d) => d.itens.some((l) => l.status === "processando"),
    4000,
  );
  const paginas = dados ? Math.max(Math.ceil(dados.total / 20), 1) : 1;

  return (
    <div className="pagina">
      <div className="cabecalho">
        <div>
          <h1>Lotes</h1>
          <p>Cada envio com vários arquivos, cada ZIP e cada dia da pasta do scanner forma um lote.</p>
        </div>
        <Link className="botao" href="/">
          Enviar arquivos
        </Link>
      </div>
      {erro && <div className="aviso aviso--erro">{erro}</div>}
      {!dados ? (
        <p className="carregando">Carregando lotes…</p>
      ) : dados.itens.length === 0 ? (
        <div className="vazio">
          <strong>Nenhum lote ainda</strong>
          Envie vários arquivos ou um ZIP na tela de envio para criar o primeiro.
        </div>
      ) : (
        <>
          <div className="rolagem-x">
            <table className="tabela">
              <thead>
                <tr>
                  <th scope="col">Lote</th>
                  <th scope="col" className="opcional">Origem</th>
                  <th scope="col">Andamento</th>
                  <th scope="col" className="num">Com divergências</th>
                  <th scope="col" className="num opcional">Erros</th>
                  <th scope="col">Situação</th>
                </tr>
              </thead>
              <tbody>
                {dados.itens.map((l) => (
                  <tr key={l.uuid}>
                    <td>
                      <Link className="principal" href={`/lotes/${l.uuid}`}>
                        {l.nome}
                      </Link>
                      <div className="discreto" style={{ fontSize: "0.85rem" }}>
                        {dataHora(l.created_at)}
                      </div>
                    </td>
                    <td className="opcional">{ORIGEM[l.origem] ?? l.origem}</td>
                    <td className="andamento">
                      <Progresso lote={l} />
                      <div className="discreto" style={{ fontSize: "0.85rem", marginTop: 4 }}>
                        {l.processados} de {l.total} lidos
                      </div>
                    </td>
                    <td className="num">{l.em_revisao}</td>
                    <td className="num opcional">{l.com_erro}</td>
                    <td>
                      <Status valor={l.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {paginas > 1 && (
            <div className="acoes" style={{ marginTop: "1rem" }}>
              <button className="botao botao--secundario" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
                Anteriores
              </button>
              <span className="discreto">
                Página {pagina} de {paginas}
              </span>
              <button className="botao botao--secundario" disabled={pagina >= paginas} onClick={() => setPagina((p) => p + 1)}>
                Próximos
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
