"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ConfirmacaoValidado from "@/components/ConfirmacaoValidado";
import DetalhesFinalidade, { chaveDetalhe } from "@/components/DetalhesFinalidade";
import Icone, { type NomeIcone } from "@/components/Icone";
import PainelJson from "@/components/PainelJson";
import Status from "@/components/Status";
import TabelaDocumentos from "@/components/TabelaDocumentos";
import Visor, { chaveCampo } from "@/components/Visor";
import { api, type CorpoCorrecao } from "@/lib/api";
import { ASSINATURA, coord, data, dataHora, EM_ANDAMENTO, listaDeOrigem, METODO, nivelConfianca, pct, ROTULO_STATUS } from "@/lib/formato";
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

type Aba = "conferencia" | "json";
const ABAS: { valor: Aba; rotulo: string; icone: NomeIcone }[] = [
  { valor: "conferencia", rotulo: "Conferência", icone: "revisao" },
  { valor: "json", rotulo: "JSON", icone: "codigo" },
];

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
  const [aba, setAba] = useState<Aba>("conferencia");
  const refAbas = useRef<Record<Aba, HTMLButtonElement | null>>({ conferencia: null, json: null });

  // a aba fica no endereço (?aba=json): recarregar ou compartilhar o link abre na mesma aba
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("aba") === "json") setAba("json");
  }, []);
  const trocarAba = (nova: Aba) => {
    setAba(nova);
    const url = new URL(window.location.href);
    if (nova === "json") url.searchParams.set("aba", "json");
    else url.searchParams.delete("aba");
    window.history.replaceState(window.history.state, "", url);
  };
  const [salvando, setSalvando] = useState(false);
  const [falha, setFalha] = useState<string | null>(null);
  const [feito, setFeito] = useState<string | null>(null);
  const [justificando, setJustificando] = useState(false);
  const [justificativa, setJustificativa] = useState("");
  const [desconsiderando, setDesconsiderando] = useState(false);
  const [motivo, setMotivo] = useState("");
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

  // correções não salvas: fechar, recarregar ou sair por endereço pede confirmação do navegador
  useEffect(() => {
    if (!sujo) return;
    const avisar = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [sujo]);

  const selecionarNaFolha = (k: string) => {
    setAtivo(k);
    const el = entradas.current[k];
    el?.focus({ preventScroll: false });
  };

  /** Grava as alterações da tela e devolve o documento salvo, com a versão nova do requerimento. */
  const gravarCorrecoes = async (atual: DocumentoDetalhe) => {
    const corpo: CorpoCorrecao = { versao: atual.requerimento?.versao };
    if (Object.keys(alterados.simples).length) corpo.campos = alterados.simples;
    if (alterados.finalidades) corpo.finalidades = finalidades.filter((f) => f.trim());
    if (alterados.irrigacao) corpo.irrigacao = irrigacao.filter((l) => l.sistema || l.area || l.cultura);
    if (Object.keys(alterados.detalhes).length) corpo.detalhes = alterados.detalhes;
    const novo = await api.corrigir(atual.uuid, corpo);
    setDoc(novo);
    carregarHistorico();
    return novo;
  };

  const salvar = async () => {
    if (!doc) return;
    setSalvando(true);
    setFalha(null);
    setFeito(null);
    try {
      const novo = await gravarCorrecoes(doc);
      setFeito(
        novo.requerimento?.pendencias.length
          ? "Correções salvas. Ainda há pendências listadas acima."
          : "Correções salvas. O documento está sem pendências e pode ser validado.",
      );
    } catch (e) {
      setFalha(e instanceof Error ? e.message : String(e));
    } finally {
      setSalvando(false);
    }
  };

  // com alterações na tela, grava antes e valida com a versão que a gravação devolveu (não a do estado,
  // que só atualiza no próximo render); se ainda restarem pendências sem justificativa, pede a justificativa
  const validar = async (forcar = false) => {
    if (!doc) return;
    setSalvando(true);
    setFalha(null);
    setFeito(null);
    try {
      const atual = sujo ? await gravarCorrecoes(doc) : doc;
      const comPendencias = !!atual.requerimento?.pendencias.length;
      if (comPendencias && !forcar) {
        setFeito("Correções salvas. Ainda há pendências: justifique para validar.");
        setJustificando(true);
        return;
      }
      // as correções podem ter resolvido as pendências: aí não há o que justificar
      const comJustificativa = forcar && comPendencias;
      const novo = await api.validar(atual.uuid, comJustificativa, comJustificativa ? justificativa : undefined, atual.requerimento?.versao);
      setDoc(novo);
      setJustificando(false);
      carregarHistorico();
      const lista = listaDeOrigem(new URLSearchParams(window.location.search).get("de"));
      setValidadoAgora({ ...lista, comJustificativa });
    } catch (e) {
      setFalha(e instanceof Error ? e.message : String(e));
    } finally {
      setSalvando(false);
    }
  };

  const descartar = () => {
    if (!inicial) return;
    setSimples(inicial.simples);
    setFinalidades(inicial.finalidades);
    setIrrigacao(inicial.irrigacao);
    setDetalhes(inicial.detalhes);
    setItensDet(inicial.itens);
  };

  // sai das filas sem validar e sem ir ao SIGA; as alterações não salvas da tela são descartadas
  const desconsiderar = async () => {
    if (!doc) return;
    setSalvando(true);
    setFalha(null);
    setFeito(null);
    try {
      const novo = await api.desconsiderar(doc.uuid, motivo.trim());
      descartar();
      setDoc(novo);
      setDesconsiderando(false);
      setJustificando(false);
      setMotivo("");
      carregarHistorico();
    } catch (e) {
      setFalha(e instanceof Error ? e.message : String(e));
    } finally {
      setSalvando(false);
    }
  };

  const reconsiderar = async () => {
    if (!doc) return;
    setSalvando(true);
    setFalha(null);
    try {
      await api.reconsiderar(doc.uuid);
      recarregar();
      carregarHistorico();
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
        {doc.numero && <p className="numero-registro">{doc.numero}</p>}
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
        {/* na aba JSON o download fica dentro dela, com o formato escolhido */}
        {doc.requerimento && aba !== "json" &&
          (sujo ? (
            <button className="botao botao--secundario" disabled title="Salve as correções para incluí-las no JSON">
              Baixar JSON (salve antes)
            </button>
          ) : (
            <a className="botao botao--secundario" href={api.jsonUrl(doc.uuid, doc.requerimento.versao)} download>
              Baixar JSON
            </a>
          ))}
        {!EM_ANDAMENTO.has(doc.status) && doc.status !== "validado" && doc.status !== "desconsiderado" && (
          <button className="botao botao--secundario" onClick={reprocessar}>
            Ler de novo
          </button>
        )}
      </div>
    </div>
  );

  const desconsiderado = doc.status === "desconsiderado";
  // o motivo é o da última desconsideração do histórico
  const ultimaDesconsideracao = historico
    .filter((h) => h.campo === "__desconsideracao__")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  const avisoFalha = falha && (
    <div className="aviso aviso--erro" role="alert" style={{ marginTop: "1rem" }}>
      {falha}
    </div>
  );

  // âmbar (sem role="status", que o deixaria azul de informação): o documento está fora do fluxo
  const avisoDesconsiderado = (
    <div className="aviso">
      <strong>Documento desconsiderado</strong> — não será validado nem enviado ao SIGA.
      {ultimaDesconsideracao?.valor_novo && (
        <p style={{ marginTop: "0.4rem" }}>
          Motivo: {ultimaDesconsideracao.valor_novo}
          <span className="discreto"> ({dataHora(ultimaDesconsideracao.created_at)})</span>
        </p>
      )}
      <div className="acoes" style={{ marginTop: "0.6rem" }}>
        <button className="botao botao--secundario botao--pequeno" onClick={reconsiderar} disabled={salvando}>
          {salvando ? "Reconsiderando…" : "Reconsiderar"}
        </button>
        <span className="dica" style={{ margin: 0 }}>O documento volta para a revisão.</span>
      </div>
    </div>
  );

  const painelDesconsiderar = desconsiderando && (
    <div className="grupo campo">
      <label htmlFor="motivo">Motivo</label>
      <textarea
        id="motivo"
        rows={3}
        autoFocus
        value={motivo}
        onChange={(e) => setMotivo(e.target.value)}
        placeholder="Ex.: não é requerimento de outorga (formulário de licenciamento); arquivo repetido; folha ilegível."
      />
      <p className="dica">
        O documento sai das filas de revisão e não será validado nem enviado ao SIGA.{" "}
        {sujo && "As alterações feitas na tela serão descartadas, sem gravar. "}
        O motivo fica no histórico, e dá para reconsiderar depois.
      </p>
      <div className="acoes" style={{ marginTop: "0.6rem" }}>
        <button className="botao botao--texto" onClick={() => setDesconsiderando(false)}>
          Cancelar
        </button>
        <button className="botao" disabled={!motivo.trim() || salvando} onClick={desconsiderar}>
          Desconsiderar
        </button>
      </div>
    </div>
  );

  if (EM_ANDAMENTO.has(doc.status))
    return (
      <div className="pagina">
        {cabecalho}
        <div className="bloco carregando" role="status">
          {doc.status === "recebido" ? "Na fila de leitura. Esta página atualiza sozinha." : "Lendo o documento. Leva alguns segundos por página."}
          {doc.validar_ao_ler &&
            " Foi enviado como já conferido: será validado assim que a leitura terminar, salvo se a confiança da leitura ficar baixa."}
        </div>
      </div>
    );

  if (doc.status === "erro")
    return (
      <div className="pagina">
        {cabecalho}
        <div className="aviso aviso--erro" role="alert">
          <strong>Não foi possível ler este arquivo.</strong> {doc.erro}
          {doc.validar_ao_ler && " Como foi enviado como já conferido, será validado quando for lido."}
          <p style={{ marginTop: "0.4rem" }}>
            Confira se o arquivo abre normalmente e use “Ler de novo”, ou envie uma digitalização melhor. Se o arquivo não é um
            requerimento (por exemplo, uma planilha que veio no ZIP), desconsidere-o.
          </p>
        </div>
        {desconsiderando ? (
          <div style={{ marginTop: "1rem" }}>{painelDesconsiderar}</div>
        ) : (
          <div className="acoes" style={{ marginTop: "1rem" }}>
            <button className="botao botao--secundario" onClick={() => setDesconsiderando(true)}>
              Desconsiderar documento
            </button>
          </div>
        )}
        {avisoFalha}
      </div>
    );

  // desconsiderado sem leitura (veio do erro): não há formulário para mostrar
  if (desconsiderado && !doc.requerimento)
    return (
      <div className="pagina">
        {cabecalho}
        {avisoDesconsiderado}
        {doc.erro && <p className="dica">Erro da leitura: {doc.erro}</p>}
        {avisoFalha}
      </div>
    );

  if (doc.status === "dividido")
    return (
      <div className="pagina">
        {cabecalho}
        <div className="aviso" style={{ marginBottom: "1.25rem" }}>
          Este arquivo tinha {doc.filhos.length} requerimentos e foi separado em partes.{" "}
          {doc.validar_ao_ler ? "Como foi enviado como já conferido, cada parte é validada ao fim da leitura." : "Confira cada uma."}
        </div>
        <TabelaDocumentos docs={doc.filhos} vazio="Nenhuma parte gerada." />
      </div>
    );

  const req = doc.requerimento!;
  const validado = doc.status === "validado";
  // validado ou desconsiderado: o formulário só mostra o que foi lido
  const somenteLeitura = validado || desconsiderado;

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
      readOnly: somenteLeitura,
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

      {/* abas: setas do teclado trocam de aba; a conferência fica montada (escondida) para não perder edições */}
      <div className="abas" role="tablist" aria-label="Visões do documento">
        {ABAS.map((a, i) => (
          <button
            key={a.valor}
            ref={(el) => {
              refAbas.current[a.valor] = el;
            }}
            id={`aba-${a.valor}`}
            type="button"
            role="tab"
            className="aba"
            aria-selected={aba === a.valor}
            aria-controls={`painel-${a.valor}`}
            tabIndex={aba === a.valor ? 0 : -1}
            onClick={() => trocarAba(a.valor)}
            onKeyDown={(e) => {
              if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
              const prox = ABAS[(i + (e.key === "ArrowRight" ? 1 : ABAS.length - 1)) % ABAS.length].valor;
              trocarAba(prox);
              refAbas.current[prox]?.focus();
            }}
          >
            <Icone nome={a.icone} tamanho={18} />
            {a.rotulo}
          </button>
        ))}
      </div>

      <div role="tabpanel" id="painel-json" aria-labelledby="aba-json" hidden={aba !== "json"}>
        {aba === "json" && <PainelJson uuid={doc.uuid} versao={req.versao} validado={validado} sujo={sujo} />}
      </div>

      <div role="tabpanel" id="painel-conferencia" aria-labelledby="aba-conferencia" hidden={aba !== "conferencia"}>
        <div className="conferencia">
          <Visor uuid={doc.uuid} paginas={doc.paginas_lidas} campos={campos} ativo={ativo} onSelecionar={selecionarNaFolha} />

          <div className="formulario">
            {desconsiderado && avisoDesconsiderado}
            {/* leitura abaixo do limiar de confiança: não é validada sozinha, nem se enviada como já conferida */}
            {doc.conferencia_obrigatoria && !somenteLeitura && (
              <div className="aviso aviso--erro">
                <strong>Conferência obrigatória</strong> — a leitura ficou com {pct(doc.confianca_geral ?? req.confianca_geral)}{" "}
                de confiança. Confira cada campo com a folha antes de validar.
              </div>
            )}
            {validado ? (
              <div className="aviso aviso--ok" role="status">
                {req.validacao_modo === "envio"
                  ? `Validado no envio, em ${dataHora(req.validado_em)}: foi enviado como já conferido e não passou pela conferência.`
                  : `Validado em ${dataHora(req.validado_em)}.`}{" "}
                Para alterar algum campo, corrija e salve: o documento volta para conferência.
              </div>
            ) : desconsiderado ? null : req.pendencias.length ? (
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
                          readOnly={somenteLeitura}
                          ref={(el) => {
                            entradas.current[k] = el;
                          }}
                          onFocus={() => setAtivo(k)}
                          onChange={(e) => setFinalidades((l) => l.map((v, j) => (j === i ? e.target.value : v)))}
                        />
                        {c?.mensagem && <p className={`mensagem${c.valido === false ? " mensagem--erro" : ""}`}>{c.mensagem}</p>}
                      </div>
                      {!somenteLeitura && (
                        <button className="botao botao--texto" onClick={() => setFinalidades((l) => l.filter((_, j) => j !== i))} aria-label={`Remover finalidade ${i + 1}`}>
                          Remover
                        </button>
                      )}
                    </div>
                  );
                })}
                {!somenteLeitura && (
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
                    validado={somenteLeitura}
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
                                readOnly={somenteLeitura}
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
                              {!somenteLeitura && (
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
                {!somenteLeitura && (
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
                      ) : h.campo === "__reprocessamento__" ? (
                        <>lido de novo; as correções manuais foram reaplicadas.</>
                      ) : h.campo === "__desconsideracao__" ? (
                        <>
                          desconsiderado. Motivo: <ins>{h.valor_novo}</ins>
                        </>
                      ) : h.campo === "__reconsideracao__" ? (
                        <>
                          reconsiderado:{" "}
                          {h.valor_novo === "erro"
                            ? "voltou para o erro de leitura."
                            : `voltou para a revisão (${(ROTULO_STATUS[h.valor_novo ?? ""] ?? h.valor_novo ?? "").toLowerCase()}).`}
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
                <p className="dica">
                  A justificativa fica registrada no histórico do documento.
                  {sujo && " As alterações da tela são salvas antes de validar."}
                </p>
              </div>
            )}
            {painelDesconsiderar}

            {desconsiderado ? (
              avisoFalha
            ) : (
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
                <button
                  className="botao botao--texto"
                  disabled={!sujo || salvando}
                  onClick={() => {
                    if (window.confirm("Descartar as alterações feitas na tela? Nada será gravado.")) descartar();
                  }}
                >
                  Descartar alterações
                </button>
                <span className="espaco" />
                {!validado && !desconsiderando && !justificando && (
                  <button
                    className="botao botao--secundario"
                    disabled={salvando}
                    onClick={() => setDesconsiderando(true)}
                  >
                    Desconsiderar documento
                  </button>
                )}
                {!validado &&
                  !desconsiderando &&
                  (justificando ? (
                    <>
                      <button className="botao botao--texto" onClick={() => setJustificando(false)}>
                        Cancelar
                      </button>
                      <button className="botao" disabled={!justificativa.trim() || salvando} onClick={() => validar(true)}>
                        {sujo ? "Salvar e validar com justificativa" : "Validar com justificativa"}
                      </button>
                    </>
                  ) : (
                    <button
                      className="botao"
                      disabled={salvando}
                      onClick={() => (sujo || !req.pendencias.length ? validar(false) : setJustificando(true))}
                    >
                      {sujo ? "Salvar e validar" : req.pendencias.length ? "Validar mesmo assim" : "Validar"}
                    </button>
                  ))}
              </div>
            )}
          </div>
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
