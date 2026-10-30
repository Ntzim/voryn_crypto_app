import { Suspense } from "react";

import { PageSkeleton } from "@/components/common/page-skeleton";
import { RiskView } from "@/components/risk/risk-view";

export const metadata = { title: "Risco" };

export default function RiskPage() {
  // The analysis window lives in the URL (?janela=…), which is request-time data.
  return (
    <Suspense fallback={<PageSkeleton variant="panel" label="a análise de risco" />}>
      <RiskView />
    </Suspense>
  );
}
