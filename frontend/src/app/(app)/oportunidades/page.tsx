import { Suspense } from "react";

import { PageSkeleton } from "@/components/common/page-skeleton";
import { OpportunitiesView } from "@/components/signals/opportunities-view";

export const metadata = { title: "Oportunidades" };

export default function OportunidadesPage() {
  return (
    <Suspense fallback={<PageSkeleton variant="list" label="as oportunidades" />}>
      <OpportunitiesView />
    </Suspense>
  );
}
