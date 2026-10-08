---
name: Conferência de Requerimentos — SEMARH-PI
description: Sistema governamental do Piauí para conferir, campo a campo, requerimentos de outorga lidos por OCR.
colors:
  fundo: "#f1f4f8"
  folha: "#ffffff"
  tinta: "#1b2430"
  tinta-2: "#4d5969"
  linha: "#c3ccd8"
  linha-suave: "#e2e7ee"
  azul: "#0b3d91"
  azul-hover: "#093279"
  azul-escuro: "#06275c"
  azul-claro: "#e7eef9"
  azul-medio: "#c8d7f0"
  verde: "#00843d"
  verde-texto: "#006630"
  verde-fundo: "#e2f3e8"
  amarelo: "#ffcd00"
  marca: "#f2d21b"
  marca-borda: "#8a7600"
  atencao: "#9a5800"
  atencao-fundo: "#fff4d9"
  atencao-borda: "#ecc56b"
  erro: "#b3261e"
  erro-fundo: "#fce9e7"
  erro-borda: "#eeb1ab"
  pronto: "#6e4e00"
  pronto-fundo: "#ffefa8"
  foco: "#c2850c"
  visor-fundo: "#dfe5ee"
  borda-entrada: "#8a96a8"
typography:
  display:
    fontFamily: "Atkinson Hyperlegible, Segoe UI, system-ui, sans-serif"
    fontSize: "1.44rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Atkinson Hyperlegible, Segoe UI, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Atkinson Hyperlegible, Segoe UI, system-ui, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 700
    lineHeight: 1.2
  title-grupo:
    fontFamily: "Atkinson Hyperlegible, Segoe UI, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 700
    lineHeight: 1.2
  body:
    fontFamily: "Atkinson Hyperlegible, Segoe UI, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Atkinson Hyperlegible, Segoe UI, system-ui, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 700
    lineHeight: 1.5
  label-pequeno:
    fontFamily: "Atkinson Hyperlegible, Segoe UI, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 700
    lineHeight: 1.5
  mono:
    fontFamily: "Atkinson Hyperlegible Mono, ui-monospace, Cascadia Mono, monospace"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tnum"
rounded:
  pequeno: "6px"
  medio: "10px"
  grande: "14px"
  pilula: "999px"
spacing:
  xs: "0.35rem"
  sm: "0.6rem"
  md: "1rem"
  lg: "1.5rem"
  pagina-base: "4rem"
components:
  button-primary:
    backgroundColor: "{colors.azul}"
    textColor: "{colors.folha}"
    rounded: "{rounded.pilula}"
    padding: "0.4rem 1.4rem"
    height: "2.5rem"
  button-primary-hover:
    backgroundColor: "{colors.azul-hover}"
    textColor: "{colors.folha}"
  button-primary-active:
    backgroundColor: "{colors.azul-escuro}"
  button-secondary:
    backgroundColor: "{colors.folha}"
    textColor: "{colors.azul}"
    rounded: "{rounded.pilula}"
    padding: "0.4rem 1.4rem"
    height: "2.5rem"
  button-secondary-hover:
    backgroundColor: "{colors.azul-claro}"
    textColor: "{colors.azul-hover}"
  button-text:
    backgroundColor: "transparent"
    textColor: "{colors.azul}"
    rounded: "{rounded.pilula}"
    padding: "0.4rem 0.7rem"
  button-small:
    rounded: "{rounded.pilula}"
    padding: "0.2rem 0.9rem"
    height: "2rem"
  input:
    backgroundColor: "{colors.folha}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.pequeno}"
    padding: "0.45rem 0.75rem"
    height: "2.5rem"
  status-extraido:
    backgroundColor: "{colors.pronto-fundo}"
    textColor: "{colors.pronto}"
    rounded: "{rounded.pilula}"
    typography: "{typography.label-pequeno}"
    padding: "0.15rem 0.65rem 0.15rem 0.55rem"
  status-validado:
    backgroundColor: "{colors.verde}"
    textColor: "{colors.folha}"
    rounded: "{rounded.pilula}"
  status-revisao:
    backgroundColor: "{colors.erro-fundo}"
    textColor: "{colors.erro}"
    rounded: "{rounded.pilula}"
  status-erro:
    backgroundColor: "{colors.erro}"
    textColor: "{colors.folha}"
    rounded: "{rounded.pilula}"
  status-processando:
    backgroundColor: "{colors.azul-claro}"
    textColor: "{colors.azul}"
    rounded: "{rounded.pilula}"
  card:
    backgroundColor: "{colors.folha}"
    rounded: "{rounded.grande}"
    padding: "1.5rem"
  barra-governo:
    backgroundColor: "{colors.azul-escuro}"
    textColor: "{colors.folha}"
    typography: "{typography.label-pequeno}"
    padding: "0.45rem 1.5rem"
  nav-item-ativo:
    textColor: "{colors.azul}"
    padding: "0.85rem 1rem 0.75rem"
  contador:
    backgroundColor: "{colors.amarelo}"
    textColor: "{colors.azul-escuro}"
    rounded: "{rounded.pilula}"
    typography: "{typography.label-pequeno}"
  selo:
    backgroundColor: "{colors.azul-claro}"
    textColor: "{colors.azul-escuro}"
    rounded: "{rounded.pilula}"
    typography: "{typography.label-pequeno}"
---

# Design System: Conferência de Requerimentos — SEMARH-PI

## Overview

**Creative North Star: "A Repartição Bem Sinalizada"**

Um sistema de Estado que se reconhece em um segundo: barra do Governo do Piauí no topo, faixa verde e amarela da bandeira, cabeçalho institucional branco com o nome do sistema, menu com ícones, trilha "Início › Seção › Item" e rodapé do órgão em azul-escuro. É a estrutura dos serviços de governo digital brasileiros traduzida nas cores do Piauí, e é ela que dá ao técnico a certeza de estar num sistema oficial.

Dentro dessa moldura, a interface é densa e calma: fundo cinza-azulado claro, superfícies brancas de cantos generosos com sombra azulada difusa, ações em pílula azul. Na tela de conferência a folha digitalizada é protagonista; o formulário aponta para ela, e o amarelo de marca-texto liga o campo em foco ao trecho exato da folha. Nada de painel escuro e quadrado: o sistema anterior era um "painel SaaS" e foi recusado.

A tipografia é uma família só, Atkinson Hyperlegible, escolhida porque distingue 0/O e 1/l/I, que é exatamente o trabalho de quem confere um OCR. A versão mono aparece apenas nos valores numéricos extraídos.

**Key Characteristics:**
- Moldura governamental fixa: barra do governo, faixa da bandeira (4px), cabeçalho, menu, trilha, rodapé.
- Azul institucional conduz toda ação e navegação; verde e amarelo são fio de identidade e sinal de sucesso.
- Superfícies brancas sobre fundo frio, com sombra suave tingida de azul.
- Pílula em tudo que é ação ou rótulo de situação; retângulo arredondado em tudo que é conteúdo.
- Foco tracejado âmbar, visível sobre azul e sobre branco.
- Uma família tipográfica de alta legibilidade, mono só para números.

## Colors

Paleta institucional contida: um azul que manda, as cores da bandeira como assinatura, e estados semânticos em pares fundo-claro/texto-escuro.

### Primary
- **Azul Institucional do Piauí** (`azul`): botões primários, links, item ativo do menu, página selecionada no visor. Toda ação clicável é azul.
- **Azul de Pressão** (`azul-hover`): hover de botões e links.
- **Azul-Noite de Estado** (`azul-escuro`): barra do governo, rodapé, títulos de página (h1), nome do sistema no cabeçalho, títulos de grupo, cabeçalhos de tabela, estado `:active` do botão.
- **Azul-Papel** (`azul-claro`): hover de menu e de botões secundários/texto, fundo de cabeçalho de tabela, situações "recebido/processando", selo "corrigido", fundo de aviso informativo.
- **Azul-Bruma** (`azul-medio`): anel de foco do campo, borda inferior do cabeçalho de tabela, borda tracejada do estado vazio, seleção de texto.

### Secondary
- **Verde da Bandeira** (`verde`): metade esquerda da faixa da bandeira, situação "validado" (pílula cheia com texto branco) e sua parte na barra de progresso, medidor de confiança alto.
- **Verde-Texto** (`verde-texto`) sobre **Verde-Folha** (`verde-fundo`): situação "concluído" do lote, aviso de sucesso, inserções no histórico.

### Tertiary
- **Amarelo da Bandeira** (`amarelo`): metade direita da faixa da bandeira e o contador de pendências no menu (com texto azul-noite).
- **Marca-Texto** (`marca`) com **Borda de Marca-Texto** (`marca-borda`): exclusivos do campo ativo na conferência, a 50% de opacidade com `mix-blend-mode: multiply` sobre a folha, e como anel do campo de formulário correspondente.

### Neutral
- **Fundo Cinza-Azulado** (`fundo`): fundo de página.
- **Folha Branca** (`folha`): cartões, grupos, cabeçalho, tabelas, barra de ações.
- **Tinta** (`tinta`): texto corrente.
- **Tinta Secundária** (`tinta-2`): descrições, metadados, rótulos de tabela empilhada, ícones do menu em repouso.
- **Linha** (`linha`) e **Linha Suave** (`linha-suave`): divisórias; a suave separa linhas de tabela e de lista, a cheia separa logo e nome e borda controles secundários.
- **Mesa do Visor** (`visor-fundo`): a bancada cinza onde a folha digitalizada repousa.
- **Borda de Entrada** (`borda-entrada`): contorno de campos em repouso, escuro o bastante para AA não-texto.

### Estados
- **Atenção** (`atencao` / `atencao-fundo` / `atencao-borda`), **Erro** (`erro` / `erro-fundo` / `erro-borda`): sempre em trio; texto escuro sobre fundo claro com borda média. O **Âmbar de Foco** (`foco`) é só do anel de foco.
- **Pronto** (`pronto` sobre `pronto-fundo`): amarelo do semáforo, só na situação "pronto para validar" e na sua parte da barra de progresso.

### Semáforo da situação
O documento lido segue um semáforo: **vermelho** (`erro-fundo`/`erro`) = com possíveis divergências, **amarelo** (`pronto-fundo`/`pronto`) = pronto para validar, **verde** (`verde`, cheio) = validado. Erro de leitura é vermelho cheio, para não se confundir com a revisão. A barra de progresso do lote usa as mesmas cores, e a legenda leva um ponto de cada cor.

### Named Rules
**A Regra do Azul que Age.** Se é clicável, é azul institucional; se é azul cheio, é clicável. Nenhum outro matiz conduz ação.

**A Regra da Bandeira como Fio.** Verde e amarelo da bandeira aparecem como faixa de 4px (topo do cabeçalho e topo do rodapé), em sucesso, no semáforo da situação e no contador de pendências. Nunca como fundo de área nem como cor de botão.

**A Regra do Marca-Texto Único.** O amarelo de marca-texto pertence a um só campo por vez: o que está em foco. Pendências na folha usam sublinhado âmbar ou vermelho, nunca amarelo.

## Typography

**Display Font:** Atkinson Hyperlegible (com Segoe UI, system-ui, sans-serif)
**Body Font:** Atkinson Hyperlegible (mesma família)
**Label/Mono Font:** Atkinson Hyperlegible Mono (com ui-monospace, Cascadia Mono, monospace)

**Character:** Uma voz única, sóbria e funcional, de serviço público; a hierarquia vem do peso 700 e do azul-noite, não de troca de família. Escala 1.2 sobre 16px.

### Hierarchy
- **Display** (700, 1.44rem, 1.15): nome do sistema no cabeçalho institucional, com o nome do órgão abaixo em 0.9rem/400 na tinta secundária. Cai para 1.2rem em ≤760px.
- **Headline** (700, 1.75rem, 1.2, -0.01em): o h1 da página, em azul-noite, com `text-wrap: balance`. Cai para 1.44rem em ≤760px.
- **Title** (700, 1.2rem, 1.2): h2 de seção; também o título do estado vazio.
- **Title de grupo** (700, 1rem): cabeçalho de cada grupo do formulário de conferência, em azul-noite, separado por linha suave.
- **Body** (400, 1rem, 1.5): texto corrente; descrições de página limitadas a 68ch.
- **Label** (700, 0.9rem): rótulos de campo, itens da trilha (400), legenda de progresso.
- **Label pequeno** (700, 0.8125rem): situação em pílula, cabeçalho de tabela, contador, selo, barra do governo (esta em caixa alta com 0.06em de espaçamento).
- **Mono** (400, tabular): CPF/CNPJ, coordenadas, áreas, datas e campos numéricos; sem quebra de linha.

### Named Rules
**A Regra do Zero Inconfundível.** Todo valor numérico extraído é composto em Atkinson Hyperlegible Mono com algarismos tabulares. Texto corrido nunca vai em mono.

**A Regra de Uma Família.** Não se introduz segunda família de exibição; peso e cor fazem a hierarquia.

## Layout

Coluna central de 1200px com respiro lateral de 1.5rem (1rem em ≤760px); a barra do governo, o cabeçalho, o menu, a trilha e o rodapé compartilham essa largura. A tela de conferência (`pagina--larga`) abre a moldura inteira para 1440px, para que a folha e o formulário caibam lado a lado.

- **Conferência:** grade de duas colunas, folha à esquerda (1.1fr) e formulário à direita (mínimo 380px). O visor é fixo ao rolar (`sticky`, topo 1rem, altura máxima da viewport). Em ≤1024px vira uma coluna e o visor fica estático com 70vh.
- **Barra de ações fixa:** salvar e validar ficam numa barra branca colada à base do formulário, com sombra para cima.
- **Formulário:** grupos empilhados com 1.25rem de intervalo; campos em grade de duas colunas, uma coluna em ≤760px.
- **Envio:** duas colunas 1.4fr/1fr (zona de soltar + formulário), uma coluna em ≤760px.
- **Ritmo:** 0.35rem entre rótulo e campo, 0.6rem entre ações, 1rem entre campos, 1.5rem entre blocos e de padding de cartão, 4rem de base de página.
- **Celular (≤760px):** some o nome do órgão na barra do governo, o selo "Integrado ao SIGA" e os ícones do menu; o menu rola na horizontal; colunas opcionais das tabelas são ocultadas; linhas de itens repetidos (localidades, estabelecimentos, sistemas de irrigação) viram blocos empilhados, cada célula com seu rótulo próprio vindo de `data-rotulo`, divididos por linha suave, sem divisória após o último.

## Elevation & Depth

Híbrido discreto: superfícies brancas levemente elevadas sobre o fundo frio, sombras sempre tingidas do azul-noite (rgba 11,33,72), nunca pretas. A profundidade separa conteúdo de fundo; dentro de um cartão tudo é plano.

### Shadow Vocabulary
- **Repouso** (`box-shadow: 0 1px 2px rgba(11,33,72,.06), 0 2px 8px rgba(11,33,72,.07)`): cabeçalho institucional, blocos, grupos, tabelas soltas.
- **Destaque** (`box-shadow: 0 2px 4px rgba(11,33,72,.06), 0 8px 24px rgba(11,33,72,.1)`): link "Ir para o conteúdo" quando focado.
- **Folha** (`box-shadow: 0 1px 2px rgba(11,33,72,.12), 0 4px 14px rgba(11,33,72,.12)`): a página digitalizada sobre a mesa do visor.
- **Barra de ações** (`box-shadow: 0 -4px 18px rgba(11,33,72,.12)`): sombra para cima da barra fixa de salvar/validar.
- **Hover do botão primário** (`box-shadow: 0 2px 8px rgba(11,61,145,.25)`): única sombra de estado.

### Named Rules
**A Regra do Cartão Único.** Tabela dentro de bloco ou grupo perde sombra, raio e fundo; não existe cartão dentro de cartão.

## Shapes

Duas famílias de forma, sem mistura: **pílula** (999px) para tudo que é ação ou rótulo curto (botões, situação, contador, selo, paginação do visor, busca dos filtros) e **retângulo arredondado** para conteúdo: 14px em cartões, grupos, tabelas, visor e zona de soltar; 10px em avisos e na área de rolagem do visor; 6px em campos de texto. Bordas são de 1px na linha suave ou cheia; bordas tracejadas de 2px marcam só o que recebe algo (zona de soltar, estado vazio). A situação em pílula leva um ponto de 0.5rem na cor do texto.

## Components

### Buttons
Pílulas firmes, sem ornamento, com borda de 2px que mantém o mesmo tamanho em todas as variantes.
- **Shape:** pílula (999px), altura mínima 2.5rem, ícone opcional com 0.45rem de intervalo.
- **Primary:** azul institucional cheio, texto branco 700.
- **Hover / Focus:** escurece para o azul de pressão e ganha a sombra de hover; `:active` vai ao azul-noite sem sombra; foco é o anel tracejado âmbar global. Transições de 0.15s ease-out.
- **Secundário:** branco com borda e texto azuis; hover em azul-papel.
- **Texto:** sem borda nem fundo, hover em azul-papel; usado para "Remover".
- **Pequeno:** altura 2rem, 0.875rem; usado em "Adicionar item", "Ampliar".
- **Desabilitado:** cinza claro com texto cinza, sem sombra.

### Chips (situação)
- **Style:** pílula de 0.8125rem/700 com ponto à esquerda, no semáforo da situação: "com possíveis divergências" em vermelho claro, "pronto para validar" em amarelo, "validado" em verde cheio com texto branco. "Erro" é vermelho cheio com texto branco; "concluído" (lote) em verde claro; recebido/processando em azul-papel com ponto pulsante de 1.2s.
- **Contador:** pílula amarela com número azul-noite, só no item "Revisão" do menu.
- **Selo:** pílula azul-papel "corrigido" ao lado do rótulo do campo.

### Diálogo de confirmação
- **Style:** `<dialog>` modal em cartão branco de 14px com sombra de nível 2, até 28rem de largura, conteúdo centrado: ícone de confirmado em verde (48px), título azul-noite, texto em tinta secundária e um único botão primário em largura total. Fundo azul-noite a 45%.
- **Uso:** depois de validar. O botão (com foco inicial) e o Esc levam à lista de onde o documento foi aberto (fila de revisão, lote ou requerimentos).

### Cards / Containers
- **Corner Style:** 14px.
- **Background:** folha branca sobre fundo cinza-azulado.
- **Shadow Strategy:** sombra de repouso (ver Elevation & Depth).
- **Border:** nenhuma; o grupo de conferência tem só a divisória sob o título.
- **Internal Padding:** 1.5rem no bloco; 1.4rem no grupo, com título em faixa de 0.85rem 1.4rem.

### Inputs / Fields
- **Style:** fundo branco, borda 1px cinza-ardósia, raio 6px, altura mínima 2.5rem; hover leva a borda ao azul.
- **Focus:** borda azul e anel de 3px azul-bruma; com teclado, o anel tracejado âmbar.
- **Campo ativo da conferência:** borda marca-texto e anel amarelo de 3px, espelhando o trecho realçado na folha.
- **Error / Atenção:** borda vermelha ou âmbar, mensagem de 0.85rem abaixo; campo alterado à mão ganha fundo creme. Um medidor de confiança de 3px pode acompanhar o campo.
- **Busca de filtros:** o mesmo campo em pílula.

### Navigation
- **Barra do governo:** faixa azul-noite, 0.8125rem/700 em caixa alta, "Governo do Estado do Piauí" à esquerda e "SEMARH" à direita (oculto no celular).
- **Cabeçalho:** branco, faixa da bandeira de 4px no topo, logo oficial opcional (48px, separado por linha vertical, só quando o arquivo existe em `public/`), nome do sistema em display, selo "Integrado ao SIGA" em pílula azul-papel à direita.
- **Menu:** itens 700 com ícone de traço de 20px em tinta secundária; hover em azul-papel com texto e ícone azuis; ativo com texto azul e sublinhado de 4px azul. No celular, sem ícones e com rolagem horizontal.
- **Trilha:** 0.9rem, ícone de casa em "Início", chevron de 14px entre itens, página atual em tinta secundária sem link.
- **Rodapé:** azul-noite com faixa da bandeira no topo, nome do órgão em branco 700 e descrição em azul pálido limitada a 52ch.

### Ícones
Conjunto próprio de traço único, 24×24, traço 2, pontas e junções arredondadas, `currentColor`, sempre decorativo ao lado de um texto que nomeia a ação. Os avisos usam o mesmo desenho aplicado como máscara.

### Visor e marca-texto (assinatura)
A folha digitalizada repousa numa mesa cinza (14px, padding 0.75rem) com barra de páginas em pílulas. Cada campo lido tem uma marca sobre a folha: sublinhado verde a 50% quando ok, âmbar ou vermelho com véu tênue quando pendente. O campo em foco recebe o marca-texto amarelo, que "risca" da esquerda para a direita em 0.35s quando o movimento é permitido.

### Avisos
Retângulo de 10px com ícone mascarado à esquerda; âmbar por padrão, vermelho para erro, verde para sucesso, azul-papel para informação (`role="status"`).

## Do's and Don'ts

### Do:
- **Do** manter a moldura governamental completa em toda rota: barra do governo, faixa da bandeira, cabeçalho, menu, trilha, rodapé.
- **Do** usar pílula azul para toda ação e retângulo de 14px com sombra de repouso para todo conteúdo.
- **Do** compor CPF, coordenadas, áreas e datas em Atkinson Hyperlegible Mono tabular.
- **Do** usar o anel tracejado âmbar (3px, offset 3px) como foco de teclado em todo elemento interativo.
- **Do** expressar estados em trios fundo claro / texto escuro / borda média, com texto que nomeia o estado.
- **Do** empilhar linhas de itens repetidos em blocos rotulados no celular, em vez de forçar rolagem horizontal.
- **Do** tingir toda sombra com o azul-noite (rgba 11,33,72).

### Don't:
- **Don't** voltar ao "painel SaaS" escuro e quadrado que este sistema substituiu.
- **Don't** desenhar, imitar ou aproximar a marca oficial do Governo ou da SEMARH; sem arquivo de logo, o nome do órgão vai escrito.
- **Don't** usar verde ou amarelo da bandeira como cor de botão ou fundo de área.
- **Don't** usar o amarelo de marca-texto para nada além do campo em foco.
- **Don't** colocar tabela-cartão dentro de cartão.
- **Don't** introduzir segunda família tipográfica ou ícones de fonte/emoji; ícones novos seguem o traço 24×24/2.
- **Don't** deixar um valor numérico extraído quebrar linha ou aparecer em fonte proporcional.
