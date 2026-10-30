# Backtesting — metodologia

Código: `backend/app/modules/backtesting/` (motor `bt-1`). Os testes provam as regras abaixo, inclusive que nenhuma decisão muda quando os candles futuros são removidos.

## Regras de simulação

1. **Sem look-ahead.** A decisão do candle *t* usa apenas os candles fechados até *t*. Indicadores pré-calculados (EMA, RSI, MACD) são causais: o valor em *t* não depende de nada depois de *t*. A estratégia `voryn-core` recalcula a análise completa sobre a janela que termina em *t*.
2. **Execução no próximo candle.** Toda ordem é executada na **abertura de t + 1**, nunca no fechamento que gerou o sinal.
3. **Custos.** Cada execução paga slippage (preço pior: compra × (1 + s), venda × (1 − s)) e taxa sobre o valor negociado. Os padrões são 0,10% de taxa e 0,05% de slippage, configuráveis até 1%.
4. **Posição.** 100% comprado ou 100% fora, sem alavancagem nem venda a descoberto. O capital parado não rende. Capital inicial: 10.000 USDT.
5. **Aquecimento.** As decisões começam depois do maior período de aquecimento entre as variantes testadas, para que todas cubram o mesmo período.

## Treino e validação

- O histórico útil (até 1.000 candles da Binance, 1d ou 4h) é dividido em treino (50% a 90%, padrão 70%) e validação. Cada parte precisa de pelo menos 60 candles.
- **Otimização** (opcional) testa uma grade fixa de parâmetros **apenas no treino** e escolhe o maior Sharpe (desempate pelo retorno). A validação roda **uma única vez**, com os parâmetros escolhidos, a partir de posição zerada e capital novo.
- Os dois períodos são sempre comparados a **comprar e manter** no mesmo intervalo e com os mesmos custos. Uma grande queda entre treino e validação indica sobreajuste.

## Estratégias

| Estratégia | Regra | Grade de otimização |
|---|---|---|
| Sinais Voryn (`voryn-core`) | compra em "potencial de compra", vende em "potencial de venda", mantém nos demais | — (pesos versionados da estratégia ativa) |
| Cruzamento de EMAs | comprado enquanto EMA rápida > lenta | rápida 9/12/20 × lenta 26/50/100 |
| MACD | comprado enquanto o histograma é positivo | rápida 8/12 × lenta 21/26/35, sinal 9 |
| Reversão por RSI(14) | compra abaixo do limiar inferior, vende acima do superior | 25/30/35 × 65/70/75 |
| Comprar e manter | referência | — |

A amplitude de mercado não é guardada historicamente. Por isso, no backtest, o componente de mercado do `voryn-core` usa só a tendência do Bitcoin no mesmo candle.

## Métricas

Retorno total, retorno anualizado (para períodos de 30 dias ou mais), drawdown máximo, volatilidade e Sharpe anualizados (sem taxa livre de risco; 365 períodos por ano no diário, 2.190 no 4h), número de operações, taxa de acerto, resultado médio por operação, profit factor (lucro bruto ÷ prejuízo bruto das operações fechadas), tempo comprado e taxas pagas.

## Execução

`POST /api/v1/backtests` cria a execução (status `queued`), e o worker processa a fila (`backtests.run`). A página consulta o status até ele virar `done` ou `failed`. Execuções paradas por mais de 15 minutos são marcadas como falhas. Limites: 10 execuções por hora por usuário; as 30 mais recentes ficam guardadas.

## Limitações

Uma única corretora e um único par por teste; sem livro de ofertas (o slippage é um percentual fixo); sem custo de financiamento nem impostos. **Resultados passados não garantem resultados futuros.**
