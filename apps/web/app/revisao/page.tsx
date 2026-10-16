"use client";
import { useEffect, useState } from "react";
import TabelaDocumentos from "@/components/TabelaDocumentos";
import { api } from "@/lib/api";
import type { DocumentoResumo } from "@/lib/tipos";

type Aba = "obrigatoria" | "revisao" | "extraido";

export default function Revisao() {
  // null até decidir a aba inicial: ?aba=obrigatoria, ou ela mesma quando há conferências obrigatórias pendentes
  const [aba, setAba] = useState<Aba | null>(null);
  const [busca, setBusca] = useState("");
  const [docs, setDocs] = useState<DocumentoResumo[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [obrigatorias, setObrigatorias] = useState(0);
  const [limiar, setLimiar] = useState(50);

  useEffect(() => {
    const pedida = new URLSearchParams(window.location.search).get("aba") === "obrigatoria";
    api
      .estatisticas()
      .then((e) => {
        setObrigatorias(e.conferencia_obrigatoria ?? 0);
        if (e.limiar_conferencia_obrigatoria != null) setLimiar(e.limiar_conferencia_obrigatoria);
        setAba((a) => a ?? (pedida || e.conferencia_obrigatoria > 0 ? "obrigatoria" : "revisao"));
      })
      .catch(() => setAba((a) => a ?? (pedida ? "obrigatoria" : "revisao")));
  }, []);

  useEffect(() => {
    if (!aba) return;
    const t = setTimeout(() => {
      // a conferência obrigatória junta as duas filas: com divergências e prontos para validar
      const params: Record<string, string> =
        aba === "obrigatoria"
          ? { status: "revisao,extraido", obrigatoria: "true", tamanho: "100" }
          : { status: aba, tamanho: "100" };
      if (busca.trim()) params.busca = busca.trim();
      api
        .documentos(params)
        .then((r) => {
          setDocs(r.itens);
          setErro(null);
          if (aba === "obrigatoria" && !busca.trim()) setObrigatorias(r.total);
        })
        .catch((e) => setErro(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [aba, busca]);

  const trocarAba = (nova: Aba) => {
    setAba(nova);
    const url = new URL(window.location.href);
    if (nova === "obrigatoria") url.searchParams.set("aba", "obrigatoria");
    else url.searchParams.delete("aba");
    window.history.replaceState(window.history.state, "", url);
  };

  return (
    <div className="pagina">
      <div className="cabecalho">
        <div>
          <h1>Revisão</h1>
          <p>
            Documentos com algum campo inválido, ilegível ou de leitura incerta. Os prontos para validar não têm
            pendências, mas ainda aguardam a conferência de uma pessoa. Os de conferência obrigatória foram lidos com
            confiança baixa e só são validados depois de conferidos na tela.
          </p>
        </div>
      </div>
      <div className="filtros">
        <div className="acoes" role="group" aria-label="Fila">
          <button
            className={`botao${aba === "obrigatoria" ? "" : " botao--secundario"}`}
            aria-pressed={aba === "obrigatoria"}
            onClick={() => trocarAba("obrigatoria")}
          >
            Conferência obrigatória
            {obrigatorias > 0 && <span className="contador contador--alerta">{obrigatorias}</span>}
          </button>
          <button className={`botao${aba === "revisao" ? "" : " botao--secundario"}`} aria-pressed={aba === "revisao"} onClick={() => trocarAba("revisao")}>
            Com possíveis divergências
          </button>
          <button className={`botao${aba === "extraido" ? "" : " botao--secundario"}`} aria-pressed={aba === "extraido"} onClick={() => trocarAba("extraido")}>
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
      {aba === "obrigatoria" && (
        <p className="dica" style={{ margin: "-0.5rem 0 1rem", maxWidth: "68ch" }}>
          Requerimentos lidos com confiança abaixo de {limiar}%. Não foram validados automaticamente, nem quando
          enviados como já conferidos: abra cada um na tela de conferência e confira campo a campo com a folha antes de
          validar.
        </p>
      )}
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
            ) : aba === "obrigatoria" ? (
              <>
                <strong>Nenhuma conferência obrigatória pendente</strong>
                Requerimentos lidos com confiança abaixo de {limiar}% aparecem aqui até serem conferidos e validados.
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
