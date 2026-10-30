# Análise técnica — metodologia (versão `ta-1.0`)

Os indicadores são calculados por código determinístico e testado (`backend/app/modules/technical_analysis/`), sobre dados históricos validados. **Nenhum indicador é produzido por IA generativa.** Toda resposta da API informa a versão da metodologia (`methodology_version`). Ela muda sempre que muda uma fórmula, um parâmetro ou uma regra, para que sinais futuros (Fase 4) sejam auditáveis.

## Dados

| Item | Decisão |
|---|---|
| Fonte de candles | Binance, dados públicos via `data-api.binance.vision` (sem chave, sem restrição geográfica) |
| Par | `ATIVO/USDT`. O USDT é usado como referência de dólar; a diferença USDT↔USD costuma ser < 0,5% |
| Intervalos | 15m, 1h, 4h, 1d, 1w — 500 candles por consulta |
| Validação do par | O mapeamento por símbolo só é aceito se o último fechamento estiver a até 5% do preço da CoinGecko. Isso evita exibir um token homônimo; o resultado é guardado em cache por 24 h |
| Validação dos candles | São descartados candles com preço ≤ 0, máxima < máx(abertura, fechamento), mínima > mín(abertura, fechamento), volume negativo ou ordem temporal quebrada |
| Persistência | Só candles **fechados** vão para `historical_candles` (imutáveis); o candle em formação aparece apenas no gráfico |
| Cache | Redis por ativo e intervalo (60 s no 15m até 30 min no 1w) |
| Indisponibilidade | Se a Binance falha, servimos os candles armazenados com `is_stale = true` |
| Retenção | 15m: 60 dias · 1h: 1 ano · 4h, 1d e 1w: indefinida |

## Indicadores

Todos são calculados **somente sobre candles fechados**. Assim, o valor de um candle não "repinta" depois do fechamento.

| Indicador | Definição |
|---|---|
| SMA(n) | média aritmética dos últimos n fechamentos |
| EMA(n) | α = 2/(n+1), semente = SMA dos n primeiros (convenção TA-Lib). Períodos: 9, 21, 50, 200 |
| RSI(14) | método de Wilder: médias iniciais simples dos 14 primeiros ganhos e perdas, depois suavização (média × 13 + atual) / 14. Sobrecompra ≥ 70, sobrevenda ≤ 30 |
| MACD(12, 26, 9) | EMA12 − EMA26; sinal = EMA9 do MACD; histograma = MACD − sinal. Cruzamento = troca de sinal do histograma nos últimos 3 candles |
| Bollinger(20, 2) | SMA20 ± 2 × desvio-padrão populacional. %B = (preço − banda inferior) / (superior − inferior); largura = (superior − inferior) / SMA20 |
| ATR(14) | média de Wilder do *true range*, com semente igual à média simples dos 14 primeiros |
| Volume | volume do último candle ÷ SMA20 do volume; ≥ 1,5× é destacado |
| Volatilidade | desvio-padrão amostral dos retornos logarítmicos dos últimos 30 candles × √(períodos por ano). Mercado 24/7: 15m = 35.040, 1h = 8.760, 4h = 2.190, 1d = 365, 1w = 52 |

**Validação.** O RSI reproduz os 19 valores do exemplo de referência de Wilder publicado pela StockCharts (planilha `cs-rsi`, tolerância de 0,01). A EMA reproduz o exemplo de 10 períodos da mesma fonte. Bollinger, MACD, ATR e volatilidade são testados contra propriedades matemáticas exatas. Exemplo: numa série linear, o MACD é exatamente 7.

## Suportes e resistências

1. **Pivôs**: um candle é topo (fundo) se sua máxima (mínima) é estritamente maior (menor) que a dos 3 candles de cada lado.
2. **Agrupamento**: pivôs a menos de máx(0,5 × ATR, 0,15% do preço) entre si formam uma zona; o nível da zona é a média dos preços agrupados.
3. **Força**: número de toques. A data do último toque também é informada.
4. **Seleção**: as 3 zonas mais próximas abaixo do preço (suportes) e acima (resistências), com preferência para zonas com ao menos 2 toques.

Níveis descrevem onde o preço reagiu no passado. Não garantem reação futura.

## Classificação de tendência

Seis critérios votam: +1 alta, −1 baixa, 0 neutro ou indisponível.

| # | Critério | Alta | Baixa |
|---|---|---|---|
| 1 | Preço × EMA 200 | acima | abaixo |
| 2 | Preço × EMA 50 | acima | abaixo |
| 3 | EMA 21 × EMA 50 | acima | abaixo |
| 4 | Inclinação da EMA 50 em 10 candles | > ATR%/2 | < −ATR%/2 |
| 5 | MACD | > sinal e > 0 | < sinal e < 0 |
| 6 | RSI | > 55 | < 45 |

| Classificação | Regra |
|---|---|
| Tendência de alta | saldo ≥ +3, preço acima da EMA 50 e EMA 50 não descendente |
| Tendência de baixa | saldo ≤ −3, preço abaixo da EMA 50 e EMA 50 não ascendente |
| Consolidação | EMA 50 lateral, largura de Bollinger no percentil ≤ 40 dos últimos 100 candles e \|saldo\| ≤ 2 |
| Indefinida | sinais mistos, ou menos de 60 candles fechados |

**Confiança** = \|saldo\| ÷ critérios disponíveis: alta a partir de 0,8, moderada a partir de 0,5, baixa abaixo disso. Toda classificação acompanha a lista de critérios com o resultado de cada um.

## Limitações

- Ativos sem par contra USDT na Binance, ou cujo par diverge do preço de referência, ficam sem gráfico. A interface explica o motivo.
- Volume é o volume da Binance no par USDT, não o volume global do ativo.
- Notícias e eventos relevantes (seção 7 da especificação) ficam para uma integração futura com provedor licenciado.
- A tabela `technical_indicators` não foi criada: os indicadores são recalculados a cada consulta (milissegundos para 500 candles). A Fase 4 vai persistir os indicadores usados em cada sinal (`analysis_signals`).
