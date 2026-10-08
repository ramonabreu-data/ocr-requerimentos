import { ROTULO_STATUS } from "@/lib/formato";

export default function Status({ valor }: { valor: string }) {
  return <span className={`status status--${valor}`}>{ROTULO_STATUS[valor] ?? valor}</span>;
}
