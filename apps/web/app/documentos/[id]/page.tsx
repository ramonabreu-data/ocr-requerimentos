"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ConfirmacaoValidado from "@/components/ConfirmacaoValidado";
import DetalhesFinalidade, { chaveDetalhe } from "@/components/DetalhesFinalidade";
import Status from "@/components/Status";
import TabelaDocumentos from "@/components/TabelaDocumentos";
import Visor, { chaveCampo } from "@/components/Visor";
import { api, type CorpoCorrecao } from "@/lib/api";
import { ASSINATURA, coord, data, dataHora, EM_ANDAMENTO, listaDeOrigem, METODO, nivelConfianca, pct } from "@/lib/formato";
import { usePolling } from "@/lib/usePolling";
import type { Campo, DocumentoDetalhe, Referencia, RegistroRevisao } from "@/lib/tipos";

type LinhaIrr = { sistema: string; area: string; cultura: string };

const CRUS = new Set(["latitude", "longitude", "data_documento"]); // mostra o texto lido, não o convertido

function exibido(c: Campo | undefined): string {
  if (!c) return "";
  if (c.corrigido_manual || CRUS.has(c.campo) || c.campo === "irrigacao_area") return c.valor_bruto ?? "";
  return (c.valido ? c.valor_normalizado : c.valor_bruto) ?? c.valor_bruto ?? "";
}

function estadoInicial(doc: DocumentoDetalhe) {
  const campos = doc.requerimento?.campos ?? [];
  const simples: Record<string, string> = {};
  for (const c of campos) if (c.indice == null) simples[c.campo] = exibido(c);
  const finalidades = campos
    .filter((c) => c.campo === "finalidade")
    .sort((a, b) => (a.indice ?? 0) - (b.indice ?? 0))
    .map(exibido);
  const ordens = [...new Set(campos.filter((c) => c.campo.startsWith("irrigacao_")).map((c) => c.indice ?? 0))].sort(
    (a, b) => a - b,
  );
  const acha = (campo: string, o: number) => campos.find((c) => c.campo === campo && c.indice === o);
  const irrigacao: LinhaIrr[] = ordens.map((o) => ({
    sistema: exibido(acha("irrigacao_sistema", o)),
    area: exibido(acha("irrigacao_area", o)),
    cultura: exibido(acha("irrigacao_cultura", o)),
  }));
  // detalhes das finalidades: campos "criacao_animal.cabecas" com índice = item
  const detalhes: Record<string, string> = {};
  const itens: Record<string, number[]> = {};
  for (const c of campos) {
    if (!c.campo.includes(".")) continue;
    detalhes[chaveDetalhe(c.campo, c.indice)] = exibido(c);
    if (c.indice != null) {
      const fin = c.campo.split(".")[0];
      itens[fin] = [...new Set([...(itens[fin] ?? []), c.indice])].sort((a, b) => a - b);
    }
  }
  return { simples, finalidades, irrigacao, detalhes, itens };
}

const LISTAS = [
  "municipios", "procedimentos", "intervencoes", "finalidades", "sistemas", "culturas",
  // listas dos detalhes das finalidades (mesmas opções do formulário que gera o PDF)
  "prestador", "especie_aquicultura", "estabelecimento", "especie_animal", "sistema_criacao", "unidade", "uso_outro", "combustivel",
] as const;

export default function Conferencia() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { dados: doc, setDados: setDoc, erro, recarregar } = usePolling(
    () => api.documento(id),
    (d) => EM_ANDAMENTO.has(d.status),
  );

  const [inicial, setInicial] = useState<ReturnType<typeof estadoInicial> | null>(null);
  const [simples, setSimples] = useState<Record<string, string>>({});
  const [finalidades, setFinalidades] = useState<string[]>([]);
  const [irrigacao, setIrrigacao] = useState<LinhaIrr[]>([]);
  const [detalhes, setDetalhes] = useState<Record<string, string>>({});
  const [itensDet, setItensDet] = useState<Record<string, number[]>>({});
  const [ativo, setAtivo] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [falha, setFalha] = useState<string | null>(null);
  const [feito, setFeito] = useState<string | null>(null);
  const [justificando, setJustificando] = useState(false);
  const [justificativa, setJustificativa] = useState("");
  const [validadoAgora, setValidadoAgora] = useState<{ href: string; rotulo: string; comJustificativa: boolean } | null>(null);
  const [historico, setHistorico] = useState<RegistroRevisao[]>([]);
  const [listas, setListas] = useState<Record<string, Referencia[]>>({});
  const entradas = useRef<Record<string, HTMLInputElement | HTMLTextAreaElement | null>>({});
  const versao = doc ? `${doc.uuid}:${doc.updated_at}:${doc.status}` : "";

  useEffect(() => {
    if (!doc?.requerimento) return;
    const e = estadoInicial(doc);
    setInicial(e);
    setSimples(e.simples);
    setFinalidades(e.finalidades);
    setIrrigacao(e.irrigacao);
    setDetalhes(e.detalhes);
    setItensDet(e.itens);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versao]);

  const carregarHistorico = useCallback(() => {
    api.revisoes(id).then(setHistorico).catch(() => undefined);
  }, [id]);

  useEffect(() => {
    carregarHistorico();
    Promise.all(LISTAS.map((t) => api.referencias(t).catch(() => [] as Referencia[]))).then((r) =>
      setListas(Object.fromEntries(LISTAS.map((t, i) => [t, r[i]]))),
    );
  }, [carregarHistorico]);

  const campos = useMemo(() => doc?.requerimento?.campos ?? [], [doc]);
  const porChave = useMemo(() => Object.fromEntries(campos.map((c) => [chaveCampo(c), c])), [campos]);

  const colunasDet = useMemo(
    () => Object.fromEntries((doc?.requerimento?.finalidades ?? []).filter((f) => f.chave && f.estrutura).map((f) => [f.chave!, f.estrutura!.colunas.map((c) => c.chave)])),
    [doc],
  );

  const alterados = useMemo(() => {
    if (!inicial) return { simples: {} as Record<string, string>, finalidades: false, irrigacao: false, detalhes: {} as Record<string, string> };
    const s: Record<string, string> = {};
    for (const [k, v] of Object.entries(simples)) if ((inicial.simples[k] ?? "") !== v) s[k] = v;
    const visivel = (k: string) => {
      const [nome, item] = k.split("#");
      return item == null || (itensDet[nome.split(".")[0]] ?? []).includes(Number(item));
    };
    const det: Record<string, string> = {};
    for (const [k, v] of Object.entries(detalhes)) if (visivel(k) && (inicial.detalhes[k] ?? "") !== v) det[k] = v;
    // item removido: todas as colunas vazias (a API apaga e renumera os seguintes)
    for (const [fin, ns] of Object.entries(inicial.itens))
      for (const n of ns)
        if (!(itensDet[fin] ?? []).includes(n)) for (const col of colunasDet[fin] ?? []) det[`${fin}.${col}#${n}`] = "";
    return {
      simples: s,
      finalidades: JSON.stringify(inicial.finalidades) !== JSON.stringify(finalidades),
      irrigacao: JSON.stringify(inicial.irrigacao) !== JSON.stringify(irrigacao),
      detalhes: det,
    };
  }, [inicial, simples, finalidades, irrigacao, detalhes, itensDet, colunasDet]);
  const sujo =
    Object.keys(alterados.simples).length > 0 || alterados.finalidades || alterados.irrigacao || Object.keys(alterados.detalhes).length > 0;

  const selecionarNaFolha = (k: string) => {
    setAtivo(k);
    const el = entradas.current[k];
    el?.focus({ preventScroll: false });
  };

  const salvar = async () => {
    if (!doc) return;
    setSalvando(true);
    setFalha(null);
    setFeito(null);
    const corpo: CorpoCorrecao = { versao: doc.requerimento?.versao };
    if (Object.keys(alterados.simples).length) corpo.campos = alterados.simples;
    if (alterados.finalidades) corpo.finalidades = finalidades.filter((f) => f.trim());
    if (alterados.irrigacao) corpo.irrigacao = irrigacao.filter((l) => l.sistema || l.area || l.cultura);
    if (Object.keys(alterados.detalhes).length) corpo.detalhes = alterados.detalhes;
    try {
      const novo = await api.corrigir(doc.uuid, corpo);
      setDoc(novo);
      setFeito(
        novo.requerimento?.pendencias.length
          ? "Correções salvas. Ainda há pendências listadas acima."
          : "Correções salvas. O documento está sem pendências e pode ser validado.",
      );
      carregarHistorico();
    } catch (e) {
      setFalha(e instanceof Error ? e.message : String(e));
    } finally {
      setSalvando(false);
    }
  };

  const validar = async (forcar = false) => {
    if (!doc) return;
    setSalvando(true);
    setFalha(null);
    try {
      const novo = await api.validar(doc.uuid, forcar, forcar ? justificativa : undefined, doc.requerimento?.versao);
      setDoc(novo);
      setJustificando(false);
      carregarHistorico();
      const lista = listaDeOrigem(new URLSearchParams(window.location.search).get("de"));
      setValidadoAgora({ ...lista, comJustificativa: forcar });
    } catch (e) {
      setFalha(e instanceof Error ? e.message : String(e));
    } finally {
      setSalvando(false);
    }
  };

  const reprocessar = async () => {
    if (!doc || !window.confirm("Ler o documento de novo? As correções manuais feitas na revisão serão reaplicadas sobre a nova leitura.")) return;
    try {
      await api.reprocessar(doc.uuid);
      setFeito(null);
      recarregar();
    } catch (e) {
      setFalha(e instanceof Error ? e.message : String(e));
    }
  };

  if (erro && !doc)
    return (
      <div className="pagina">
        <div className="aviso aviso--erro">{erro}</div>
      </div>
    );
  if (!doc) return <p className="carregando">Carregando documento…</p>;

  const cabecalho = (
    <div className="cabecalho">
      <div>
        {doc.lote_uuid && (
          <Link href={`/lotes/${doc.lote_uuid}`} className="discreto">
            Voltar ao lote
          </Link>
        )}
        <h1 style={{ overflowWrap: "anywhere" }}>{doc.nome_original}</h1>
        <p className="metadados">
          <Status valor={doc.status} />
          {[doc.metodo_extracao && (METODO[doc.metodo_extracao] ?? doc.metodo_extracao), doc.assinatura_tipo && (ASSINATURA[doc.assinatura_tipo] ?? doc.assinatura_tipo)]
            .filter(Boolean)
            .map((t) => (
              <span key={String(t)}>{t}</span>
            ))}
        </p>
      </div>
      <div className="acoes">
        <a className="botao botao--secundario" href={api.arquivoUrl(doc.uuid)} target="_blank" rel="noreferrer">
          Abrir original
        </a>
        {doc.requerimento &&
          (sujo ? (
            <button className="botao botao--secundario" disabled title="Salve as correções para incluí-las no JSON">
              Baixar JSON (salve antes)
            </button>
          ) : (
            <a className="botao botao--secundario" href={api.jsonUrl(doc.uuid, doc.requerimento.versao)} download>
              Baixar JSON
            </a>
          ))}
        {!EM_ANDAMENTO.has(doc.status) && doc.status !== "validado" && (
          <button className="botao botao--secundario" onClick={reprocessar}>
            Ler de novo
          </button>
        )}
      </div>
    </div>
  );

  if (EM_ANDAMENTO.has(doc.status))
    return (
      <div className="pagina">
        {cabecalho}
        <div className="bloco carregando" role="status">
          {doc.status === "recebido" ? "Na fila de leitura. Esta página atualiza sozinha." : "Lendo o documento. Leva alguns segundos por página."}
        </div>
      </div>
    );

  if (doc.status === "erro")
    return (
      <div className="pagina">
        {cabecalho}
        <div className="aviso aviso--erro" role="alert">
          <strong>Não foi possível ler este arquivo.</strong> {doc.erro}
          <p style={{ marginTop: "0.4rem" }}>Confira se o arquivo abre normalmente e use “Ler de novo”, ou envie uma digitalização melhor.</p>
        </div>
      </div>
    );

  if (doc.status === "dividido")
    return (
      <div className="pagina">
        {cabecalho}
        <div className="aviso" style={{ marginBottom: "1.25rem" }}>
          Este arquivo tinha {doc.filhos.length} requerimentos e foi separado em partes. Confira cada uma.
        </div>
        <TabelaDocumentos docs={doc.filhos} vazio="Nenhuma parte gerada." />
      </div>
    );

  const req = doc.requerimento!;
  const validado = doc.status === "validado";

  const entradaCampo = (nome: string, opcoes?: { lista?: string; mono?: boolean; area?: boolean; inteiro?: boolean; dica?: string }) => {
    const c = porChave[`${nome}:`];
    const k = `${nome}:`;
    const nivel = c?.corrigido_manual ? "ok" : nivelConfianca(c?.confianca, c?.valido ?? null);
    const id_ = `campo-${nome}`;
    const alterado = nome in alterados.simples;
    // leitura perfeita (texto do PDF) não precisa de medidor: só mostra quando há algo a ponderar
    const mostrarConf = !!c && !c.corrigido_manual && c.confianca != null && (c.confianca < 99.5 || c.valido === false);
    const classe = ["campo", k === ativo && "campo--ativo", !alterado && nivel !== "ok" && `campo--${nivel}`, alterado && "campo--alterado", opcoes?.inteiro && "inteiro"]
      .filter(Boolean)
      .join(" ");
    const props = {
      id: id_,
      value: simples[nome] ?? "",
      readOnly: validado,
      className: opcoes?.mono ? "mono" : undefined,
      onFocus: () => setAtivo(k),
      "aria-invalid": c?.valido === false || undefined,
      "aria-describedby": c?.mensagem ? `${id_}-msg` : undefined,
      ref: (el: HTMLInputElement | HTMLTextAreaElement | null) => {
        entradas.current[k] = el;
      },
    };
    return (
      <div className={classe}>
        <label htmlFor={id_}>
          <span>
            {c?.rotulo ?? nome} {c?.corrigido_manual && <span className="selo">corrigido</span>}
          </span>
          {mostrarConf && <span className="conf">{pct(c!.confianca)}</span>}
        </label>
        {opcoes?.area ? (
          <textarea {...props} rows={2} onChange={(e) => setSimples((s) => ({ ...s, [nome]: e.target.value }))} />
        ) : (
          <input {...props} list={opcoes?.lista} onChange={(e) => setSimples((s) => ({ ...s, [nome]: e.target.value }))} />
        )}
        {mostrarConf && (
          <div className={`medidor medidor--${nivel}`} aria-hidden>
            <span style={{ width: `${Math.max(c!.confianca ?? 0, 4)}%` }} />
          </div>
        )}
        {c?.mensagem && (
          <p id={`${id_}-msg`} className={`mensagem${c.valido === false ? " mensagem--erro" : nivel === "atencao" ? " mensagem--atencao" : ""}`}>
            {c.mensagem}
          </p>
        )}
        {opcoes?.dica && <p className="dica">{opcoes.dica}</p>}
      </div>
    );
  };

  const campoLista = (campo: string, indice: number) => porChave[`${campo}:${indice}`];

  const rotuloHistorico = (campo: string) => {
    const [nome, item] = campo.split("#");
    const c = porChave[`${nome}:${item ?? ""}`] ?? campos.find((x) => x.campo === nome);
    const extra = { finalidades: "Finalidades", irrigacao: "Tabela de irrigação" } as Record<string, string>;
    return `${c?.rotulo ?? extra[campo] ?? campo}${item ? `, item ${item}` : ""}`;
  };

  return (
    <div className="pagina pagina--larga">
      {cabecalho}
      {LISTAS.map((t) => (
        <datalist id={`lista-${t}`} key={t}>
          {(listas[t] ?? []).map((r) => (
            <option key={`${r.id}-${r.nome}`} value={r.nome} />
          ))}
        </datalist>
      ))}

      <div className="conferencia">
        <Visor uuid={doc.uuid} paginas={doc.paginas_lidas} campos={campos} ativo={ativo} onSelecionar={selecionarNaFolha} />

        <div className="formulario">
          {validado ? (
            <div className="aviso aviso--ok" role="status">
              Validado em {dataHora(req.validado_em)}. Para alterar algum campo, corrija e salve: o documento volta para conferência.
            </div>
          ) : req.pendencias.length ? (
            <div className="aviso" role="status">
              <strong>
                {req.pendencias.length === 1 ? "1 ponto para conferir" : `${req.pendencias.length} pontos para conferir`}
              </strong>
              <ul>
                {req.pendencias.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="aviso aviso--ok" role="status">
              Nenhuma pendência. Confira os campos com a folha ao lado e valide.
            </div>
          )}
          {req.avisos.length > 0 && (
            <p className="dica">Observações da leitura: {req.avisos.join("; ")}.</p>
          )}

          <section className="grupo" aria-labelledby="g-ident">
            <h2 id="g-ident">Requerente</h2>
            <div className="grade">
              {entradaCampo("requerente_nome", { inteiro: true })}
              {entradaCampo("cpf_cnpj", { mono: true })}
              <div className="campo">
                <span className="dica" style={{ display: "block", marginTop: "1.6rem" }}>
                  {req.pessoa_id ? `Cadastrado no SIGA (pessoa nº ${req.pessoa_id})` : "Não encontrado no cadastro de pessoas"}
                </span>
              </div>
            </div>
          </section>

          <section className="grupo" aria-labelledby="g-pedido">
            <h2 id="g-pedido">Pedido e localização</h2>
            <div className="grade">
              {entradaCampo("procedimento", { lista: "lista-procedimentos", inteiro: true })}
              {entradaCampo("tipo_intervencao", { lista: "lista-intervencoes" })}
              {entradaCampo("municipio", { lista: "lista-municipios" })}
              {entradaCampo("localidade", { inteiro: true })}
              {entradaCampo("latitude", { mono: true, dica: `Em decimal: ${coord(req.latitude)}` })}
              {entradaCampo("longitude", { mono: true, dica: `Em decimal: ${coord(req.longitude)}` })}
              {entradaCampo("descricao_usos", { area: true, inteiro: true })}
            </div>
          </section>

          <section className="grupo" aria-labelledby="g-final">
            <h2 id="g-final">Finalidades do uso da água</h2>
            <div className="lista-finalidades">
              {finalidades.map((f, i) => {
                const c = campoLista("finalidade", i);
                const k = `finalidade:${i}`;
                const nivel = c?.corrigido_manual ? "ok" : nivelConfianca(c?.confianca, c?.valido ?? null);
                return (
                  <div className="linha-acao" key={i}>
                    <div className={`campo${k === ativo ? " campo--ativo" : ""}${nivel !== "ok" ? ` campo--${nivel}` : ""}`}>
                      <input
                        aria-label={`Finalidade ${i + 1}`}
                        list="lista-finalidades"
                        value={f}
                        readOnly={validado}
                        ref={(el) => {
                          entradas.current[k] = el;
                        }}
                        onFocus={() => setAtivo(k)}
                        onChange={(e) => setFinalidades((l) => l.map((v, j) => (j === i ? e.target.value : v)))}
                      />
                      {c?.mensagem && <p className={`mensagem${c.valido === false ? " mensagem--erro" : ""}`}>{c.mensagem}</p>}
                    </div>
                    {!validado && (
                      <button className="botao botao--texto" onClick={() => setFinalidades((l) => l.filter((_, j) => j !== i))} aria-label={`Remover finalidade ${i + 1}`}>
                        Remover
                      </button>
                    )}
                  </div>
                );
              })}
              {!validado && (
                <div>
                  <button className="botao botao--secundario botao--pequeno" onClick={() => setFinalidades((l) => [...l, ""])}>
                    Adicionar finalidade
                  </button>
                </div>
              )}
            </div>
          </section>

          {req.finalidades
            .filter((f) => f.estrutura && f.chave && f.chave !== "irrigacao")
            .map((f) => {
              const fin = f.chave!;
              const todos = [...(inicial?.itens[fin] ?? []), ...(itensDet[fin] ?? [])];
              return (
                <DetalhesFinalidade
                  key={fin}
                  fin={f}
                  porChave={porChave}
                  valores={detalhes}
                  itens={itensDet[fin] ?? []}
                  validado={validado}
                  ativo={ativo}
                  entradas={entradas}
                  onAtivar={setAtivo}
                  onMudar={(k, v) => setDetalhes((d) => ({ ...d, [k]: v }))}
                  onAdicionarItem={() => setItensDet((m) => ({ ...m, [fin]: [...(m[fin] ?? []), Math.max(0, ...todos) + 1] }))}
                  onRemoverItem={(n) => setItensDet((m) => ({ ...m, [fin]: (m[fin] ?? []).filter((x) => x !== n) }))}
                />
              );
            })}

          {(irrigacao.length > 0 || finalidades.some((f) => f.toLowerCase().includes("irriga"))) && (
            <section className="grupo" aria-labelledby="g-irr">
              <h2 id="g-irr">Irrigação</h2>
              <div className="rolagem-x">
                <table className="irrigacao">
                  <colgroup>
                    <col className="col-sistema" />
                    <col className="col-area" />
                    <col />
                    <col className="col-remover" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">Sistema de irrigação</th>
                      <th scope="col">Área (ha)</th>
                      <th scope="col">Cultura</th>
                      <th scope="col">
                        <span className="pular">Ações</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {irrigacao.map((linha, i) => {
                      const ordem = i + 1;
                      const celula = (sub: keyof LinhaIrr, lista?: string) => {
                        const c = campoLista(`irrigacao_${sub}`, ordem);
                        const k = `irrigacao_${sub}:${ordem}`;
                        const nivel = c?.corrigido_manual ? "ok" : nivelConfianca(c?.confianca, c?.valido ?? null);
                        return (
                          <div className={`campo${k === ativo ? " campo--ativo" : ""}${nivel !== "ok" ? ` campo--${nivel}` : ""}`}>
                            <input
                              aria-label={`${sub === "area" ? "Área irrigada" : sub === "sistema" ? "Sistema de irrigação" : "Cultura"}, linha ${ordem}`}
                              list={lista}
                              className={sub === "area" ? "mono" : undefined}
                              inputMode={sub === "area" ? "decimal" : undefined}
                              value={linha[sub]}
                              readOnly={validado}
                              title={c?.mensagem ?? undefined}
                              ref={(el) => {
                                entradas.current[k] = el;
                              }}
                              onFocus={() => setAtivo(k)}
                              onChange={(e) =>
                                setIrrigacao((l) => l.map((v, j) => (j === i ? { ...v, [sub]: e.target.value } : v)))
                              }
                            />
                            {c?.valido === false && <p className="mensagem mensagem--erro">{c.mensagem}</p>}
                          </div>
                        );
                      };
                      return (
                        <tr key={i}>
                          <td data-rotulo="Sistema de irrigação">{celula("sistema", "lista-sistemas")}</td>
                          <td className="area" data-rotulo="Área (ha)">{celula("area")}</td>
                          <td data-rotulo="Cultura">{celula("cultura", "lista-culturas")}</td>
                          <td className="remover">
                            {!validado && (
                              <button className="botao botao--texto botao--pequeno" onClick={() => setIrrigacao((l) => l.filter((_, j) => j !== i))} aria-label={`Remover linha ${ordem}`}>
                                Remover
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {!validado && (
                <button
                  className="botao botao--secundario botao--pequeno"
                  style={{ marginTop: "0.6rem" }}
                  onClick={() => setIrrigacao((l) => [...l, { sistema: "", area: "", cultura: "" }])}
                >
                  Adicionar linha
                </button>
              )}
              {req.irrigacao.length > 0 && (
                <p className="dica">
                  Área total:{" "}
                  <span className="mono">
                    {req.irrigacao.reduce((s, i) => s + (i.area_ha ?? 0), 0).toLocaleString("pt-BR")} ha
                  </span>
                </p>
              )}
            </section>
          )}

          <section className="grupo" aria-labelledby="g-ass">
            <h2 id="g-ass">Assinatura e data</h2>
            <div className="grade">
              {entradaCampo("assinante_nome")}
              {entradaCampo("data_documento", { mono: true, dica: req.data_documento ? `Lida como ${data(req.data_documento)}` : undefined })}
            </div>
            <dl className="ficha" style={{ marginTop: "1rem" }}>
              <dt>Assinatura</dt>
              <dd>{ASSINATURA[doc.assinatura_tipo ?? ""] ?? "—"}</dd>
              {doc.assinatura_tipo === "digital" &&
                Array.isArray((doc.assinatura_detalhes as { assinaturas?: unknown[] } | null)?.assinaturas) &&
                ((doc.assinatura_detalhes as { assinaturas: Record<string, unknown>[] }).assinaturas).map((a, i) => (
                  <dd key={i} style={{ gridColumn: "2" }} className="discreto">
                    {String(a.assinante ?? "")} {a.integra === false ? "(documento alterado depois da assinatura)" : a.integra ? "(íntegra)" : ""}
                  </dd>
                ))}
              {doc.processo_uuid && (
                <>
                  <dt>Processo (QR)</dt>
                  <dd className="mono">{doc.processo_id ? `nº ${doc.processo_id}` : "não encontrado no SIGA"}</dd>
                </>
              )}
              <dt>Confiança geral</dt>
              <dd>{pct(req.confianca_geral)}</dd>
            </dl>
          </section>

          {historico.length > 0 && (
            <section className="grupo" aria-labelledby="g-hist">
              <h2 id="g-hist">Histórico de correções</h2>
              <ul className="historico">
                {historico.map((h, i) => (
                  <li key={i}>
                    <span className="discreto">{dataHora(h.created_at)}</span>{" "}
                    {h.campo === "__validacao_com_pendencias__" ? (
                      <>
                        validado com pendências. Justificativa: <ins>{h.valor_novo}</ins>
                      </>
                    ) : (
                      <>
                        <strong>{rotuloHistorico(h.campo)}</strong>: <del>{h.valor_anterior || "vazio"}</del> para{" "}
                        <ins>{h.valor_novo || "vazio"}</ins>
                      </>
                    )}
                    {h.usuario_id && <span className="discreto">, usuário {h.usuario_id}</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {justificando && (
            <div className="grupo campo">
              <label htmlFor="justificativa">Por que validar mesmo com pendências?</label>
              <textarea
                id="justificativa"
                rows={3}
                value={justificativa}
                onChange={(e) => setJustificativa(e.target.value)}
                placeholder="Ex.: coordenada conferida em vistoria; o ponto fica na divisa entre municípios."
              />
              <p className="dica">A justificativa fica registrada no histórico do documento.</p>
            </div>
          )}

          <div className="barra-acoes">
            {falha && (
              <div className="aviso aviso--erro" role="alert" style={{ width: "100%" }}>
                {falha}
              </div>
            )}
            {feito && !falha && (
              <div className="aviso aviso--ok" role="status" style={{ width: "100%" }}>
                {feito}
              </div>
            )}
            <button className="botao" onClick={salvar} disabled={!sujo || salvando}>
              {salvando && sujo ? "Salvando…" : "Salvar correções"}
            </button>
            {sujo && (
              <button
                className="botao botao--texto"
                onClick={() => {
                  if (!inicial) return;
                  setSimples(inicial.simples);
                  setFinalidades(inicial.finalidades);
                  setIrrigacao(inicial.irrigacao);
                  setDetalhes(inicial.detalhes);
                  setItensDet(inicial.itens);
                }}
              >
                Desfazer alterações
              </button>
            )}
            <span className="espaco" />
            {!validado &&
              (justificando ? (
                <>
                  <button className="botao botao--texto" onClick={() => setJustificando(false)}>
                    Cancelar
                  </button>
                  <button className="botao" disabled={!justificativa.trim() || salvando} onClick={() => validar(true)}>
                    Validar com justificativa
                  </button>
                </>
              ) : (
                <button
                  className="botao"
                  disabled={sujo || salvando}
                  title={sujo ? "Salve as correções antes de validar" : undefined}
                  onClick={() => (req.pendencias.length ? setJustificando(true) : validar(false))}
                >
                  {req.pendencias.length ? "Validar mesmo assim" : "Validar"}
                </button>
              ))}
          </div>
          {sujo && !validado && <p className="dica">Salve as correções antes de validar.</p>}
        </div>
      </div>
      {validadoAgora && (
        <ConfirmacaoValidado
          nome={doc.nome_original}
          comJustificativa={validadoAgora.comJustificativa}
          rotuloLista={validadoAgora.rotulo}
          aoIrParaLista={() => router.push(validadoAgora.href)}
        />
      )}
    </div>
  );
}
