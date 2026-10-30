import { Suspense } from "react";

import { RiskView } from "@/components/risk/risk-view";

export const metadata = { title: "Risco" };

export default function RiskPage() {
  // The analysis window lives in the URL (?janela=…), which is request-time data.
  return (
    <Suspense>
      <RiskView />
    </Suspense>
  );
}
