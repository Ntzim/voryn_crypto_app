import { Suspense } from "react";

import { AssistantView } from "@/components/ai/assistant-view";

export const metadata = { title: "Voryn AI" };

export default function VorynAiPage() {
  // The open conversation lives in the URL (?c=…), which is request-time data.
  return (
    <Suspense>
      <AssistantView />
    </Suspense>
  );
}
