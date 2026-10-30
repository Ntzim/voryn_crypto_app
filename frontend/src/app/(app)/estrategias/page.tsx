import { Suspense } from "react";

import { BacktestView } from "@/components/strategies/backtest-view";

export const metadata = { title: "Estratégias" };

export default function EstrategiasPage() {
  // The open backtest lives in the URL (?run=…), which is request-time data.
  return (
    <Suspense>
      <BacktestView />
    </Suspense>
  );
}
