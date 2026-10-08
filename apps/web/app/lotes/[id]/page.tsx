"use client";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import Progresso from "@/components/Progresso";
import Status from "@/components/Status";
import TabelaDocumentos from "@/components/TabelaDocumentos";
import { api } from "@/lib/api";
import { dataHora, EM_ANDAMENTO, ORIGEM } from "@/lib/formato";
import { usePolling } from "@/lib/usePolling";

const FILTROS = [
  { valor: "", rotulo: "Todos" },
  { valor: "revisao", rotulo: "Com possíveis divergências" },
  { valor: "extraido", rotulo: "Prontos para validar" },
  { valor: "validado", rotulo: "Validados" },
  { valor: "erro", rotulo: "Com erro" },
];

export default function Lote() {
  const { id } = useParams<{ id: string }>();
  const [filtro, setFiltro] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const { dados: lote, erro, recarregar } = usePolling(
    () => api.lote(id),
    (l) => l.status === "processando" || l.documentos.some((d) => EM_ANDAMENTO.has(d.status)),
  );

  const docs = useMemo(
    () => (lote?.documentos ?? []).filter((d) => d.status !== "dividido" && (!filtro || d.status === filtro)),
    [lote, filtro],
  );

  if (erro && !lote) return <div className="pagina"><div className="aviso aviso--erro">{erro}</div></div>;
  if (!lote) return <p className="carregando">Carregando lote…</p>;

  const reprocessar = async () => {
    const r = await api.reprocessarErros(id);
    setAviso(`${r.reenfileirados} documento${r.reenfileirados === 1 ? "" : "s"} de volta na fila.`);
    recarregar();
  };

  return (
    <div className="pagina">
      <div className="cabecalho">
        <div>
          <h1>{lote.nome}</h1>
          <p>
            {ORIGEM[lote.origem] ?? lote.origem}, criado em {dataHora(lote.created_at)}
            {lote.finalizado_em && `, concluído em ${dataHora(lote.finalizado_em)}`}.
          </p>
        </div>
        <div className="acoes">
          <a className="botao botao--secundario" href={api.exportarUrl(id, "xlsx")}>
            Baixar planilha (XLSX)
          </a>
          <a className="botao botao--secundario" href={api.exportarUrl(id, "csv")}>
            Baixar CSV
          </a>
          {lote.com_erro > 0 && (
            <button className="botao" onClick={reprocessar}>
              {lote.com_erro === 1 ? "Ler de novo o documento com erro" : `Ler de novo os ${lote.com_erro} com erro`}
            </button>
          )}
        </div>
      </div>

      <div className="bloco">
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", marginBottom: "0.6rem" }}>
          <Status valor={lote.status} />
          <span className="discreto">
            {lote.processados} de {lote.total} documentos lidos
          </span>
        </div>
        <Progresso lote={lote} legenda />
      </div>

      {aviso && (
        <div className="aviso aviso--ok" role="status" style={{ marginTop: "1rem" }}>
          {aviso}
        </div>
      )}

      <section className="secao" style={{ marginTop: "2rem" }}>
        <div className="filtros" role="group" aria-label="Filtrar documentos">
          {FILTROS.map((f) => (
            <button
              key={f.valor}
              className={`botao botao--pequeno${filtro === f.valor ? "" : " botao--secundario"}`}
              aria-pressed={filtro === f.valor}
              onClick={() => setFiltro(f.valor)}
            >
              {f.rotulo}
            </button>
          ))}
        </div>
        <TabelaDocumentos
          docs={docs}
          origem={`/lotes/${id}`}
          vazio={
            <>
              <strong>Nenhum documento neste filtro</strong>
              Escolha outro filtro acima.
            </>
          }
        />
      </section>
    </div>
  );
}
