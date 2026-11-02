import { Suspense } from "react";

import { B3AssetView } from "@/components/b3/b3-asset-view";
import { PageSkeleton } from "@/components/common/page-skeleton";

async function Content({ params }: { params: PageProps<"/b3/[symbol]">["params"] }) {
  const { symbol } = await params;
  return <B3AssetView symbol={symbol.toUpperCase()} />;
}

export default function B3AssetPage({ params }: PageProps<"/b3/[symbol]">) {
  return (
    <Suspense fallback={<PageSkeleton variant="detail" label="o ativo" />}>
      <Content params={params} />
    </Suspense>
  );
}
