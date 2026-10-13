"use client";
import { useEffect, useState } from "react";
import ArvoreJson from "@/components/ArvoreJson";
import Icone from "@/components/Icone";
import { api, type FormatoJson } from "@/lib/api";

const FORMATOS: { valor: FormatoJson; rotulo: string; descricao: string }[] = [
  {
    valor: "siga",
    rotulo: "Padrão do SIGA",
    descricao:
      "O que é entregue ao SIGA: formulário consolidado, validação, rastreabilidade de cada campo e origem do arquivo.",
  },
  {
    valor: "completo",
    rotulo: "Completo",
    descricao:
      "O arquivo como está gravado no bucket: documento, leitura, cada campo com confiança e posição na folha, e o histórico.",
  },
];

type Estado = { carregando: boolean; erro: string | null; dados: unknown };

export default function PainelJson({
  uuid,
  versao,
  validado,
  sujo,
}: {
  uuid: string;
  /** requerimento.versao: muda a cada gravação, e o JSON é buscado de novo */
  versao: number;
  validado: boolean;
  sujo: boolean;
}) {
  const [formato, setFormato] = useState<FormatoJson>("siga");
  const [estado, setEstado] = useState<Estado>({ carregando: true, erro: null, dados: null });
  // remonta a árvore com outro nível de abertura (expandir/recolher tudo)
  const [abertura, setAbertura] = useState({ nivel: 2, vez: 0 });
  const [copiado, setCopiado] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    setEstado((e) => ({ ...e, carregando: true, erro: null }));
    api
      .json(uuid, formato)
      .then((dados) => vivo && setEstado({ carregando: false, erro: null, dados }))
      .catch((e) => vivo && setEstado({ carregando: false, erro: e instanceof Error ? e.message : String(e), dados: null }));
    return () => {
      vivo = false;
    };
  }, [uuid, formato, versao]);

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(estado.dados, null, 2));
      setCopiado("JSON copiado.");
    } catch {
      setCopiado("Não foi possível copiar: o navegador bloqueou o acesso à área de transferência.");
    }
    window.setTimeout(() => setCopiado(null), 3000);
  };

  const atual = FORMATOS.find((f) => f.valor === formato)!;
  const pronto = !estado.carregando && !estado.erro && estado.dados != null;

  return (
    <div className="painel-json">
      <div className="painel-json__topo">
        <div className="alternador" role="group" aria-label="Formato do JSON">
          {FORMATOS.map((f) => (
            <button
              key={f.valor}
              type="button"
              className="alternador__opcao"
              aria-pressed={formato === f.valor}
              onClick={() => setFormato(f.valor)}
            >
              {f.rotulo}
            </button>
          ))}
        </div>
        <div className="acoes">
          <button
            type="button"
            className="botao botao--secundario"
            onClick={copiar}
            disabled={!pronto}
          >
            Copiar
          </button>
          {sujo ? (
            <button className="botao" disabled title="Salve as correções para incluí-las no JSON">
              <Icone nome="baixar" tamanho={18} />
              Baixar JSON (salve antes)
            </button>
          ) : (
            <a className="botao" href={api.jsonUrlFormato(uuid, formato, versao)} download>
              <Icone nome="baixar" tamanho={18} />
              Baixar JSON
            </a>
          )}
        </div>
      </div>

      <p className="dica">{atual.descricao}</p>
      {formato === "siga" && !validado && (
        <div className="aviso" role="status">
          Prévia: este requerimento ainda não foi validado. O SIGA só recebe os requerimentos validados.
        </div>
      )}
      {sujo && (
        <div className="aviso" role="status">
          Há correções não salvas na conferência. O JSON mostra a última versão gravada (versão {versao}).
        </div>
      )}
      {copiado && (
        <p className="dica" role="status">
          {copiado}
        </p>
      )}

      <div className="bloco painel-json__conteudo">
        <div className="painel-json__barra">
          <span className="discreto">Versão {versao}</span>
          <span className="acoes">
            <button
              type="button"
              className="botao botao--texto botao--pequeno"
              disabled={!pronto}
              onClick={() => setAbertura((a) => ({ nivel: Infinity, vez: a.vez + 1 }))}
            >
              Expandir tudo
            </button>
            <button
              type="button"
              className="botao botao--texto botao--pequeno"
              disabled={!pronto}
              onClick={() => setAbertura((a) => ({ nivel: 1, vez: a.vez + 1 }))}
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
        ) : (
          <ArvoreJson
            key={`${formato}:${versao}:${abertura.vez}`}
            dados={estado.dados}
            abertoAte={abertura.nivel}
            rotulo={`JSON ${atual.rotulo.toLowerCase()}`}
          />
        )}
      </div>
    </div>
  );
}
