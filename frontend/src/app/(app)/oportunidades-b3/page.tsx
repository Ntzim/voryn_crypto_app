import { Suspense } from "react";

import { B3OpportunitiesView } from "@/components/b3/b3-opportunities-view";
import { PageSkeleton } from "@/components/common/page-skeleton";

export const metadata = { title: "Oportunidades B3" };

export default function B3OpportunitiesPage() {
  // The view reads URL search params, which are only known at request time.
  return (
    <Suspense fallback={<PageSkeleton variant="list" label="as oportunidades" />}>
      <B3OpportunitiesView />
    </Suspense>
  );
}
