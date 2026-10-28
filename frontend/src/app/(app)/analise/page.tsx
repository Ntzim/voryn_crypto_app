import { ChartCandlestick } from "lucide-react";

import { ComingSoon } from "@/components/common/coming-soon";

export const metadata = { title: "Análise de Ativos" };

export default function AnalisePage() {
  return (
    <ComingSoon
      icon={ChartCandlestick}
      title="Análise de Ativos"
      description="Gráficos de candles e indicadores técnicos calculados deterministicamente."
      features={[
        "Candles em 15 min, 1 h, 4 h, 1 dia e 1 semana",
        "RSI, MACD, EMAs 9/21/50/200, SMA, Bandas de Bollinger e ATR",
        "Suporte e resistência com metodologia documentada",
        "Classificação de tendência com justificativa baseada em múltiplos indicadores",
        "Volatilidade histórica e mudanças relevantes de volume",
        "Watchlists e favoritos",
      ]}
      note="Indicadores são calculados por código testado a partir de dados históricos validados — nunca por IA generativa."
    />
  );
}
