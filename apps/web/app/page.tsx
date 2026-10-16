"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Icone from "@/components/Icone";
import Progresso from "@/components/Progresso";
import Status from "@/components/Status";
import { api } from "@/lib/api";
import { dataHora, ORIGEM } from "@/lib/formato";
import type { LoteResumo, RespostaLote } from "@/lib/tipos";

const ACEITOS = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp,.heic,.heif,.zip";

function tamanho(bytes: number) {
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

export default function Envio() {
  const router = useRouter();
  const entrada = useRef<HTMLInputElement>(null);
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [nome, setNome] = useState("");
  // true: os arquivos já foram conferidos; cada requerimento é validado e armazenado assim que for lido
  const [jaConferidos, setJaConferidos] = useState(false);
  const [arrastando, setArrastando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [lotes, setLotes] = useState<LoteResumo[] | null>(null);
  const [parcial, setParcial] = useState<RespostaLote | null>(null);

  useEffect(() => {
    api.lotes().then((r) => setLotes(r.itens.slice(0, 5))).catch(() => setLotes([]));
  }, []);

  const adicionar = (lista: FileList | null) => {
    if (!lista) return;
    // copia já: a FileList do input (zerado logo depois) e a do arrastar-e-soltar (limpa ao fim do
    // evento) ficam vazias antes de o React rodar o atualizador abaixo
    const novos = Array.from(lista);
    setErro(null);
    setArquivos((atual) => {
      const nomes = new Set(atual.map((a) => a.name + a.size));
      return [...atual, ...novos.filter((a) => !nomes.has(a.name + a.size))];
    });
  };

  const umSoDocumento = arquivos.length === 1 && !arquivos[0].name.toLowerCase().endsWith(".zip");

  const enviar = async () => {
    setEnviando(true);
    setErro(null);
    setParcial(null);
    try {
      if (umSoDocumento) {
        const d = await api.enviarDocumento(arquivos[0], jaConferidos);
        router.push(`/documentos/${d.uuid}`);
      } else {
        const l = await api.criarLote(arquivos, nome.trim() || undefined, jaConferidos);
        if (l.duplicados.length || l.formato_nao_suportado.length) {
          // alguns arquivos ficaram de fora: mostra quais antes de ir para o lote
          setParcial(l);
          setArquivos([]);
          setEnviando(false);
        } else {
          router.push(`/lotes/${l.uuid}`);
        }
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
      setEnviando(false);
    }
  };

  return (
    <div className="pagina">
      <div className="cabecalho">
        <div>
          <h1>Enviar requerimentos digitalizados</h1>
          <p>
            PDF do sistema, PDF do scanner, foto ou imagem. Vários arquivos ou um ZIP viram um lote; um PDF com vários
            requerimentos é separado automaticamente.
          </p>
        </div>
      </div>

      <div className="envio">
        <div>
          <div
            className={`soltar${arrastando ? " soltar--ativo" : ""}`}
            role="button"
            tabIndex={0}
            aria-describedby="formatos"
            onClick={() => entrada.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && entrada.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setArrastando(true);
            }}
            onDragLeave={() => setArrastando(false)}
            onDrop={(e) => {
              e.preventDefault();
              setArrastando(false);
              adicionar(e.dataTransfer.files);
            }}
          >
            <span className="soltar__icone">
              <Icone nome="nuvem" tamanho={30} />
            </span>
            <strong>Solte os arquivos aqui</strong>
            <p id="formatos">
              ou <span className="soltar__escolher">escolha no computador</span>. Aceita PDF, JPG, PNG, TIFF, HEIC e
              ZIP, até 50 MB por arquivo.
            </p>
          </div>
          <input
            ref={entrada}
            type="file"
            multiple
            accept={ACEITOS}
            hidden
            onChange={(e) => {
              adicionar(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        <div className="bloco formulario-envio">
          <h2 style={{ marginBottom: "0.75rem" }}>
            {arquivos.length ? `${arquivos.length} arquivo${arquivos.length > 1 ? "s" : ""} escolhido${arquivos.length > 1 ? "s" : ""}` : "Nenhum arquivo escolhido"}
          </h2>
          {arquivos.length > 0 && (
            <ul className="lista-arquivos">
              {arquivos.map((a, i) => (
                <li key={a.name + a.size}>
                  <span style={{ overflowWrap: "anywhere" }}>
                    <Icone nome="arquivo" tamanho={18} />
                    {a.name}
                  </span>
                  <span className="discreto" style={{ whiteSpace: "nowrap" }}>
                    {tamanho(a.size)}{" "}
                    <button
                      type="button"
                      className="botao botao--texto botao--pequeno"
                      onClick={() => setArquivos((l) => l.filter((_, j) => j !== i))}
                      aria-label={`Remover ${a.name}`}
                    >
                      Remover
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
          {!umSoDocumento && arquivos.length > 0 && (
            <div style={{ marginTop: "1rem" }}>
              <label htmlFor="nome-lote">Nome do lote</label>
              <input
                id="nome-lote"
                className="entrada"
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Ex.: Malote da regional de Picos, setembro"
                maxLength={200}
              />
              <p className="dica">Opcional. Sem nome, o lote recebe a data e a hora do envio.</p>
            </div>
          )}
          {arquivos.length > 0 && (
            <fieldset className="escolha-validacao">
              <legend>Depois da leitura</legend>
              <label className="escolha-validacao__opcao">
                <input
                  type="radio"
                  name="validacao"
                  checked={!jaConferidos}
                  onChange={() => setJaConferidos(false)}
                />
                <span>
                  <strong>Conferir na tela</strong>
                  <span className="dica">
                    Cada requerimento passa pela conferência, ao lado da folha, antes de ser validado.
                  </span>
                </span>
              </label>
              <label className="escolha-validacao__opcao">
                <input
                  type="radio"
                  name="validacao"
                  checked={jaConferidos}
                  onChange={() => setJaConferidos(true)}
                />
                <span>
                  <strong>Já estão conferidos: só armazenar</strong>
                  <span className="dica">
                    Os dados lidos são validados e armazenados direto, sem conferência. Pontos que a leitura apontar
                    ficam registrados no histórico de cada requerimento. Requerimentos lidos com confiança abaixo de
                    50% não são validados automaticamente: vão para “Conferência obrigatória”, na Revisão.
                  </span>
                </span>
              </label>
            </fieldset>
          )}
          {erro && (
            <div className="aviso aviso--erro" role="alert" style={{ marginTop: "1rem" }}>
              {erro}
            </div>
          )}
          {parcial && (
            <div className="aviso" role="status" style={{ marginTop: "1rem" }}>
              <p>
                Lote criado com {parcial.novos} {parcial.novos === 1 ? "arquivo novo" : "arquivos novos"}.{" "}
                <Link href={`/lotes/${parcial.uuid}`}>Acompanhar o lote</Link>
              </p>
              {parcial.duplicados.length > 0 && (
                <>
                  <p style={{ marginTop: "0.5rem" }}>
                    Já tinham sido enviados antes e não foram lidos de novo
                    {jaConferidos ? " (mantêm a situação que já tinham)" : ""}:
                  </p>
                  <ul>
                    {parcial.duplicados.map((d) => (
                      <li key={d.documento_uuid + d.arquivo}>
                        <Link href={`/documentos/${d.documento_uuid}`}>{d.arquivo}</Link>{" "}
                        <Status valor={d.status} />
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {parcial.formato_nao_suportado.length > 0 && (
                <p style={{ marginTop: "0.5rem" }}>
                  Formato não suportado, ignorados: {parcial.formato_nao_suportado.join(", ")}
                </p>
              )}
            </div>
          )}
          <div className="acoes" style={{ marginTop: "1.25rem" }}>
            <button className="botao" disabled={!arquivos.length || enviando} onClick={enviar}>
              {enviando
                ? "Enviando…"
                : umSoDocumento
                  ? jaConferidos
                    ? "Enviar e validar"
                    : "Enviar documento"
                  : jaConferidos
                    ? "Criar lote e validar"
                    : "Criar lote"}
            </button>
            {arquivos.length > 0 && !enviando && (
              <button className="botao botao--secundario" onClick={() => setArquivos([])}>
                Limpar
              </button>
            )}
          </div>
        </div>
      </div>

      <section className="secao" style={{ marginTop: "2.5rem" }}>
        <div className="cabecalho" style={{ marginBottom: "0.75rem" }}>
          <h2>Lotes recentes</h2>
          <Link href="/lotes">Ver todos os lotes</Link>
        </div>
        {lotes === null ? (
          <p className="discreto">Carregando…</p>
        ) : lotes.length === 0 ? (
          <div className="vazio">
            <strong>Nenhum lote ainda</strong>
            Os lotes enviados por aqui ou pela pasta do scanner aparecem nesta lista.
          </div>
        ) : (
          <div className="rolagem-x">
            <table className="tabela">
              <thead>
                <tr>
                  <th scope="col">Lote</th>
                  <th scope="col" className="opcional">Origem</th>
                  <th scope="col">Andamento</th>
                  <th scope="col">Situação</th>
                </tr>
              </thead>
              <tbody>
                {lotes.map((l) => (
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
                    <td>
                      <Status valor={l.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
