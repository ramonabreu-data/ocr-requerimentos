"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { nivelConfianca } from "@/lib/formato";
import type { Campo, PaginaLida } from "@/lib/tipos";

export const chaveCampo = (c: Pick<Campo, "campo" | "indice">) => `${c.campo}:${c.indice ?? ""}`;

interface Props {
  uuid: string;
  paginas: PaginaLida[];
  campos: Campo[];
  ativo: string | null;
  onSelecionar: (chave: string) => void;
}

/** Folha digitalizada com uma marca sobre cada trecho lido. O campo em foco ganha o marca-texto. */
export default function Visor({ uuid, paginas, campos, ativo, onSelecionar }: Props) {
  const [pagina, setPagina] = useState(1);
  const [ampliado, setAmpliado] = useState(false);
  const [carregada, setCarregada] = useState(false);
  const marcas = useRef<Record<string, HTMLButtonElement | null>>({});

  const campoAtivo = campos.find((c) => chaveCampo(c) === ativo);

  useEffect(() => {
    if (campoAtivo?.pagina && campoAtivo.pagina !== pagina) setPagina(campoAtivo.pagina);
  }, [campoAtivo, pagina]);

  useEffect(() => {
    if (!ativo) return;
    const el = marcas.current[ativo];
    if (el) {
      const suave = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ block: "center", inline: "nearest", behavior: suave ? "smooth" : "auto" });
    }
  }, [ativo, pagina, carregada, ampliado]);

  const pag = paginas.find((p) => p.numero === pagina) ?? paginas[0];
  if (!pag) return <div className="visor"><p className="carregando">Sem imagem para exibir.</p></div>;

  const visiveis = campos.filter((c) => c.bbox && (c.pagina ?? 1) === pag.numero && c.valor_bruto);

  return (
    <div className="visor">
      <div className="visor__barra">
        {paginas.length > 1 ? (
          <div className="visor__paginas" role="group" aria-label="Páginas">
            {paginas.map((p) => (
              <button key={p.numero} aria-pressed={p.numero === pag.numero} onClick={() => setPagina(p.numero)}>
                {p.numero}
              </button>
            ))}
          </div>
        ) : (
          <span className="discreto">Página 1</span>
        )}
        <span className="discreto">
          {pag.metodo === "ocr" ? `Lida por OCR, ${Math.round(pag.confianca_media ?? 0)}% de confiança média` : "Texto do próprio PDF"}
          {pag.angulo_correcao ? `, endireitada ${Math.abs(pag.angulo_correcao).toLocaleString("pt-BR")}°` : ""}
        </span>
        <button className="botao botao--secundario botao--pequeno" onClick={() => setAmpliado((a) => !a)} aria-pressed={ampliado}>
          {ampliado ? "Ajustar à largura" : "Ampliar"}
        </button>
      </div>
      <div className="visor__rolagem">
        <div className="folha" style={{ width: ampliado ? "170%" : "100%" }}>
          {pag.tem_imagem ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={api.imagemUrl(uuid, pag.numero)}
              alt={`Página ${pag.numero} do documento digitalizado`}
              width={pag.largura}
              height={pag.altura}
              onLoad={() => setCarregada(true)}
            />
          ) : (
            <p className="carregando">Imagem da página indisponível.</p>
          )}
          {visiveis.map((c) => {
            const [x0, y0, x1, y1] = c.bbox!;
            const k = chaveCampo(c);
            const nivel = c.corrigido_manual ? "ok" : nivelConfianca(c.confianca, c.valido);
            const folga = 0.004;
            return (
              <button
                key={k}
                ref={(el) => {
                  marcas.current[k] = el;
                }}
                type="button"
                className={`marca marca--${nivel}${k === ativo ? " marca--ativa" : ""}`}
                style={{
                  left: `${(x0 / pag.largura - folga) * 100}%`,
                  top: `${(y0 / pag.altura - folga / 2) * 100}%`,
                  width: `${((x1 - x0) / pag.largura + folga * 2) * 100}%`,
                  height: `${((y1 - y0) / pag.altura + folga) * 100}%`,
                }}
                onClick={() => onSelecionar(k)}
                aria-label={`Ir para o campo ${c.rotulo}${c.indice != null ? ` ${c.indice + (c.campo === "finalidade" ? 1 : 0)}` : ""}`}
                title={c.rotulo}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
