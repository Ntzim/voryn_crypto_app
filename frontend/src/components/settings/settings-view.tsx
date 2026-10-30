"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/common/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { IntegrationsSection } from "./integrations-section";
import { PreferencesSection } from "./preferences-section";
import { ProfileSection } from "./profile-section";
import { SecuritySection } from "./security-section";

const TABS = [
  { value: "perfil", label: "Perfil" },
  { value: "seguranca", label: "Segurança" },
  { value: "preferencias", label: "Preferências" },
  { value: "integracoes", label: "Integrações" },
] as const;

type TabValue = (typeof TABS)[number]["value"];

export function SettingsView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const requested = params.get("aba");
  const tab: TabValue = TABS.some((t) => t.value === requested) ? (requested as TabValue) : "perfil";

  return (
    <>
      <PageHeader title="Configurações" description="Perfil, segurança da conta e preferências de exibição." />
      <Tabs
        value={tab}
        onValueChange={(value) => router.replace(value === "perfil" ? pathname : `${pathname}?aba=${value}`, { scroll: false })}
      >
        <TabsList className="mb-6 w-full justify-start overflow-x-auto sm:w-auto">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="perfil">
          <ProfileSection />
        </TabsContent>
        <TabsContent value="seguranca">
          <SecuritySection />
        </TabsContent>
        <TabsContent value="preferencias">
          <PreferencesSection />
        </TabsContent>
        <TabsContent value="integracoes">
          <IntegrationsSection />
        </TabsContent>
      </Tabs>
    </>
  );
}
