import { Suspense } from "react";

import { AnalysisView } from "@/components/analysis/analysis-view";

async function Content({ params }: { params: PageProps<"/analise/[slug]">["params"] }) {
  const { slug } = await params;
  return <AnalysisView slug={slug} />;
}

export default function AnalysisPage({ params }: PageProps<"/analise/[slug]">) {
  return (
    <Suspense>
      <Content params={params} />
    </Suspense>
  );
}
