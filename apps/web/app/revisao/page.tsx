"use client";
import { useEffect, useState } from "react";
import TabelaDocumentos from "@/components/TabelaDocumentos";
import { api } from "@/lib/api";
import type { DocumentoResumo } from "@/lib/tipos";

export default function Revisao() {
  const [aba, setAba] = useState<"revisao" | "extraido">("revisao");
  const [busca, setBusca] = useState("");
  const [docs, setDocs] = useState<DocumentoResumo[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      const params: Record<string, string> = { status: aba, tamanho: "100" };
      if (busca.trim()) params.busca = busca.trim();
      api
        .documentos(params)
        .then((r) => {
          setDocs(r.itens);
          setErro(null);
        })
        .catch((e) => setErro(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [aba, busca]);

  return (
    <div className="pagina">
      <div className="cabecalho">
        <div>
          <h1>Revisão</h1>
          <p>
            Documentos com algum campo inválido, ilegível ou de leitura incerta. Os prontos para validar não têm
            pendências, mas ainda aguardam a conferência de uma pessoa.
          </p>
        </div>
      </div>
      <div className="filtros">
        <div className="acoes" role="group" aria-label="Fila">
          <button className={`botao${aba === "revisao" ? "" : " botao--secundario"}`} aria-pressed={aba === "revisao"} onClick={() => setAba("revisao")}>
            Com possíveis divergências
          </button>
          <button className={`botao${aba === "extraido" ? "" : " botao--secundario"}`} aria-pressed={aba === "extraido"} onClick={() => setAba("extraido")}>
            Prontos para validar
          </button>
        </div>
        <label className="pular" htmlFor="busca">
          Buscar
        </label>
        <input
          id="busca"
          className="entrada"
          type="search"
          placeholder="Buscar por nome, CPF/CNPJ, município ou arquivo"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
        />
      </div>
      {erro && <div className="aviso aviso--erro">{erro}</div>}
      {docs === null ? (
        <p className="carregando">Carregando…</p>
      ) : (
        <TabelaDocumentos
          docs={docs}
          origem="/revisao"
          vazio={
            busca ? (
              <>
                <strong>Nada encontrado para “{busca}”</strong>
                Confira a grafia ou busque pelo CPF/CNPJ.
              </>
            ) : aba === "revisao" ? (
              <>
                <strong>Fila de revisão vazia</strong>
                Todos os documentos lidos estão sem pendências.
              </>
            ) : (
              <>
                <strong>Nenhum documento aguardando validação</strong>
                Documentos sem pendências aparecem aqui assim que a leitura termina.
              </>
            )
          }
        />
      )}
    </div>
  );
}
