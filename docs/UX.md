# UX/UI — diagnóstico e melhorias (30/10/2026)

Branch `ux/redesign`. Todas as medições foram feitas na pilha local (Docker), com uma conta de demonstração local de 5 ativos e preços reais de mercado. Para as telas de celular, o Chromium emulou toque (`isMobile`, `hasTouch`). **Nenhum aparelho físico nem Safari foi testado.**

## 1. Diagnóstico inicial

| # | Problema | Impacto | Frequência | Gravidade | Esforço |
|---|---|---|---|---|---|
| 1 | Dashboard e carteira abriam com 4 cartões iguais (patrimônio, resultado, variação 24h, TWR), que ocupavam a primeira tela inteira do celular; o gráfico nem aparecia | alto | toda visita | alta | médio |
| 2 | O dashboard não respondia "o que precisa da minha atenção": os sinais dos ativos que o usuário tem só existiam na página de oportunidades | alto | diária | alta | médio |
| 3 | Metade do dashboard eram 3 listas genéricas de mercado e 4 cartões de indicadores, com cara de painel administrativo | médio | toda visita | média | baixo |
| 4 | Explicações (ⓘ, termos pontilhados) usavam tooltip, que **não abre com toque**: no celular eram inacessíveis | alto | frequente | alta | baixo |
| 5 | Botões de 28–32px, campos e abas de 32px: abaixo dos 44px recomendados para toque | médio | constante | média | baixo |
| 6 | Conexão lenta: **tela em branco** até o JavaScript inteiro carregar (páginas com `Suspense` sem fallback; barra inferior incluída) | alto | redes móveis | alta | baixo |
| 7 | Rótulo "Oportunida…" cortado na barra inferior; página ativa indicada só pela cor | médio | constante | média | baixo |
| 8 | Filtros do mercado empilhados (busca + 2 seletores em largura total); chips de sinais e de indicadores quebrando em 2–3 linhas antes do conteúdo | médio | frequente | média | baixo |
| 9 | Análise do ativo: o cenário atual (sinal) só aparecia depois do gráfico e de todos os seus controles | médio | frequente | média | baixo |
| 10 | Contraste abaixo do WCAG AA: legendas 3,3–4,1:1, vermelho de perdas 4,3:1 em linhas com hover, cor da marca como texto 3,5–4,3:1, texto branco no botão principal 4,3:1 | médio | constante | média | baixo |
| 11 | Transbordo horizontal na página de Risco em 320px | baixo | ocasional | média | baixo |
| 12 | Seis controles segmentados escritos de seis jeitos, sem navegação por setas; esqueletos mais escuros que os cartões | baixo | — | baixa | baixo |

Já estava bom e foi mantido:
- barra de navegação inferior no celular;
- lista de mercado e lista de posições já adaptadas para celular;
- `prefers-reduced-motion` respeitado;
- números tabulares;
- gráficos sem conflito com a rolagem da página.

## 2. Melhorias implementadas

- **Resumo da carteira:** um único bloco no lugar dos 4 cartões. O patrimônio vem em destaque, depois a variação do dia (com seta e sinal, não só cor), o resultado e a rentabilidade, e os retornos por período numa faixa.
- **Dashboard reorganizado:** resumo → evolução e distribuição → **Precisa da sua atenção** → posições → **Mercado hoje**.
  - *Precisa da sua atenção* reúne os sinais diários não neutros dos ativos que o usuário tem, os alertas disparados e os insights.
  - *Mercado hoje* traz os indicadores em grade e as maiores altas, baixas e o ranking em abas.
  - Nenhum cálculo novo: só dados que a API já fornecia.
- **Análise do ativo:** resumo do sinal antes do gráfico (classificação, score, qualidade dos dados, horário da análise), com atalho para a explicação completa.
- **Gráficos:**
  - Evolução com os controles numa linha no celular ("Valor/Retorno"), eixo sem rótulo cortado e setas de aporte sem texto sobreposto em telas estreitas.
  - Rosca de distribuição menor, com a legenda ao lado no celular.

## 3. Evolução mobile

- **Barra inferior:** rótulos que cabem ("Início, Carteira, Mercado, Sinais, Mais"), item ativo com fundo atrás do ícone e retorno visual ao toque.
- **Áreas de toque de 44px** em botões, campos, seletores, abas e controles segmentados, só em telas de toque; o desktop com mouse não muda.
- **Explicações** abrem com toque (popover) e fecham com toque fora.
- **Filtros do mercado** lado a lado; chips de sinais e de indicadores numa faixa única deslizável.
- **Sem transbordo horizontal** nas 11 páginas principais em 320, 360, 375, 390, 430, 768, 1024 e 1440px.

## 4. Evolução visual e design system

**Componentes novos:**
- `Segmented` substitui 6 implementações e navega por setas do teclado.
- `Hint` unifica tooltip e popover.
- `PageSkeleton` desenha o esqueleto de cada tipo de página.
- `scroll-row` faz as faixas deslizáveis.
- `AttentionPanel` é a seção "Precisa da sua atenção".

**Tokens de cor (contraste WCAG AA verificado contra fundo, cartão, superfície e hover):**

| Token | Antes | Depois | Contraste mínimo |
|---|---|---|---|
| `subtle-foreground` | #64748b | #8190a6 | 4,7:1 |
| `destructive` | #ef4444 | #f25f5f | 4,8:1 |
| `primary` (preenchimentos) | #6366f1 | #585bef | texto branco 4,8:1 |
| `primary-ink` (novo: texto e ícones na cor da marca) | — | #8b93f8 | 5,6:1 |

Os esqueletos agora são claros e visíveis sobre qualquer superfície.

## 5. Performance

Medido no build de produção, servido localmente, em 390px:

| Métrica | 3G fraco (400 ms, 400 kbit/s) | 3G bom (150 ms, 1,6 Mbit/s) |
|---|---|---|
| Primeiro conteúdo (FCP) | 2,7 s | 0,7 s |
| Valor do patrimônio visível | **14,8 s → 10,2 s** | 3,7 s → 3,6 s |
| Tela aos 3,5 s | **em branco → esqueleto + barra inferior** | — |
| JavaScript transferido | 474 KB → 478 KB | |

Os ganhos vêm de duas mudanças:
- **Gráficos sob demanda:** `lightweight-charts` e `recharts` carregam depois dos números.
- **Esqueletos no HTML do servidor:** a tela tem estrutura antes do JavaScript chegar.

O total de JavaScript praticamente não mudou; o que mudou foi a ordem de carregamento. Não alterei cache nem a frequência de atualização dos dados financeiros.

## 6. Testes

| Teste | Resultado |
|---|---|
| E2E Playwright, desktop e celular (Pixel 7 emulado) | **41 aprovados**, 3 pulados por desenho (testes de um só projeto) |
| Novos e2e: sem transbordo em 320, 375, 768 e 1024px; explicação abre com toque; seletor segmentado responde às setas | aprovados |
| Vitest, ESLint, `tsc`, `next build` | 28 aprovados / sem problemas |
| Varredura visual: 11 páginas × 8 larguras, com capturas antes e depois | sem transbordo |

**Limitações:**
- **Tabela de Risco em teste automático:** a tabela larga só aparece depois que o worker preenche o histórico de preços (a cada 6 h). A correção dela foi verificada com a conta de demonstração: o transbordo volta ao desfazer a correção. O teste e2e não cobre esse estado.
- **Leitores de tela:** não testados com leitor real.
- **Aparelhos físicos e Safari/iOS:** não testados.
- **Ajustes de teste:**
  - O e2e da carteira passou a procurar "Precisa da sua atenção" no lugar de "Insights da carteira", porque a seção mudou de nome de propósito.
  - O teste de console ganhou 120 s de limite: com a suíte inteira em paralelo, 60 s ficava apertado; cada página leva cerca de 1 s.

## 7. Próximas oportunidades

1. **Tabela de transações e formulário de nova transação no celular:** revisar como folha inferior (bottom sheet), com teclado numérico em todos os valores.
2. **Página de Risco:** a tabela de contribuição por ativo ainda rola na horizontal no celular; vale transformá-la em lista.
3. **Voryn AI e Estratégias:** passar pelo mesmo tratamento de hierarquia.
4. **Leitor de tela:** auditoria com NVDA/VoiceOver e verificação automatizada (axe) no CI.
5. **Gráfico de candles:** pinça para zoom no celular, sem conflito com a rolagem.
6. **Indicador de atualização:** marcar "dados de 5 min atrás" no resumo da carteira, como já é feito no mercado.

---

# Refinamento "Apple-grade" (30/10/2026)

Branch `ux/apple-grade`, construída sobre o redesign anterior (PR #4).

## Referências consultadas

| Referência | Acesso | O que foi usado |
|---|---|---|
| Apple HIG: *Materials*, *Tab bars*, *Layout* | lidas pela versão JSON da documentação (a página web é renderizada por JavaScript) | Liquid Glass só na camada de controles ("Don't use Liquid Glass in the content layer", "use sparingly"); variante *regular* (desfoque e escurecimento) onde há texto; barra de abas flutuante, sempre visível, para navegação e não para ações, com rótulos de uma palavra; ordem por importância, *progressive disclosure* e espaçamento consistente |
| Apple — guia de design da WWDC26 | lido | só menções gerais ao Liquid Glass; os detalhes estão na HIG acima |
| Apple Design Resources (UI Kits) | **não consultado** | são arquivos do Figma e do Sketch |
| Linear — *Behind the latest design refresh* | lido | barra lateral mais discreta que o conteúdo, cinzas menos saturados, menos separadores e mais suaves, menos ícones decorativos ("Don't compete for attention you haven't earned") |
| Mobbin | **parcial** | a página pública não mostra telas; a biblioteca de apps financeiros (Finance+) é de planos pagos |
| 21st.dev | **parcial** | catálogo genérico; nenhuma dependência adicionada |

## O que mudou

**Paleta**
- Grafite neutro em três degraus (fundo #0b0d12, superfície #151820, elevado #1c2029).
- Texto: #f5f5f7 (primário), #8e919a (secundário), #858893 (legendas).
- Ganhos #30d19a e perdas #ff6678.
- Contraste mínimo medido em todas as superfícies: 4,6:1 (legendas), 5,2:1 (texto secundário), 5,8:1 (perdas), 8,3:1 (ganhos).
- O índigo da marca foi mantido.

**Tipografia:** Inter em títulos e texto. A Sora fica só no logotipo.

**Vidro (`.glass`)**
- Desfoque de 24px, saturação 1,6 e tom escuro com 80% de opacidade, mais borda e brilho internos sutis.
- Aplicado só na barra de abas, no cabeçalho ao rolar, em menus, seletores e popovers. Nunca nos cartões de conteúdo.
- Vira fundo opaco quando o navegador não suporta desfoque, ou quando o usuário pede mais contraste ou menos transparência.

**Celular**
- Barra de abas flutuante de vidro, afastada das bordas e acima da área do indicador de início. A aba ativa tem fundo elevado e ícone mais grosso, não só cor.
- Cabeçalho transparente no topo, que vira vidro com linha fina ao rolar (efeito *scroll edge*).
- Diálogos viram folhas inferiores, com alça e animação de subida.
- Seletor de período abaixo do gráfico, na largura toda.
- Patrimônio sem moldura, com 42px, como elemento principal da tela.

**Desktop**
- Barra lateral no tom da página, com rótulos mais discretos; a página atual é marcada por uma superfície elevada.
- Cartões com contorno fino em vez de borda.

**Ordem do dashboard:** patrimônio → variação → gráfico → principais posições → o que precisa de atenção → distribuição e mercado.

**Movimento** (150–300 ms, desligado com `prefers-reduced-motion`): botões encolhem ao toque, abas e páginas entram com *fade*, linhas respondem ao toque.

## Testes

| Teste | Resultado |
|---|---|
| E2E Playwright, desktop e celular emulado | 41 aprovados, 3 pulados por desenho |
| Vitest / ESLint / `tsc` / `next build` | 28 aprovados / sem problemas |
| Transbordo horizontal: 11 páginas × 8 larguras (320–1440px) | nenhum |
| Vidro aplicado: estilo calculado da barra de abas | `blur(24px) saturate(1.6)` |

**Limitações**
- **Navegador:** Chromium emulado. Não houve aparelho físico nem Safari/iOS, onde o `backdrop-filter` e a *safe area* precisam de verificação real.
- **Media query `prefers-reduced-transparency`:** o Safari ainda não a suporta. Lá o fallback de transparência depende só de "mais contraste".
