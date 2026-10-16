"use client";
import { useEffect, useMemo, useState } from "react";
import ArvoreJson from "@/components/ArvoreJson";
import Icone from "@/components/Icone";
import { api, type SituacaoConsolidado } from "@/lib/api";
import { dataHora } from "@/lib/formato";

const SITUACOES: { valor: SituacaoConsolidado; rotulo: string; descricao: string }[] = [
  {
    valor: "validados",
    rotulo: "Validados",
    descricao: "O requerimentos.json que o SIGA recebe: todos os requerimentos validados, do mais antigo ao mais novo.",
  },
  {
    valor: "todos",
    rotulo: "Todos os lidos",
    descricao:
      "Inclui os requerimentos lidos que ainda aguardam conferência (marcados como “não validado”). Serve para conferir; o SIGA só recebe os validados.",
  },
];

type Requerimento = {
  numero?: string | null;
  formulario?: {
    requerente?: { nome?: string | null; cpf_cnpj?: string | null } | null;
    localizacao?: { municipio?: { nome?: string | null } | null; localidade?: string | null } | null;
    procedimento?: { nome?: string | null } | null;
  } | null;
  origem?: { arquivo_nome?: string | null } | null;
};
type Consolidado = { gerado_em?: string; total?: number; requerimentos?: Requerimento[] } & Record<string, unknown>;
type Estado = { carregando: boolean; erro: string | null; dados: Consolidado | null };

const semAcento = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** O que a busca olha em cada requerimento: número, requerente, CPF/CNPJ, município, localidade, procedimento e arquivo. */
function textoDeBusca(r: Requerimento): string {
  const f = r.formulario;
  return semAcento(
    [
      r.numero,
      f?.requerente?.nome,
      f?.requerente?.cpf_cnpj,
      f?.localizacao?.municipio?.nome,
      f?.localizacao?.localidade,
      f?.procedimento?.nome,
      r.origem?.arquivo_nome,
    ]
      .filter(Boolean)
      .join(" "),
  );
}

export default function JsonRequerimentos() {
  const [situacao, setSituacao] = useState<SituacaoConsolidado>("validados");
  const [estado, setEstado] = useState<Estado>({ carregando: true, erro: null, dados: null });
  const [recarga, setRecarga] = useState(0);
  const [busca, setBusca] = useState("");
  // remonta a árvore com outro nível de abertura (recolher tudo)
  const [abertura, setAbertura] = useState({ nivel: 2, vez: 0 });
  const [copiado, setCopiado] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    setEstado((e) => ({ ...e, carregando: true, erro: null }));
    api
      .jsonConsolidado(situacao)
      .then((dados) => vivo && setEstado({ carregando: false, erro: null, dados: dados as Consolidado }))
      .catch((e) => vivo && setEstado({ carregando: false, erro: e instanceof Error ? e.message : String(e), dados: null }));
    return () => {
      vivo = false;
    };
  }, [situacao, recarga]);

  const todos = useMemo(() => estado.dados?.requerimentos ?? [], [estado.dados]);
  const indice = useMemo(() => todos.map(textoDeBusca), [todos]);
  // a busca só filtra o que a tela mostra; copiar e baixar levam o JSON completo
  const visivel = useMemo(() => {
    const termo = semAcento(busca.trim());
    if (!estado.dados || !termo) return estado.dados;
    const digitos = termo.replace(/\D/g, "");
    const porDigitos = digitos.length >= 3 && /^[\d\s./-]+$/.test(termo);
    const requerimentos = todos.filter(
      (_, i) => indice[i].includes(termo) || (porDigitos && indice[i].replace(/\D/g, "").includes(digitos)),
    );
    return { ...estado.dados, requerimentos, total: requerimentos.length };
  }, [estado.dados, todos, indice, busca]);

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(estado.dados, null, 2));
      setCopiado("JSON copiado.");
    } catch {
      setCopiado("Não foi possível copiar: o navegador bloqueou o acesso à área de transferência.");
    }
    window.setTimeout(() => setCopiado(null), 3000);
  };

  const atual = SITUACOES.find((s) => s.valor === situacao)!;
  const pronto = !estado.carregando && !estado.erro && estado.dados != null;
  const filtrando = pronto && busca.trim() !== "";
  const mostrados = visivel?.requerimentos?.length ?? 0;

  return (
    <div className="pagina">
      <div className="cabecalho">
        <div>
          <h1>JSON dos requerimentos</h1>
          <p>
            Todos os requerimentos num só JSON, no padrão do SIGA, gerado agora a partir do que está gravado. Abra cada
            requerimento para ver o formulário, a validação e a origem de cada campo.
          </p>
        </div>
      </div>

      <div className="painel-json">
        <div className="painel-json__topo">
          <div className="alternador" role="group" aria-label="Requerimentos incluídos">
            {SITUACOES.map((s) => (
              <button
                key={s.valor}
                type="button"
                className="alternador__opcao"
                aria-pressed={situacao === s.valor}
                onClick={() => setSituacao(s.valor)}
              >
                {s.rotulo}
              </button>
            ))}
          </div>
          <div className="acoes">
            <button type="button" className="botao botao--secundario" onClick={() => setRecarga((n) => n + 1)} disabled={estado.carregando}>
              Atualizar
            </button>
            <button type="button" className="botao botao--secundario" onClick={copiar} disabled={!pronto}>
              Copiar
            </button>
            <a className="botao" href={api.jsonConsolidadoUrl(situacao)} download>
              <Icone nome="baixar" tamanho={18} />
              Baixar JSON
            </a>
          </div>
        </div>

        <p className="dica">{atual.descricao}</p>

        <div className="filtros">
          <label className="pular" htmlFor="busca-json">
            Buscar
          </label>
          <input
            id="busca-json"
            className="entrada"
            type="search"
            placeholder="Buscar por número, requerente, CPF/CNPJ, município, localidade ou arquivo"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
        </div>
        {copiado && (
          <p className="dica" role="status">
            {copiado}
          </p>
        )}

        <div className="bloco painel-json__conteudo">
          <div className="painel-json__barra">
            <span className="discreto" role="status">
              {!pronto
                ? ""
                : filtrando
                  ? `${mostrados} de ${todos.length} requerimento${todos.length === 1 ? "" : "s"} (a busca só filtra a tela; copiar e baixar levam todos)`
                  : `${todos.length} requerimento${todos.length === 1 ? "" : "s"}${estado.dados?.gerado_em ? ` · gerado em ${dataHora(estado.dados.gerado_em)}` : ""}`}
            </span>
            <span className="acoes">
              <button
                type="button"
                className="botao botao--texto botao--pequeno"
                disabled={!pronto}
                onClick={() => setAbertura((a) => ({ nivel: 2, vez: a.vez + 1 }))}
              >
                Recolher tudo
              </button>
            </span>
          </div>
          {estado.erro ? (
            <div className="aviso aviso--erro" role="alert">
              {estado.erro}
            </div>
          ) : !pronto ? (
            <p className="carregando">Carregando JSON…</p>
          ) : todos.length === 0 ? (
            <div className="vazio">
              <strong>{situacao === "validados" ? "Nenhum requerimento validado ainda" : "Nenhum requerimento lido ainda"}</strong>
              {situacao === "validados"
                ? " Os requerimentos aparecem aqui assim que forem validados na conferência."
                : " Envie arquivos na tela Enviar; os requerimentos aparecem aqui assim que a leitura terminar."}
            </div>
          ) : filtrando && mostrados === 0 ? (
            <div className="vazio">
              <strong>Nada encontrado para “{busca}”</strong> Confira a grafia ou busque pelo CPF/CNPJ.
            </div>
          ) : (
            <ArvoreJson
              key={`${situacao}:${recarga}:${abertura.vez}:${busca}`}
              dados={visivel}
              abertoAte={abertura.nivel}
              rotulo={`JSON dos requerimentos ${atual.rotulo.toLowerCase()}`}
            />
          )}
        </div>
      </div>
    </div>
  );
}
