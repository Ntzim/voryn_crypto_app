import { Lock, Plug } from "lucide-react";

import { EmptyState } from "@/components/common/states";

import { SettingsSection } from "./section";

export function IntegrationsSection() {
  return (
    <SettingsSection
      title="Exchanges"
      description="Sincronize automaticamente saldos e operações da Binance, Coinbase, Kraken e outras."
    >
      <EmptyState
        icon={Plug}
        title="Integrações em breve"
        description={
          <span className="inline-flex flex-col items-center gap-2">
            Até lá, o registro manual e a importação CSV cobrirão sua carteira.
            <span className="inline-flex items-center gap-1.5 text-xs text-subtle-foreground">
              <Lock className="size-3.5" /> Somente chaves de leitura, cifradas. Nunca pediremos permissão de saque.
            </span>
          </span>
        }
        className="items-start px-0 text-left sm:items-center sm:text-center"
      />
    </SettingsSection>
  );
}
