# Risco da carteira — metodologia

A página **Risco** mostra como a carteira **de hoje** teria se comportado no histórico recente. Ela descreve exposição, não prevê o futuro. Código: `backend/app/modules/risk/`.

## Dados

- Candles diários **fechados** da Binance (par USDT, horário UTC), os mesmos da análise técnica. Período de 90, 180 ou 365 dias.
- Stablecoins (por símbolo ou comportamento: preço a 2% de US$ 1 e volatilidade anual abaixo de 5%) valem US$ 1 constante.
- Ativos sem candles (sem par USDT na Binance, ou com mercado de referência divergente) ficam **fora** das métricas. A página mostra a cobertura e lista esses ativos.
- Mínimo de 30 retornos diários em comum entre os ativos. Abaixo disso, as métricas não são exibidas.

## Duas séries, dois usos

| Série | Como é feita | Usada em |
|---|---|---|
| Retornos com pesos constantes | Σ peso atual × retorno diário do ativo | volatilidade, VaR, expected shortfall, beta, contribuição ao risco |
| Valor das quantidades atuais | Σ quantidade atual × fechamento do dia | drawdown, piores janelas de 1, 7 e 30 dias |

Com pesos constantes, as contribuições ao risco somam 100% (decomposição de Euler). Drawdown e janelas dependem do caminho dos preços, por isso usam a série de valor.

## Métricas

| Métrica | Fórmula |
|---|---|
| Volatilidade anualizada | desvio-padrão amostral (n − 1) dos retornos diários × √365 |
| VaR histórico 1 dia (95%, 99%) | perda do percentil empírico, sem interpolação: k-ésimo pior retorno, k = ⌈(1 − c)·n⌉ |
| Expected shortfall 95% | perda média nos dias iguais ou piores que o VaR 95% |
| Beta ao BTC | cov(ativo, BTC) ÷ var(BTC), nos dias em comum |
| Contribuição ao risco | peso × cov(ativo, carteira) ÷ var(carteira) |
| Drawdown máximo | menor valor ÷ maior valor anterior − 1 |
| Concentração | HHI = Σ peso²; ativos efetivos = 1 ÷ HHI; maior peso; três maiores |
| Correlação | Pearson dos retornos diários, até 8 maiores ativos (sem stablecoins) |
| Liquidez | valor da posição ÷ volume médio diário de 30 dias no par USDT da Binance. Alta ≤ 1%, média ≤ 10%, baixa acima disso |

Valores monetários aplicam o percentual ao valor de mercado coberto de hoje, na moeda do usuário.

## Pontos de atenção (regras)

| Regra | Limiar |
|---|---|
| Volatilidade elevada | atenção ≥ 50% a.a.; risco ≥ 80% |
| Carteira abaixo do pico | valor atual ≤ −20% do pico do período |
| Diversificação efetiva baixa | menos de 3 ativos efetivos |
| Liquidez limitada | posição > 1% do volume diário (atenção); > 10% (risco) |
| Ativos muito correlacionados | ρ ≥ 0,80 entre ativos com peso ≥ 10% |
| Cobertura | algum ativo sem histórico |
| Stablecoins | ≥ 1% da carteira (risco de emissor não modelado) |

## Simulador de cenários

Variação do Bitcoin (−100% a +1000%) aplicada a cada ativo pelo seu beta ao BTC no período. Stablecoins ficam estáveis. Ativos sem beta recebem a mesma variação do BTC, e a nota avisa. Ajustes manuais por ativo substituem o valor propagado. Nenhum preço cai abaixo de zero. É uma conta mecânica sobre as posições atuais, não uma previsão, e nada é gravado.

## Limitações

- O passado recente não representa todos os regimes de mercado. O VaR histórico não enxerga eventos ausentes da janela.
- Volume de uma única corretora subestima a liquidez global.
- A perda de paridade de stablecoins não é modelada.
