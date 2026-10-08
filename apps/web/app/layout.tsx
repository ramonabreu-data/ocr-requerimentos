import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "@fontsource/atkinson-hyperlegible-mono/400.css";
import "@fontsource/atkinson-hyperlegible-mono/700.css";
import "./globals.css";

import { existsSync } from "node:fs";
import { join } from "node:path";
import type { Metadata } from "next";
import Navegacao from "@/components/Navegacao";

export const metadata: Metadata = {
  title: "Conferência de Requerimentos — SEMARH-PI",
  description: "Leitura e conferência de requerimentos digitalizados do SIGA",
};

// Logo oficial: basta colocar o arquivo em public/ (svg tem preferência) e recompilar a imagem.
const LOGO = ["logo-semarh.svg", "logo-semarh.png"].find((f) => existsSync(join(process.cwd(), "public", f)));

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <a href="#conteudo" className="pular">
          Ir para o conteúdo
        </a>
        <Navegacao logo={LOGO ? `/${LOGO}` : null} />
        <main id="conteudo">{children}</main>
        <footer className="rodape">
          <div className="rodape__interno">
            <div>
              <strong>Secretaria do Meio Ambiente e Recursos Hídricos — SEMARH</strong>
              <span>Governo do Estado do Piauí</span>
            </div>
            <p>Conferência de requerimentos de outorga digitalizados, integrada ao SIGA.</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
