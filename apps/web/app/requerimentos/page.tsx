"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Icone from "@/components/Icone";
import Status from "@/components/Status";
import { api } from "@/lib/api";
import { data, dataHora, pct } from "@/lib/formato";
import type { DocumentoResumo, OpcoesFiltro } from "@/lib/tipos";

const TAMANHOS = [10, 20, 50, 100] as const;

const FILTROS = [
  { valor: "extraido,revisao,validado", rotulo: "Todos" },
  { valor: "validado", rotulo: "Validados" },
  { valor: "extraido,revisao", rotulo: "Aguardando conferência" },
] as const;

/** Estado da lista; os nomes são os mesmos dos parâmetros da API e do endereço da página. */
type Filtros = {
  status: string;
  busca: string;
  requerente: string;
  procedimento: string;
  municipio: string;
  campo_data: "documento" | "gravacao";
  data_de: string;
  data_ate: string;
  pagina: number;
  tamanho: number;
};

const PADRAO: Filtros = {
  status: FILTROS[0].valor,
  busca: "",
  requerente: "",
  procedimento: "",
  municipio: "",
  campo_data: "documento",
  data_de: "",
  data_ate: "",
  pagina: 1,
  tamanho: 20,
};

/** Só o que difere do padrão, para o endereço ficar curto. */
function paraQuery(f: Filtros): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(f) as [keyof Filtros, string | number][]) {
    const valor = String(v).trim();
    if (valor && valor !== String(PADRAO[k])) p.set(k, valor);
  }
  if (!f.data_de && !f.data_ate) p.delete("campo_data");
  return p.toString();
}

function daQuery(qs: string): Filtros {
  const p = new URLSearchParams(qs);
  const f = { ...PADRAO };
  for (const k of Object.keys(PADRAO) as (keyof Filtros)[]) {
    const v = p.get(k);
    if (v == null) continue;
    if (k === "pagina") f.pagina = Math.max(Number.parseInt(v, 10) || 1, 1);
    else if (k === "tamanho") f.tamanho = (TAMANHOS as readonly number[]).includes(Number(v)) ? Number(v) : PADRAO.tamanho;
    else if (k === "campo_data") f.campo_data = v === "gravacao" ? "gravacao" : "documento";
    else (f as Record<string, unknown>)[k] = v;
  }
  return f;
}

/** Quantos filtros do painel estão ativos (o período conta como um). */
function filtrosDoPainel(f: Filtros): number {
  return [f.requerente.trim(), f.procedimento, f.municipio, f.data_de || f.data_ate].filter(Boolean).length;
}

/** Garante que o valor vindo do endereço aparece no select mesmo sem requerimentos com ele. */
function opcoesCom(lista: { nome: string; total: number }[], atual: string) {
  return atual && !lista.some((o) => o.nome === atual) ? [...lista, { nome: atual, total: 0 }] : lista;
}

export default function Requerimentos() {
  const [f, setF] = useState<Filtros>(PADRAO);
  const [pronto, setPronto] = useState(false);
  const [opcoes, setOpcoes] = useState<OpcoesFiltro>({ procedimentos: [], municipios: [] });
  // `inicio`: posição do primeiro item da resposta (a faixa exibida segue o que chegou, não o que foi pedido)
  const [resultado, setResultado] = useState<{ total: number; itens: DocumentoResumo[]; inicio: number } | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [painelAberto, setPainelAberto] = useState(false);

  // filtros vêm do endereço: voltar de um documento ou abrir um link mantém a lista como estava
  useEffect(() => {
    const inicial = daQuery(window.location.search);
    setF(inicial);
    setPainelAberto(filtrosDoPainel(inicial) > 0); // filtros já aplicados: o painel abre mostrando-os
    setPronto(true);
    api.filtros().then(setOpcoes).catch(() => undefined);
  }, []);

  const qs = paraQuery(f);

  useEffect(() => {
    if (!pronto) return;
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
    const t = setTimeout(() => {
      const params: Record<string, string> = {};
      for (const [k, v] of Object.entries(f)) if (String(v).trim()) params[k] = String(v).trim();
      if (!f.data_de && !f.data_ate) delete params.campo_data;
      api
        .documentos(params)
        .then((r) => {
          setResultado({ ...r, inicio: (f.pagina - 1) * f.tamanho + 1 });
          setErro(null);
        })
        .catch((e) => setErro(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [f, qs, pronto]);

  /** Muda filtros e volta para a primeira página. */
  const mudar = (parcial: Partial<Filtros>) => setF((atual) => ({ ...atual, pagina: 1, ...parcial }));
  const ativos = filtrosDoPainel(f);
  const filtrando =
    !!(f.busca.trim() || f.requerente.trim() || f.procedimento || f.municipio || f.data_de || f.data_ate);
  const limpar = () => mudar({ busca: "", requerente: "", procedimento: "", municipio: "", campo_data: "documento", data_de: "", data_ate: "" });
  const origem = encodeURIComponent(`/requerimentos${qs ? `?${qs}` : ""}`);

  const paginas = resultado ? Math.max(Math.ceil(resultado.total / f.tamanho), 1) : 1;

  return (
    <div className="pagina">
      <div className="cabecalho">
        <div>
          <h1>Requerimentos</h1>
          <p>Todos os requerimentos já lidos e gravados no banco, validados ou ainda aguardando conferência.</p>
        </div>
      </div>
      <div className="filtros">
        <div className="acoes" role="group" aria-label="Situação">
          {FILTROS.map((o) => (
            <button
              key={o.valor}
              className={`botao${f.status === o.valor ? "" : " botao--secundario"}`}
              aria-pressed={f.status === o.valor}
              onClick={() => mudar({ status: o.valor })}
            >
              {o.rotulo}
            </button>
          ))}
        </div>
        <label className="pular" htmlFor="busca">
          Buscar
        </label>
        <input
          id="busca"
          className="entrada"
          type="search"
          placeholder="Buscar por nome, CPF/CNPJ, município ou arquivo"
          value={f.busca}
          onChange={(e) => mudar({ busca: e.target.value })}
        />
        <button
          type="button"
          className={`botao botao--secundario alternar-filtros${painelAberto ? " alternar-filtros--aberto" : ""}`}
          aria-expanded={painelAberto}
          aria-controls="painel-filtros"
          onClick={() => setPainelAberto((a) => !a)}
        >
          <Icone nome="filtro" tamanho={18} />
          Filtros
          {!painelAberto && ativos > 0 && (
            <span className="alternar-filtros__contagem">
              {ativos}
              <span className="pular"> {ativos === 1 ? "ativo" : "ativos"}</span>
            </span>
          )}
          <Icone nome="seta" tamanho={16} className="alternar-filtros__seta" />
        </button>
      </div>

      <div id="painel-filtros" className="painel-filtros" role="group" aria-label="Filtros" hidden={!painelAberto}>
        <div className="campo">
          <label htmlFor="f-requerente">Requerente</label>
          <input
            id="f-requerente"
            type="text"
            placeholder="Nome ou parte dele"
            value={f.requerente}
            onChange={(e) => mudar({ requerente: e.target.value })}
          />
        </div>
        <div className="campo">
          <label htmlFor="f-procedimento">Procedimento</label>
          <select id="f-procedimento" value={f.procedimento} onChange={(e) => mudar({ procedimento: e.target.value })}>
            <option value="">Todos</option>
            {opcoesCom(opcoes.procedimentos, f.procedimento).map((o) => (
              <option key={o.nome} value={o.nome}>
                {o.nome} ({o.total})
              </option>
            ))}
          </select>
        </div>
        <div className="campo">
          <label htmlFor="f-municipio">Município</label>
          <select id="f-municipio" value={f.municipio} onChange={(e) => mudar({ municipio: e.target.value })}>
            <option value="">Todos</option>
            {opcoesCom(opcoes.municipios, f.municipio).map((o) => (
              <option key={o.nome} value={o.nome}>
                {o.nome} ({o.total})
              </option>
            ))}
          </select>
        </div>
        <fieldset className="painel-filtros__periodo">
          <legend>Período</legend>
        <div className="campo">
          <label htmlFor="f-campo-data">Pela</label>
          <select
            id="f-campo-data"
            value={f.campo_data}
            onChange={(e) => mudar({ campo_data: e.target.value === "gravacao" ? "gravacao" : "documento" })}
          >
            <option value="documento">Data do documento</option>
            <option value="gravacao">Data de gravação</option>
          </select>
        </div>
        <div className="campo">
          <label htmlFor="f-de">De</label>
          <input id="f-de" type="date" value={f.data_de} max={f.data_ate || undefined} onChange={(e) => mudar({ data_de: e.target.value })} />
        </div>
        <div className="campo">
          <label htmlFor="f-ate">Até</label>
          <input id="f-ate" type="date" value={f.data_ate} min={f.data_de || undefined} onChange={(e) => mudar({ data_ate: e.target.value })} />
        </div>
        </fieldset>
        {filtrando && (
          <button className="botao botao--texto painel-filtros__limpar" onClick={limpar}>
            Limpar filtros
          </button>
        )}
      </div>

      {erro && <div className="aviso aviso--erro">{erro}</div>}
      {resultado === null ? (
        <p className="carregando">Carregando…</p>
      ) : resultado.itens.length === 0 ? (
        <div className="vazio">
          {filtrando ? (
            <>
              <strong>Nenhum requerimento com esses filtros</strong>
              Afrouxe algum filtro ou{" "}
              <button className="botao botao--texto" onClick={limpar}>
                limpe todos
              </button>
              .
            </>
          ) : (
            <>
              <strong>Nenhum requerimento gravado ainda</strong>
              Os requerimentos aparecem aqui assim que a leitura termina.
            </>
          )}
        </div>
      ) : (
        <>
          <p className="discreto">
            {resultado.total > resultado.itens.length
              ? `${resultado.inicio}–${resultado.inicio + resultado.itens.length - 1} de ${resultado.total} requerimentos`
              : `${resultado.total} ${resultado.total === 1 ? "requerimento" : "requerimentos"}`}
          </p>
          <div className="rolagem-x">
            <table className="tabela">
              <thead>
                <tr>
                  <th scope="col">Requerente</th>
                  <th scope="col" className="opcional">Procedimento</th>
                  <th scope="col" className="opcional">Município</th>
                  <th scope="col" className="opcional">Data do documento</th>
                  <th scope="col">Situação</th>
                  <th scope="col" className="num opcional">Confiança</th>
                  <th scope="col" className="opcional">Gravado em</th>
                </tr>
              </thead>
              <tbody>
                {resultado.itens.map((d) => (
                  <tr key={d.uuid}>
                    <td>
                      <Link className="principal" href={`/documentos/${d.uuid}?de=${origem}`}>
                        {d.requerente_nome ?? d.nome_original}
                      </Link>
                      {d.cpf_cnpj && (
                        <div className="mono discreto" style={{ fontSize: "0.85rem" }}>
                          {d.cpf_cnpj}
                        </div>
                      )}
                    </td>
                    <td className="opcional">{d.procedimento ?? "—"}</td>
                    <td className="opcional">{d.municipio ?? "—"}</td>
                    <td className="opcional">{data(d.data_documento)}</td>
                    <td>
                      <Status valor={d.status} />
                      {d.validado_em && (
                        <div className="discreto" style={{ fontSize: "0.85rem" }}>
                          {dataHora(d.validado_em)}
                        </div>
                      )}
                    </td>
                    <td className="num opcional">{pct(d.confianca_geral)}</td>
                    <td className="opcional data">{dataHora(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="paginacao">
            <div className="paginacao__tamanho">
              <label htmlFor="f-tamanho">Por página</label>
              <select
                id="f-tamanho"
                className="entrada"
                value={f.tamanho}
                onChange={(e) => mudar({ tamanho: Number(e.target.value) })}
              >
                {TAMANHOS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>
            {paginas > 1 && (
            <div className="acoes">
              <button
                className="botao botao--secundario"
                disabled={f.pagina <= 1}
                onClick={() => setF((a) => ({ ...a, pagina: a.pagina - 1 }))}
              >
                Anteriores
              </button>
              <span className="discreto">
                Página {f.pagina} de {paginas}
              </span>
              <button
                className="botao botao--secundario"
                disabled={f.pagina >= paginas}
                onClick={() => setF((a) => ({ ...a, pagina: a.pagina + 1 }))}
              >
                Próximos
              </button>
            </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
