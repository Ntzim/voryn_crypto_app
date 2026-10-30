# Oportunidades e alertas — metodologia

> Os sinais são **analíticos**: gerados por regras quantitativas fixas a partir de dados históricos. O score mede quantas condições favoráveis estão alinhadas. **Não é probabilidade de lucro e não é recomendação de investimento.**

## Estratégia

A configuração fica na tabela `signal_strategies`, com chave, versão, pesos e limiares. A estratégia vigente é `voryn-core` v1:

| Componente | Peso | Regra (0 a 100; 50 = neutro) |
|---|---|---|
| Tendência | 25% | 50 + 50 × saldo da classificação de tendência ÷ critérios disponíveis ([TECHNICAL_ANALYSIS.md](TECHNICAL_ANALYSIS.md)) |
| Momentum | 20% | média de dois subscores: (1) MACD: cruzamento positivo recente 80, negativo 20, histograma positivo 65, negativo 35; (2) RSI: ≥ 70 → 25 (sobrecompra), ≤ 30 → 70 (sobrevenda), 55–70 → 62, 30–45 → 40, 45–55 → 50 |
| Volume | 15% | ≥ 1,5× a média: 75 em candle de alta, 25 em candle de baixa; entre 1× e 1,5×: 58 ou 42; < 0,7×: 45; demais casos: 50 |
| Volatilidade | 15% | 80 − 0,6 × percentil da largura de Bollinger nos últimos 100 candles. Volatilidade relativa menor significa risco menor e pontuação maior |
| Suportes/resistências | 15% | 30 + 50 × espaço até a resistência ÷ (espaço até o suporte + espaço até a resistência) |
| Condições de mercado | 10% | média de: % dos ativos acompanhados em alta em 24 h; tendência do Bitcoin no mesmo intervalo (alta 70, baixa 30, demais 50) |

**Score** = Σ peso × subscore, com uma casa decimal. Os pesos são normalizados, de modo que somam 100%.

## Classificação

| Ordem | Condição | Classificação |
|---|---|---|
| 1 | dados desatualizados | **Atenção**. Nunca compra ou venda; a justificativa começa com "Dados desatualizados — sinal suspenso" |
| 2 | score ≥ 65 e tendência diferente de baixa | **Potencial de compra** |
| 3 | score ≤ 35, ou tendência de baixa com score ≤ 45 | **Potencial de venda** |
| 4 | evidência contraditória: diferença ≥ 40 entre os subscores de tendência e momentum, RSI ≥ 75 ou ≤ 25, ou volatilidade ≤ 30 | **Atenção** |
| 5 | demais casos | **Neutro** |

Cada sinal traz:
- **Justificativa**: frase da classificação mais os três componentes que mais pesaram no resultado (peso × distância de 50).
- **Riscos**: proximidade de resistência (< 3%), RSI em extremo, volatilidade elevada, tendência de baixa, mercado desfavorável e dados desatualizados.
- **Condições de invalidação**:
  - compra: fechamento abaixo do suporte mais próximo ou perda da EMA 50;
  - venda: fechamento acima da resistência ou recuperação da EMA 50.

## Registro e auditoria

- Um sinal por (ativo, intervalo, versão da estratégia, **candle fechado**), garantido por restrição única. Reprocessar o mesmo candle não altera nada, e o histórico mostra exatamente o que a estratégia dizia em cada momento.
- **Campos gravados**:
  - data e hora;
  - ativo e intervalo;
  - preço de referência;
  - score e componentes, com subscore, peso e explicação;
  - todos os indicadores usados (snapshot completo);
  - tendência, justificativa, riscos e condições de invalidação;
  - fonte dos dados, horário da coleta e se estavam desatualizados;
  - versão da estratégia e da metodologia técnica.
- **Universo**: os 50 maiores ativos por capitalização mais todo ativo em carteira, watchlist ou alerta. Intervalos 1d e 4h, gerados a cada 30 minutos pelo worker. Ativos fora desse universo recebem o sinal sob demanda, ao abrir sua análise.
- **Stablecoins não recebem sinais.** São identificadas pela lista de símbolos conhecidos **e** por comportamento: preço a até 2% de US$ 1 e volatilidade anualizada abaixo de 5%.
- Um sinal com mais de 3 candles de idade sai da listagem, porque já não descreve o mercado.

## Alertas

| Tipo | Condição | Dados usados |
|---|---|---|
| Preço acima / abaixo | cotação cruza o alvo (USD ou BRL) | ticker ao vivo; ignorado se tiver mais de 30 min |
| RSI acima / abaixo | RSI(14) do candle fechado cruza o nível | candles do intervalo escolhido |
| Cruzamento de médias | EMA rápida cruza a lenta (9/21/50/200), com direção opcional | idem |
| Volume elevado | volume do candle fechado ≥ N× a média de 20 | idem; dispara uma vez por candle |
| Mudança de tendência | classificação muda (destino opcional) | idem |
| Mudança no sinal | classificação do sinal muda (destino opcional) | sinais gravados (1d/4h) |
| Concentração | peso de um ativo (ou do maior) ≥ limite | carteira do usuário |

- **Disparo por cruzamento**: o alerta dispara quando a condição *passa* a ser verdadeira, não enquanto ela continua verdadeira. A primeira avaliação só registra a linha de base, então criar um alerta já satisfeito não gera aviso imediato.
- **Controle de repetição e volume**:
  - cooldown por alerta, de 15 min a 1 semana;
  - chave única de deduplicação por ocorrência, que impede duplicatas mesmo com execuções concorrentes;
  - no máximo 30 notificações e 10 e-mails por usuário por hora.
- **Dados desatualizados nunca disparam alertas.**
- **Canais**: notificação no aplicativo (sino) e e-mail. Novos canais (push, Telegram, app móvel) implementam a interface `Channel` em `app/modules/alerts/channels.py`.
- **Retenção**: notificações lidas por 90 dias; qualquer notificação por no máximo 180 dias.
