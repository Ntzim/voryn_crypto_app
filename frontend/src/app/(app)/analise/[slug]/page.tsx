import { Suspense } from "react";

import { PageSkeleton } from "@/components/common/page-skeleton";
import { AnalysisView } from "@/components/analysis/analysis-view";

async function Content({ params }: { params: PageProps<"/analise/[slug]">["params"] }) {
  const { slug } = await params;
  return <AnalysisView slug={slug} />;
}

export default function AnalysisPage({ params }: PageProps<"/analise/[slug]">) {
  return (
    <Suspense fallback={<PageSkeleton variant="detail" label="a análise" />}>
      <Content params={params} />
    </Suspense>
  );
}
