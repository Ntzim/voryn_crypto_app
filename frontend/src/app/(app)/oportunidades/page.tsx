import { Radar } from "lucide-react";

import { ComingSoon } from "@/components/common/coming-soon";

export const metadata = { title: "Oportunidades" };

export default function OportunidadesPage() {
  return (
    <ComingSoon
      icon={Radar}
      title="Oportunidades"
      description="Sinais quantitativos transparentes, com justificativa e condições de invalidação."
      features={[
        "Classificação: potencial de compra, neutro, atenção ou potencial de venda",
        "Score de 0 a 100 com pesos configuráveis e versionados",
        "Justificativa, riscos e condições que invalidam cada cenário",
        "Registro de data, timeframe, preço de referência e qualidade dos dados",
        "Histórico de sinais para auditoria",
        "Bloqueio de sinais quando os preços estiverem desatualizados",
      ]}
      note="O score não é uma probabilidade de lucro e os sinais não são recomendações de investimento."
    />
  );
}
