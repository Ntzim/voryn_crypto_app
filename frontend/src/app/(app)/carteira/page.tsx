import { Suspense } from "react";

import { PortfolioView } from "@/components/portfolio/portfolio-view";

export const metadata = { title: "Minha Carteira" };

export default function CarteiraPage() {
  return (
    <Suspense>
      <PortfolioView />
    </Suspense>
  );
}
