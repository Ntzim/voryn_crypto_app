# Carteira — metodologia de cálculo

Tudo o que a Voryn mostra sobre a carteira é derivado das **transações** (fonte única da verdade) por código determinístico e testado (`backend/app/modules/portfolio/engine.py` e `performance.py`). Nenhum número é gerado por IA.

## Tipos de transação

| Tipo | Efeito no saldo | Custo | Aporte/retirada? | Resultado realizado |
|---|---|---|---|---|
| Compra | + quantidade (− taxa cobrada no ativo) | + valor + taxa | aporte | — |
| Venda | − quantidade | − preço médio × qtd | retirada (valor − taxa) | (valor − taxa) − preço médio × qtd |
| Depósito | + quantidade | + valor informado | aporte | — |
| Retirada | − quantidade | − preço médio × qtd | retirada (valor informado ou custo) | — |
| Transferência | − apenas a taxa de rede | custo da taxa vira despesa | **não** | − custo da taxa |
| Taxa | − quantidade | custo vira despesa | não | − custo |
| Conversão A→B | − A, + B | B recebe o valor líquido de A | **não** | valor de A − custo de A |

- **Custo médio ponderado**: as taxas entram no custo das compras. Vender não altera o preço médio das unidades restantes.
- **Transferências entre contas próprias** não são aporte nem lucro. Assim, mover BTC da exchange para a carteira fria não distorce a rentabilidade.
- O sistema **recusa** operações que deixariam o saldo negativo em qualquer momento do histórico: vender mais do que possui, excluir uma compra da qual uma venda posterior depende, ou mover datas de modo a quebrar o histórico.

## Moedas (BRL e USD)

Cada transação grava a cotação USD/BRL vigente no momento da operação:

- datas passadas usam a **PTAX de venda do Banco Central do Brasil** (oficial);
- operações recentes, antes da publicação da PTAX do dia (por volta das 13h de Brasília), usam a cotação mais recente disponível.

Com isso, custo e resultado são exatos nas duas moedas. Na mesma carteira, o resultado em BRL pode ser positivo e o resultado em USD negativo: a diferença é o efeito cambial. O valor de mercado atual usa os preços ao vivo (em USD) convertidos pela cotação USD/BRL mais recente.

## Variação em 24 horas

Δ patrimônio = **efeito de mercado** + **aportes líquidos** do período.

- O valor de 24h atrás é calculado com as posições daquele momento e os preços daquele momento, deduzidos da variação de 24h informada pelo provedor.
- Percentual (Dietz modificado): efeito de mercado ÷ (valor há 24h + aportes positivos do período).

## Rentabilidade

- **TWR (retorno ponderado pelo tempo)**: retornos diários encadeados, r_d = V_d / (V_{d−1} + F_d) − 1. Considera os aportes do dia como feitos no início do dia e usa fechamentos diários em UTC. Mede o desempenho dos investimentos sem a influência do momento em que o dinheiro entrou ou saiu.
  - Períodos: 24h, 7d, 30d, 90d, 1 ano e desde o início.
  - Um período só é exibido quando a carteira já tem esse histórico completo.
- **XIRR (anualizado, ponderado pelo dinheiro)**: a taxa que zera o valor presente de todos os aportes e retiradas mais o valor atual. Reflete as decisões de timing do investidor.
  - Só é exibido após 30 dias, porque em prazos curtos a anualização produz números enganosos.
- **Comparação com BTC e ETH**: variação acumulada dos fechamentos diários de cada ativo no mesmo período do gráfico.

## Insights

Regras fixas sobre os números calculados. Cada insight informa o método e o limiar usados ("Como é calculado").

| Insight | Regra |
|---|---|
| Concentração | maior ativo ≥ 50% do valor (atenção) / ≥ 80% (risco) |
| Stablecoins | soma do peso de USDT, USDC, DAI e similares ≥ 1% |
| Movimento relevante | variação de 24h ≥ 5% (em módulo) em um ativo da carteira |
| Posições abaixo do preço médio | resultado não realizado ≤ −20% |
| Correlação | Pearson dos retornos diários dos dois maiores ativos em 90 dias ≥ 0,80 (mínimo de 30 observações) |

## Importação CSV

- **Modelo**: botão "Baixar modelo" em Minha Carteira.
- **Colunas**:
  - obrigatórias: `data`, `tipo`, `ativo`, `quantidade`;
  - opcionais: `preco_unitario`, `moeda`, `taxa`, `taxa_no_ativo`, `exchange`, `exchange_destino`, `ativo_destino`, `quantidade_destino`, `observacoes`, `id_externo`;
  - cabeçalhos em inglês também são aceitos.
- **Formatos aceitos**:
  - separador `;` ou `,`;
  - números como `1.234,56` ou `1234.56`;
  - datas ISO 8601 ou `DD/MM/AAAA HH:MM`; sem fuso, valem no fuso do usuário.
- **Ativos**: identificados pelo símbolo (`BTC`) ou pelo identificador (`bitcoin`). Um símbolo ambíguo resolve para o ativo de maior capitalização.
- **Deduplicação**: pelo `id_externo` ou, na falta dele, por uma impressão digital do conteúdo da linha. Reimportar o mesmo arquivo não duplica nada.
- **Pré-visualização**: mostra o erro de cada linha. A importação é atômica: as linhas válidas entram juntas e são validadas contra o histórico completo.

## Limitações conhecidas

- Histórico diário de preços limitado a **365 dias** (plano gratuito da CoinGecko). Carteiras mais antigas mostram o gráfico do último ano, e o TWR "desde o início" fica indisponível. O XIRR continua válido, pois depende só dos fluxos e do valor atual.
- Ativos fora do catálogo (os 100 maiores por capitalização e os que já constam em alguma carteira) ainda não podem ser cadastrados.
- Taxas pagas em um terceiro ativo (por exemplo, taxa da Binance paga em BNB) devem ser registradas como uma transação "Taxa" separada.
- Moedas de cotação suportadas: BRL e USD. Operações contra stablecoins devem ser registradas como **conversão** (por exemplo, USDT → BTC).
- Mapeadores automáticos para os extratos da Binance e da Coinbase ainda não foram implementados; use o modelo da Voryn.
