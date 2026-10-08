# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Técnicos da SEMARH-PI (Secretaria do Meio Ambiente e Recursos Hídricos do Piauí) que conferem
requerimentos de outorga digitalizados, em computador de mesa, várias horas por dia. Não há uso
pelo cidadão ou por prefeituras nesta interface.

## Product Purpose

Lê requerimentos de outorga ("Regularização de Poço Tubular" e afins) em PDF do sistema, PDF
assinado, PDF de scanner, foto ou imagem; extrai os campos, confere com o cadastro do SIGA e grava
em PostgreSQL. Sucesso é o técnico validar um requerimento conferindo a folha ao lado dos campos,
sem redigitar nada, e resolver as pendências que o OCR levantou.

## Operating Context

- Fluxo: envio (um arquivo, vários, ZIP ou pasta monitorada do scanner) → lote → fila de revisão →
  tela de conferência (folha à esquerda, formulário à direita, cada campo marcado no trecho da folha)
  → validar (com justificativa quando há pendências).
- Situações do documento: recebido, processando, extraído (pronto para validar), revisão, validado,
  erro, dividido.
- Integra o SIGA (login futuro via Better Auth do SIGA).

## Capabilities and Constraints

- Next.js (App Router) em `apps/web`; a API Python fica atrás de um proxy `/api/ocr`.
- Interface inteira em português do Brasil.
- Números extraídos (CPF/CNPJ, coordenadas, áreas, datas) precisam ser lidos sem ambiguidade entre
  0/O e 1/l/I.

## Brand Commitments

- Identidade do Governo do Estado do Piauí / SEMARH, com a estrutura e as convenções de um sistema
  governamental brasileiro (pedido do usuário em 05/10/2026).
- Logos oficiais serão fornecidos pelo usuário em `apps/web/public/`; até lá, nada de desenhar ou
  imitar marca oficial — o nome do órgão vai escrito.

## Evidence on Hand

- PDFs reais de exemplo fora do repositório (`~/Área de trabalho/outorgas-exemplo`) e o PDF de teste
  `services/ocr/tests/fixtures/requerimento_exemplo.pdf`.
- Sem arquivos de logo no repositório ainda.

## Product Principles

1. A folha digitalizada é a prova; a interface aponta para ela, não compete com ela.
2. Nenhum dado é aceito em silêncio: pendência sempre visível e justificada ao validar.
3. Ser reconhecível como sistema do Governo do Piauí, sem perder velocidade de trabalho.

## Accessibility & Inclusion

Uso prolongado por servidores públicos: contraste AA no mínimo, navegação por teclado, foco visível,
textos em linguagem simples (eMAG / boas práticas de governo digital).
