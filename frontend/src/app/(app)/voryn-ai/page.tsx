import { Suspense } from "react";

import { PageSkeleton } from "@/components/common/page-skeleton";
import { AssistantView } from "@/components/ai/assistant-view";

export const metadata = { title: "Voryn AI" };

export default function VorynAiPage() {
  // The open conversation lives in the URL (?c=…), which is request-time data.
  return (
    <Suspense fallback={<PageSkeleton variant="panel" label="o Voryn AI" />}>
      <AssistantView />
    </Suspense>
  );
}
