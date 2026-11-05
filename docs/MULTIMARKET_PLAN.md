`# Voryn multimercado — plano técnico, provedores e custos
`
`**Status:** proposta para decisão (31/10/2026). Nada foi implementado. Este documento existe porque a missão pede o plano, os provedores, os custos e as dependências **antes** de integrações pagas e mudanças estruturais de alto risco.
`
`## Resumo para decisão
`
`1. **O sistema atual é uma boa base.** Candles, análise técnica, motor de sinais (com pesos versionados), qualidade de dados, backtesting, carteira com BRL/USD e câmbio PTAX, alertas e watchlists funcionam sobre "um ativo com candles", não sobre "cripto". O que amarra tudo a cripto é o cadastro de ativos: a tabela `cryptocurrencies` e as 10 chaves estrangeiras que apontam para ela.
`2. **O maior obstáculo é a licença de dados, não o código.** Exibir cotações de ações para usuários de um produto comercial exige licença de exibição/redistribuição. Os planos baratos ou gratuitos de quase todos os provedores proíbem esse uso.
`3. **Caminho recomendado:** construir a fundação sem custo agora; ligar a B3 primeiro (provedor brasileiro barato, com ressalva jurídica) e os EUA quando houver licença comercial contratada. Cada mercado fica atrás de uma chave de configuração e só aparece em produção quando licenciado.
`
`## 1. Diagnóstico do que existe
`
`| Área | Situação | Reaproveitamento |
`|---|---|---|
`| Cadastro de ativos | `cryptocurrencies` (símbolo, nome, imagem, ranking), chave da CoinGecko | **Generalizar** (seção 2) |
`| Cotações | `market_tickers` (atual), `market_prices` (intradiário), com `fetched_at` e detecção de defasagem | Reaproveitar e acrescentar atraso declarado e estado do pregão |
`| Histórico | `historical_candles` (OHLCV por timeframe), `daily_prices` (fechamento diário em USD) | Reaproveitar; ações precisam de preço ajustado por proventos |
`| Provedores | interfaces `MarketDataProvider`, `CandleProvider`, `FxHistoryProvider`; implementações CoinGecko, Binance e BCB | Mesmo padrão para novos provedores |
`| Câmbio | PTAX do Banco Central (oficial, gratuito), histórico por data | Pronto para a consolidação multimoeda |
`| Análise técnica | RSI, MACD, MMEs, Bollinger, ATR, suportes e resistências, tendência, volatilidade | Serve para ações sem mudança de cálculo |
`| Sinais | 6 componentes ponderados, estratégia versionada, qualidade de dados, rastreabilidade | Base do **Voryn Score**; faltam fundamentos e valuation |
`| Carteira | preço médio ponderado, resultado realizado e não realizado, TWR e XIRR, BRL/USD com câmbio na data | Faltam **proventos** e **desdobramentos** como eventos |
`| Alertas e watchlists | por ativo, com cooldown e deduplicação | Funcionam assim que o ativo existir |
`| Busca | `/market/search` e `resolve_asset` sobre cripto | Virar busca global, ciente de mercado e bolsa |
`
`**Acoplamento medido:** 10 chaves estrangeiras para `cryptocurrencies` em 6 módulos (mercado, carteira, sinais, alertas, watchlists, backtesting) e 94 referências a `cryptocurrency_id` em 18 arquivos.
`
`## 2. Arquitetura proposta
`
`### Instrumento financeiro
`A tabela `cryptocurrencies` passa a se chamar `instruments`. No PostgreSQL, renomear tabela e colunas é uma operação só de metadados: instantânea, sem cópia, e as chaves estrangeiras acompanham. Colunas novas:
`
`| Coluna | Valores | Cripto (preenchido na migration) |
`|---|---|---|
`| `market` | `CRYPTO`, `B3`, `US` | `CRYPTO` |
`| `asset_type` | `CRYPTO`, `STOCK`, `ETF`, `FII`, `BDR`, `REIT` | `CRYPTO` |
`| `exchange` | código MIC: `BVMF` (B3), `XNYS`, `XNAS`, `ARCX`… | nulo |
`| `currency` | moeda de negociação: `BRL`, `USD` | `USD` (referência atual) |
`| `isin`, `sector` | quando disponíveis | nulos |
`
`A unicidade passa a ser por `(market, symbol)`. Assim, ativos com o mesmo ticker em bolsas diferentes nunca se confundem.
`
`Em vez de criar uma interface paralela, a `FinancialAsset` da missão vira essa tabela.
`
`**Migration em duas etapas, ambas aditivas e reversíveis:**
`1. Colunas novas com valor padrão.
`2. Renomeações, com o código atualizado no mesmo commit e a suíte completa (209 testes) como rede de segurança.
`
`### Provedores
`Um registro de provedores por mercado (`quotes`, `history`, `fundamentals`, `dividends`), com:
`- **Retry e tolerância:** tentativa com espera crescente e circuit breaker (padrões que já existem no conector da Binance).
`- **Custo:** limite de consumo por provedor no Redis, com contador mensal para não estourar o plano.
`- **Desempenho:** cache das cotações e processamento em lote, sem chamada por componente renderizado.
`- **Fallback:** troca entre provedores só quando a licença permitir.
`
`### Atraso e pregão — nunca apresentar cotação atrasada como tempo real
`- Cada cotação guarda o atraso declarado pelo provedor (`delay_seconds`) e o momento a que o preço se refere.
`- A interface mostra sempre "atraso de 15 min", "fechamento de 30/10" ou "mercado fechado".
`- O calendário de pregão da B3 e da NYSE/Nasdaq (feriados e horários) vem da biblioteca `exchange-calendars`, open source (Apache 2.0), sem custo recorrente.
`
`### Análise e Voryn Score
`- **Componentes:** o motor atual ganha "Fundamentos" e "Valuation" (só para ações, FIIs e REITs). Os pesos ficam na tabela de estratégias, que já é versionada, um conjunto por tipo de ativo.
`- **Classificação:** os nomes atuais (potencial de compra, atenção, neutro, potencial de venda) passam a ser exibidos como "Oportunidade potencial / Atenção ao risco / Neutro / Acompanhar", com a mesma metodologia explicável.
`- **Ressalvas:** a verificação de qualidade de dados continua valendo, e indicador indisponível aparece como "—", nunca como zero.
`
`### Carteira multimercado
`- **Já existe:** a moeda da transação (BRL/USD) e o câmbio na data.
`- **Novos eventos:** `dividend` (provento, com imposto retido) e `split`/`reverse_split` (ajustam quantidade e preço médio sem mudar o custo).
`- **Câmbio:** a rentabilidade é separada em retorno do ativo na moeda original + efeito cambial.
`- **Distribuição:** por mercado (Brasil / EUA / Cripto).
`- **Testes:** são mudanças em cálculo financeiro. Cada uma entra com testes de preço médio, resultado e TWR antes e depois do evento.
`
`## 3. Provedores avaliados
`
`Valores consultados em 31/10/2026, nas páginas oficiais quando possível. **Preços e termos mudam; confirmar por escrito antes de contratar.**
`
`### Brasil (B3)
`
`| Provedor | Custo | Atraso | Cobertura | Licença para exibir no Voryn |
`|---|---|---|---|---|
`| **brapi Pro** | R$ 1.399,90/ano (≈ R$ 117/mês) | 5 min | ações, FIIs, ETFs, BDRs; histórico de mais de 10 anos; fundamentos trimestrais desde 2009; proventos completos | Permite "exibir os dados para os seus usuários" dentro do produto. **Mas a brapi declara que não é distribuidora licenciada da B3**, não tem contrato com a B3 e não oferece SLA |
`| brapi Startup | R$ 1.199,90/ano | 15 min | histórico de 1 ano, fundamentos anuais | mesma ressalva |
`| brapi Gratuito | R$ 0 | 30 min | 15 mil requisições/mês, 3 meses de histórico | só para desenvolvimento |
`| B3 direto (distribuidor licenciado) | taxas fixas da B3 para exibição/distribuição; há modalidade só para dados com 15 min de atraso | ≥ 15 min ou tempo real | oficial | Licenciado. Valores sob consulta à B3 |
`
`### Estados Unidos
`
`| Provedor | Custo | Licença para exibir no Voryn |
`|---|---|---|
`| Massive (ex-Polygon) Stocks Advanced | US$ 199/mês | "Individual use only": **não serve** |
`| Massive Business | US$ 2.499/mês (+ US$ 499 para o pacote de 15 min de atraso) | "Business use"; direito de exibição a confirmar com vendas |
`| Twelve Data Grow/Pro | US$ 79–229/mês | só uso/exibição **interna**: **não serve** |
`| Twelve Data comercial (exibição externa) | sob consulta; fontes de terceiros citam ≈ US$ 499/mês | a confirmar |
`| EODHD comercial | a partir de ≈ €399/mês (o plano interno de US$ 399 proíbe exibição externa) | a página da EODHD afirma que os planos comerciais incluem direitos de redistribuição; cobertura B3 a confirmar |
`| Finnhub, Alpha Vantage | planos pessoais proíbem uso comercial; comercial sob consulta | a confirmar |
`| Financial Modeling Prep | US$ 22–149/mês pessoal; exibição exige "Data Display and Licensing Agreement" | sob contrato |
`
`### Índices (Ibovespa, S&P 500, Nasdaq Composite, Dow Jones)
`Os valores de índices também são licenciados: o Ibovespa pela B3, que tem taxa anual para distribuir índices com 15 min de atraso; o S&P 500 e o Dow Jones pela S&P Dow Jones Indices; o Nasdaq Composite pela Nasdaq.
`
`**Proposta:** até haver licença, mostrar os ETFs que acompanham cada índice (BOVA11, SPY, QQQ, DIA), identificados como ETFs e não como "o índice". Eles chegam pela mesma licença de cotações.
`
`## 4. Recomendação e custos
`
`| Etapa | O que liga | Custo recorrente estimado |
`|---|---|---|
`| Fundação | modelo de instrumentos, provedores, calendários, rótulos de atraso, carteira multimercado, proventos e desdobramentos; desenvolvido e testado com planos gratuitos, sem exibir em produção | **R$ 0** |
`| B3 em produção | brapi Pro (atraso de 5 min) | **≈ R$ 117/mês**, mais um parecer jurídico sobre a necessidade de licença B3 |
`| EUA em produção | licença comercial com exibição (Twelve Data ou EODHD, a cotar) | **≈ US$ 400–500/mês** (≈ R$ 2.200–2.800), a confirmar |
`| Índices oficiais | licenças B3/S&P DJI/Nasdaq | sob consulta; adiável com ETFs como referência |
`
`Custos de infraestrutura no Railway: mais armazenamento de histórico e tarefas do worker. Estimativa baixa (poucos dólares/mês) até alguns milhares de ativos.
`
`## 5. Fases
`
`1. **Fundação (sem custo).**
`   - Migration de instrumentos e registro de provedores.
`   - Adaptador brapi, desenvolvido no plano gratuito.
`   - Calendário de pregão, atraso declarado e busca global com mercado e bolsa.
`   - Chave de configuração por mercado, desligada em produção.
`   - **Testes de regressão de cripto em cada passo.**
`2. **Exploração B3.**
`   - Painel do mercado, lista de ativos e página do ativo (gráfico, dados do dia, 52 semanas, fundamentos com data de referência).
`   - Liga em produção depois da contratação e do parecer jurídico.
`3. **Inteligência.**
`   - Componentes "Fundamentos" e "Valuation"; pesos por tipo de ativo; Voryn Score explicável.
`   - Testes do cálculo com dados reais congelados (fixtures).
`4. **Carteira.**
`   - Ações na carteira, proventos, desdobramentos, efeito cambial e distribuição por mercado.
`   - Calendário de dividendos.
`5. **EUA e experiência avançada.**
`   - Adaptador do provedor licenciado.
`   - Comparador de ativos, alertas novos (variação %, resultados, proventos) e otimizações (paginação e virtualização das listas).
`
`### Andamento
`
`- **Fase 1 — implementada** (branch `feat/multimarket-foundation`, não publicada em produção):
`  - Migration `3b9d2f61c0a4` (aditiva e reversível): `market`, `asset_type`, `exchange`, `currency` e `sector` no catálogo; `delay_seconds` nas cotações; ticker único por mercado.
`  - Todas as consultas de cripto filtram `market = 'CRYPTO'`; watchlists, alertas, backtests e transações recusam ativos de outros mercados.
`  - `MARKETS_ENABLED` (padrão `CRYPTO`); a sincronização e os endpoints de B3 só funcionam com o mercado listado.
`  - Adaptador brapi: catálogo completo com cotação em 3 requisições (~2.270 instrumentos), histórico diário, retry com Retry-After, reparo de acentuação, contador mensal de uso no Redis.
`  - Calendários B3 (BVMF) e EUA (NYSE) com feriados; a hora de referência da cotação é a hora da coleta menos o atraso, limitada ao fechamento do pregão.
`  - Endpoints `GET /market/markets` e `GET /market/instruments/search`.
`  - Não modelado ainda: meio pregão (vésperas de feriado nos EUA, Quarta-feira de Cinzas na B3).
`
`- **Fase 2 — implementada no plano gratuito** (branch `feat/b3-exploration`, B3 desligada em produção):
`  - Telas `/b3` (referência do Ibovespa pelo BOVA11, altas e baixas, mais negociados, lista com busca e filtro por tipo) e `/b3/[código]` (gráfico diário e dados do pregão). A entrada no menu só aparece com o mercado habilitado.
`  - Estado do pregão, atraso e hora dos dados em toda tela com cotação; aviso de que não é recomendação.
`  - Limites do plano gratuito: sem `BRAPI_TOKEN`, detalhe e histórico só funcionam para PETR4, VALE3, ITUB4 e MGLU3; os demais mostram a indisponibilidade, sem valores inventados. O histórico vai até 3 meses.
`  - Consultas sob demanda passam por cache no Redis, inclusive falhas, e param na cota mensal.
`  - Altas, baixas e amplitude só contam ativos com ao menos R$ 1 milhão negociado; o mercado fracionário saiu do catálogo.
`  - Ainda não incluído: fundamentos, ativos da B3 em watchlists e alertas, e recomendações (Fase 3).
`
`- **Fase 3 — parcial, no plano gratuito** (B3 desligada em produção):
`  - Tela \`/oportunidades-b3\` (ações e FIIs) e sinal na página do ativo, sobre o mesmo motor de cripto. Sinais calculados uma vez por pregão fechado para as 40 ações e os 30 FIIs mais negociados; ver uma página não gasta requisições.
`  - **Ações:** só análise técnica. Múltiplos, balanços e dividendos respondem 403 no plano gratuito.
`  - **FIIs:** P/VP sobre o preço atual e rendimentos de 12 meses pesam 55% do score. No plano gratuito esses dados só vieram para HGLG11 e MXRF11; os demais ficam sem score, com compra e venda suspensas. A brapi indica o plano Pro para FIIs.
`  - **Sem validação:** pesos e faixas são decisões de projeto. Com 3 meses de histórico não dá para fazer backtest, e sem EMA 200.
`  - **Antes de produção:** parecer jurídico, incluindo as regras da CVM sobre recomendação de valores mobiliários, e plano pago.
`
`### Uso pessoal (decisão de 2026-11-05)
`
`A instalação em produção é de uso pessoal do dono. Por isso a B3 pode ser ligada sem parecer jurídico **desde que** \`REGISTRATION_OPEN=false\` esteja definido: é o que mantém o uso pessoal, que é a condição do plano gratuito da brapi e a premissa de não haver recomendação a terceiros. Reabrir cadastros ou admitir outras pessoas exige rever esta decisão: plano pago, licença de dados e avaliação das regras da CVM.
`
`Cada fase termina com diagnóstico, implementação, validação e próximos passos, em commits separados.
`
`## 6. Riscos
`
`| Risco | Impacto | Mitigação |
`|---|---|---|
`| Exibir cotações sem licença adequada | jurídico/comercial | só ligar cada mercado com licença contratada e parecer; atraso sempre visível |
`| brapi sem SLA nem contrato | disponibilidade | cache, fallback para último preço marcado como atrasado, monitoramento |
`| Proventos e desdobramentos mudam preço médio e rentabilidade | cálculos financeiros errados | eventos explícitos, testes antes/depois, histórico de preço ajustado separado do não ajustado |
`| Migration de instrumentos | quebra das funções de cripto | migration aditiva e reversível, renomeação com suíte completa |
`| Escala de milhares de ativos | lentidão | sincronização em lote no worker, paginação, índices, cache no Redis |
