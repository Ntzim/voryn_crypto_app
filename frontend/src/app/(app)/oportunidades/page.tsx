import { Suspense } from "react";

import { OpportunitiesView } from "@/components/signals/opportunities-view";

export const metadata = { title: "Oportunidades" };

export default function OportunidadesPage() {
  return (
    <Suspense>
      <OpportunitiesView />
    </Suspense>
  );
}
