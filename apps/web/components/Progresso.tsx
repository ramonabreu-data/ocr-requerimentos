import type { LoteResumo } from "@/lib/tipos";

/** Barra empilhada: validados (verde), prontos (amarelo), com possíveis divergências (vermelho), erro, desconsiderados (cinza). */
export default function Progresso({ lote, legenda = false }: { lote: LoteResumo; legenda?: boolean }) {
  const total = Math.max(lote.total, 1);
  const prontos = Math.max(lote.processados - lote.em_revisao - lote.com_erro - lote.validados - (lote.desconsiderados ?? 0), 0);
  const partes = [
    { classe: "p-validado", n: lote.validados, rotulo: "validados" },
    { classe: "p-ok", n: prontos, rotulo: "prontos para validar" },
    { classe: "p-revisao", n: lote.em_revisao, rotulo: "com possíveis divergências" },
    { classe: "p-erro", n: lote.com_erro, rotulo: "com erro" },
    // só aparece na legenda quando há algum: é exceção, não etapa do lote
    ...(lote.desconsiderados ? [{ classe: "p-desconsiderado", n: lote.desconsiderados, rotulo: "desconsiderados" }] : []),
  ];
  const fila = lote.total - lote.processados;
  return (
    <div>
      <div
        className="progresso"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={lote.total}
        aria-valuenow={lote.processados}
        aria-label={`${lote.processados} de ${lote.total} documentos lidos`}
      >
        {partes.map((p) => (p.n ? <span key={p.classe} className={p.classe} style={{ width: `${(p.n / total) * 100}%` }} /> : null))}
      </div>
      {legenda && (
        <div className="legenda-progresso">
          {partes.map((p) => (
            <span key={p.classe}>
              <i className={p.classe} aria-hidden="true" />
              <b>{p.n}</b> {p.rotulo}
            </span>
          ))}
          {fila > 0 && (
            <span>
              <b>{fila}</b> na fila
            </span>
          )}
        </div>
      )}
    </div>
  );
}
