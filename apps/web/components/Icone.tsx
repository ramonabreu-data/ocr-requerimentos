// Ícones de traço único (24×24, traço 2), desenhados para a interface. Decorativos: o texto ao lado
// sempre nomeia a ação, então ficam fora da árvore de acessibilidade.
const CAMINHOS = {
  inicio: "M3 10.5 12 3l9 7.5M5 9v11h5v-6h4v6h5V9",
  enviar: "M12 16V4m0 0L7 9m5-5 5 5M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4",
  lotes: "m12 3 9 4.5-9 4.5-9-4.5L12 3Zm-9 9 9 4.5 9-4.5M3 16.5 12 21l9-4.5",
  revisao: "M9 4h6v3H9zM8 5.5H6a1 1 0 0 0-1 1V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6.5a1 1 0 0 0-1-1h-2M9 14l2 2 4-4",
  requerimentos: "M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7l-4-4Zm0 0v4h4M9 12h6M9 16h6",
  seta: "m9 6 6 6-6 6",
  baixar: "M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M4 19h16",
  filtro: "M4 5h16l-6 7.5V18l-4 2v-7.5L4 5Z",
  nuvem: "M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 8.5a4 4 0 0 1 .5 7.97M12 12v8m0-8-3 3m3-3 3 3",
  arquivo: "M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7l-4-4Zm0 0v4h4",
  confirmado: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-13 0 3 3 5-6",
} as const;

export type NomeIcone = keyof typeof CAMINHOS;

export default function Icone({ nome, tamanho = 20, className }: { nome: NomeIcone; tamanho?: number; className?: string }) {
  return (
    <svg
      className={className ? `icone ${className}` : "icone"}
      width={tamanho}
      height={tamanho}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={CAMINHOS[nome]} />
    </svg>
  );
}
