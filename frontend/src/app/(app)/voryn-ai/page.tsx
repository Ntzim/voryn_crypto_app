import { Sparkles } from "lucide-react";

import { ComingSoon } from "@/components/common/coming-soon";

export const metadata = { title: "Voryn AI" };

export default function VorynAiPage() {
  return (
    <ComingSoon
      icon={Sparkles}
      title="Voryn AI"
      description="Assistente que explica sua carteira e o mercado a partir dos dados da plataforma."
      features={[
        "Perguntas em linguagem natural sobre carteira, ativos e riscos",
        "Respostas que separam dados observados, interpretações, hipóteses e riscos",
        "Período analisado e horário dos dados em toda resposta",
        "Usa apenas resultados calculados pelos motores internos",
        "Informa quando não há dados suficientes",
        "Sem execução de ordens",
      ]}
    />
  );
}
