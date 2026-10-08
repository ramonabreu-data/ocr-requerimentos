"use client";

import { useEffect, useRef } from "react";
import Icone from "./Icone";

/** Pop-up depois de validar. O botão (ou Esc) leva para a lista de onde o documento foi aberto. */
export default function ConfirmacaoValidado({
  nome,
  comJustificativa,
  rotuloLista,
  aoIrParaLista,
}: {
  nome: string;
  comJustificativa: boolean;
  rotuloLista: string;
  aoIrParaLista: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      className="dialogo"
      aria-labelledby="dialogo-titulo"
      aria-describedby="dialogo-texto"
      onCancel={(e) => {
        e.preventDefault();
        aoIrParaLista();
      }}
    >
      <Icone nome="confirmado" tamanho={48} className="dialogo__icone" />
      <h2 id="dialogo-titulo">Documento validado</h2>
      <p id="dialogo-texto">
        <strong>{nome}</strong> foi validado e já aparece como Validado nas listas.
        {comJustificativa && " A justificativa ficou registrada no histórico."}
      </p>
      <button className="botao" autoFocus onClick={aoIrParaLista}>
        {rotuloLista}
      </button>
    </dialog>
  );
}
