import { FlaskConical } from "lucide-react";

import { ComingSoon } from "@/components/common/coming-soon";

export const metadata = { title: "Estratégias" };

export default function EstrategiasPage() {
  return (
    <ComingSoon
      icon={FlaskConical}
      title="Estratégias"
      description="Backtesting de estratégias com dados históricos e custos realistas."
      features={[
        "Estratégias com RSI, cruzamento de médias, MACD e regras combinadas",
        "Retorno, drawdown, taxa de acerto, profit factor e Sharpe",
        "Taxas, slippage e liquidez considerados",
        "Comparação com buy and hold",
        "Separação temporal entre desenvolvimento e validação",
        "Sem look-ahead bias: só dados disponíveis em cada decisão",
      ]}
      note="Resultados históricos não garantem desempenho futuro."
    />
  );
}
