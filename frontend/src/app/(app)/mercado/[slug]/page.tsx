import { Suspense } from "react";

import { AssetView } from "@/components/market/asset-view";

async function AssetPageContent({ params }: { params: PageProps<"/mercado/[slug]">["params"] }) {
  const { slug } = await params;
  return <AssetView slug={slug} />;
}

export default function AssetPage({ params }: PageProps<"/mercado/[slug]">) {
  return (
    <Suspense>
      <AssetPageContent params={params} />
    </Suspense>
  );
}
