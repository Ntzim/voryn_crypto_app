import { ShieldHalf } from "lucide-react";

import { ComingSoon } from "@/components/common/coming-soon";

export const metadata = { title: "Risco" };

export default function RiscoPage() {
  return (
    <ComingSoon
      icon={ShieldHalf}
      title="Risco"
      description="Indicadores de risco da carteira e simulação de cenários hipotéticos."
      features={[
        "Volatilidade histórica, drawdown máximo e VaR histórico",
        "Concentração por ativo e por categoria, participação de stablecoins",
        "Correlação entre ativos e liquidez estimada",
        "Score de risco: baixo, moderado, elevado ou muito elevado",
        "Simulador: “e se o Bitcoin cair 20%?”",
      ]}
      note="Métricas históricas não eliminam o risco de perdas extremas; cenários são hipóteses, não previsões."
    />
  );
}
