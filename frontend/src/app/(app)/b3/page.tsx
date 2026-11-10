import { Suspense } from "react";

import { B3View } from "@/components/b3/b3-view";
import { PageSkeleton } from "@/components/common/page-skeleton";

export const metadata = { title: "Bolsa B3" };

export default function B3Page() {
  // B3View reads URL search params, which are only known at request time.
  return (
    <Suspense fallback={<PageSkeleton variant="list" label="a bolsa" />}>
      <B3View />
    </Suspense>
  );
}
