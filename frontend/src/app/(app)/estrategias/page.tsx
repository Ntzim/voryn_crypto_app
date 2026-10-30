import { Suspense } from "react";

import { PageSkeleton } from "@/components/common/page-skeleton";
import { BacktestView } from "@/components/strategies/backtest-view";

export const metadata = { title: "Estratégias" };

export default function EstrategiasPage() {
  // The open backtest lives in the URL (?run=…), which is request-time data.
  return (
    <Suspense fallback={<PageSkeleton variant="panel" label="as estratégias" />}>
      <BacktestView />
    </Suspense>
  );
}
