import { Wallet } from "lucide-react";

import { ComingSoon } from "@/components/common/coming-soon";

export const metadata = { title: "Minha Carteira" };

export default function CarteiraPage() {
  return (
    <ComingSoon
      icon={Wallet}
      title="Minha Carteira"
      description="Posições, transações e rentabilidade da sua carteira."
      features={[
        "Registro de compras, vendas, depósitos, retiradas, transferências, taxas e conversões",
        "Importação de extratos em CSV com pré-visualização e deduplicação",
        "Preço médio, resultado realizado e não realizado por ativo",
        "Rentabilidade por período com metodologia TWR e XIRR",
        "Transferências entre carteiras próprias sem distorcer aportes ou lucro",
        "Histórico patrimonial diário",
      ]}
      note="Os cálculos serão feitos no servidor com precisão decimal e testados contra casos de referência."
    />
  );
}
