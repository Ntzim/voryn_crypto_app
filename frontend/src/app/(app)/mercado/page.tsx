import { Suspense } from "react";

import { MarketView } from "@/components/market/market-view";

export const metadata = { title: "Mercado" };

export default function MercadoPage() {
  // MarketView reads URL search params, which are only known at request time.
  return (
    <Suspense>
      <MarketView />
    </Suspense>
  );
}
