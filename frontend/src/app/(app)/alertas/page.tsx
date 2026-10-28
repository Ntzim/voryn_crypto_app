import { Bell } from "lucide-react";

import { ComingSoon } from "@/components/common/coming-soon";

export const metadata = { title: "Alertas" };

export default function AlertasPage() {
  return (
    <ComingSoon
      icon={Bell}
      title="Alertas"
      description="Notificações configuráveis de preço, indicadores e carteira."
      features={[
        "Preço acima ou abaixo de um valor",
        "RSI, cruzamento de médias e mudanças de volume",
        "Mudança de tendência e de score de oportunidade",
        "Aumento de concentração na carteira",
        "Notificações no aplicativo e por e-mail",
        "Deduplicação e cooldown para evitar alertas repetitivos",
      ]}
    />
  );
}
