"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import Icone, { type NomeIcone } from "@/components/Icone";
import { api } from "@/lib/api";

const LINKS: { href: string; rotulo: string; icone: NomeIcone }[] = [
  { href: "/", rotulo: "Enviar", icone: "enviar" },
  { href: "/lotes", rotulo: "Lotes", icone: "lotes" },
  { href: "/revisao", rotulo: "Revisão", icone: "revisao" },
  { href: "/requerimentos", rotulo: "Requerimentos", icone: "requerimentos" },
  { href: "/json", rotulo: "JSON", icone: "codigo" },
];

/** Trilha "Início › Seção › Item" a partir da rota. */
function trilha(caminho: string): { rotulo: string; href?: string }[] {
  const [secao, item] = caminho.split("/").filter(Boolean);
  if (!secao) return [{ rotulo: "Enviar requerimentos" }];
  if (secao === "documentos") return [{ rotulo: "Requerimentos", href: "/requerimentos" }, { rotulo: "Conferência do documento" }];
  const link = LINKS.find((l) => l.href === `/${secao}`);
  if (!link) return [];
  return item ? [{ rotulo: link.rotulo, href: link.href }, { rotulo: "Lote" }] : [{ rotulo: link.rotulo }];
}

export default function Navegacao({ logo }: { logo: string | null }) {
  const caminho = usePathname();
  const [emRevisao, setEmRevisao] = useState<number | null>(null);
  const [obrigatorias, setObrigatorias] = useState(0);

  useEffect(() => {
    let ativo = true;
    const buscar = () =>
      api
        .estatisticas()
        .then((e) => {
          if (!ativo) return;
          setEmRevisao(e.por_status.revisao ?? 0);
          setObrigatorias(e.conferencia_obrigatoria ?? 0);
        })
        .catch(() => undefined);
    buscar();
    const t = setInterval(buscar, 30000);
    return () => {
      ativo = false;
      clearInterval(t);
    };
  }, [caminho]);

  const atual = (href: string) => (href === "/" ? caminho === "/" : caminho.startsWith(href));
  const passos = trilha(caminho);
  const larga = caminho.startsWith("/documentos");

  return (
    <>
      <div className="governo">
        <div className="governo__interno">
          <span className="governo__nome">Governo do Estado do Piauí</span>
          <span className="governo__orgao">SEMARH</span>
        </div>
      </div>
      <header className="topo">
        <div className="topo__interno">
          <Link href="/" className="topo__marca">
            {logo ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={logo} alt="SEMARH — Governo do Piauí" className="topo__logo" />
            ) : null}
            <span className="topo__nome">
              Conferência de Requerimentos
              <small>Secretaria do Meio Ambiente e Recursos Hídricos</small>
            </span>
          </Link>
          <span className="topo__sistema">Integrado ao SIGA</span>
        </div>
        <nav className="nav" aria-label="Principal">
          <div className="nav__interno">
            {LINKS.map((l) => (
              <Link key={l.href} href={l.href} aria-current={atual(l.href) ? "page" : undefined}>
                <Icone nome={l.icone} />
                {l.rotulo}
                {l.href === "/revisao" && emRevisao ? (
                  <span className="contador" aria-label={`${emRevisao} documentos aguardando revisão`}>
                    {emRevisao}
                  </span>
                ) : null}
                {/* lidos abaixo do limiar de confiança: só saem da fila conferidos na tela */}
                {l.href === "/revisao" && obrigatorias > 0 ? (
                  <span className="contador contador--alerta" title="Conferência obrigatória">
                    <span aria-hidden>{obrigatorias}</span>
                    <span className="pular">
                      {obrigatorias === 1
                        ? "1 documento com conferência obrigatória"
                        : `${obrigatorias} documentos com conferência obrigatória`}
                    </span>
                  </span>
                ) : null}
              </Link>
            ))}
          </div>
        </nav>
      </header>
      {passos.length > 0 && (
        <nav className={`trilha${larga ? " trilha--larga" : ""}`} aria-label="Você está em">
          <ol>
            <li>
              <Link href="/" className="trilha__inicio">
                <Icone nome="inicio" tamanho={16} />
                Início
              </Link>
            </li>
            {passos.map((p) => (
              <li key={p.rotulo}>
                <Icone nome="seta" tamanho={14} className="trilha__seta" />
                {p.href ? <Link href={p.href}>{p.rotulo}</Link> : <span aria-current="page">{p.rotulo}</span>}
              </li>
            ))}
          </ol>
        </nav>
      )}
    </>
  );
}
