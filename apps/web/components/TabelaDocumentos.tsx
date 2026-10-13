import Link from "next/link";
import Status from "./Status";
import { pct } from "@/lib/formato";
import type { DocumentoResumo } from "@/lib/tipos";

/** `origem`: lista onde a tabela está; a conferência volta para ela depois de validar. */
export default function TabelaDocumentos({
  docs,
  vazio,
  origem,
}: {
  docs: DocumentoResumo[];
  vazio: React.ReactNode;
  origem?: string;
}) {
  if (!docs.length) return <div className="vazio">{vazio}</div>;
  return (
    <div className="rolagem-x">
      <table className="tabela">
        <thead>
          <tr>
            <th scope="col">Número</th>
            <th scope="col">Arquivo</th>
            <th scope="col">Requerente</th>
            <th scope="col" className="opcional">Município</th>
            <th scope="col">Situação</th>
            <th scope="col" className="num opcional">Confiança</th>
            <th scope="col" className="opcional">O que conferir</th>
          </tr>
        </thead>
        <tbody>
          {docs.map((d) => (
            <tr key={d.uuid}>
              <td className="numero">{d.numero ?? <span className="discreto">—</span>}</td>
              <td>
                <Link
                  className="principal"
                  href={origem ? `/documentos/${d.uuid}?de=${encodeURIComponent(origem)}` : `/documentos/${d.uuid}`}
                >
                  {d.nome_original}
                </Link>
              </td>
              <td>
                {d.requerente_nome ?? <span className="discreto">—</span>}
                {d.cpf_cnpj && (
                  <div className="mono discreto" style={{ fontSize: "0.85rem" }}>
                    {d.cpf_cnpj}
                  </div>
                )}
              </td>
              <td className="opcional">{d.municipio ?? "—"}</td>
              <td>
                <Status valor={d.status} />
              </td>
              <td className="num opcional">{pct(d.confianca_geral)}</td>
              <td className="opcional" style={{ maxWidth: "34ch" }}>
                {d.status === "erro" ? (
                  <span className="mensagem--erro">{d.erro}</span>
                ) : d.pendencias.length ? (
                  <>
                    {d.pendencias[0]}
                    {d.pendencias.length > 1 && <span className="discreto"> e mais {d.pendencias.length - 1}</span>}
                  </>
                ) : (
                  <span className="discreto">Nada pendente</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
