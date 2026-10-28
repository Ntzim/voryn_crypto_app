import { Suspense } from "react";

import { SettingsView } from "@/components/settings/settings-view";

export const metadata = { title: "Configurações" };

export default function SettingsPage() {
  return (
    <Suspense>
      <SettingsView />
    </Suspense>
  );
}
