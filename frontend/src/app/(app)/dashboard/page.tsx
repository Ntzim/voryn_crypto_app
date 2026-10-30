import { Suspense } from "react";

import { DashboardView } from "@/components/dashboard/dashboard-view";

export const metadata = { title: "Dashboard" };

export default function DashboardPage() {
  // The greeting shows today's date, which must be computed per request, not at build time.
  return (
    <Suspense>
      <DashboardView />
    </Suspense>
  );
}
