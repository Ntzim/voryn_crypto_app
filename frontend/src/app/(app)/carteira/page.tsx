import { Suspense } from "react";

import { PageSkeleton } from "@/components/common/page-skeleton";
import { PortfolioView } from "@/components/portfolio/portfolio-view";

export const metadata = { title: "Minha Carteira" };

export default function CarteiraPage() {
  return (
    <Suspense fallback={<PageSkeleton variant="dashboard" label="sua carteira" />}>
      <PortfolioView />
    </Suspense>
  );
}
