"use client";

import { FileUp, Plus, Wallet } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { EmptyState, ErrorState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Transaction } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { usePerformance, usePortfolio, useSummary } from "@/lib/portfolio-queries";
import { usePreferences } from "@/lib/queries";

import { CsvImportDialog } from "./csv-import-dialog";
import { PositionsTable } from "./positions-table";
import { SummaryCards } from "./summary-cards";
import { TransactionDialog } from "./transaction-dialog";
import { TransactionsList } from "./transactions-list";

export function PortfolioView() {
  const { currency, locale, timeZone } = usePreferences();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const portfolio = usePortfolio();
  const summary = useSummary(portfolio.data?.id, currency);
  const performance = usePerformance(portfolio.data?.id, currency);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const [formOpen, setFormOpen] = useState(params.get("nova") === "1");
  const [importOpen, setImportOpen] = useState(false);
  const tab = params.get("aba") === "transacoes" ? "transacoes" : "posicoes";

  const openNew = () => {
    setEditing(null);
    setFormOpen(true);
  };
  const setTab = (value: string) =>
    router.replace(value === "posicoes" ? pathname : `${pathname}?aba=${value}`, { scroll: false });

  const pid = portfolio.data?.id;
  const s = summary.data;
  const empty = s?.transaction_count === 0;

  return (
    <>
      <PageHeader
        title="Minha Carteira"
        description={s && !empty ? `Valores em ${currency} · atualizado ${formatDateTime(s.as_of, locale, timeZone, { timeStyle: "short" })}` : "Posições, transações e rentabilidade."}
        actions={
          pid && (
            <>
              <Button variant="outline" onClick={() => setImportOpen(true)}>
                <FileUp /> Importar CSV
              </Button>
              <Button onClick={openNew}>
                <Plus /> Nova transação
              </Button>
            </>
          )
        }
      />

      {portfolio.isError || summary.isError ? (
        <Card><ErrorState error={portfolio.error ?? summary.error} onRetry={() => summary.refetch()} /></Card>
      ) : empty ? (
        <Card>
          <EmptyState
            icon={Wallet}
            title="Sua carteira está vazia"
            description="Registre sua primeira compra ou importe o histórico de uma exchange em CSV. Os cálculos de preço médio, resultado e rentabilidade começam a partir daí."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Button onClick={openNew}><Plus /> Registrar transação</Button>
                <Button variant="outline" onClick={() => setImportOpen(true)}><FileUp /> Importar CSV</Button>
              </div>
            }
          />
        </Card>
      ) : (
        <>
          <SummaryCards summary={s} performance={performance.data} locale={locale} loading={!s} />
          <Tabs value={tab} onValueChange={setTab} className="mt-6">
            <TabsList>
              <TabsTrigger value="posicoes">Posições</TabsTrigger>
              <TabsTrigger value="transacoes">Transações</TabsTrigger>
            </TabsList>
            <TabsContent value="posicoes">
              <Card className="gap-0 py-0">
                <PositionsTable positions={s?.positions} currency={currency} locale={locale} loading={!s} />
              </Card>
              {s && s.closed_positions.length > 0 && (
                <details className="mt-4 rounded-xl border border-border bg-card">
                  <summary className="cursor-pointer px-5 py-3 text-sm text-muted-foreground hover:text-foreground">
                    Posições encerradas ({s.closed_positions.length})
                  </summary>
                  <PositionsTable positions={s.closed_positions} currency={currency} locale={locale} />
                </details>
              )}
              {s && (
                <p className="mt-3 text-xs text-subtle-foreground">
                  Custo pelo método do preço médio ponderado, com taxas incluídas. Resultado não realizado = valor de
                  mercado − custo de aquisição. Preços: CoinGecko{s.fx_usd_brl && ` · USD/BRL ${Number(s.fx_usd_brl).toLocaleString(locale, { maximumFractionDigits: 4 })}`}.
                  {s.prices.is_stale && " Atenção: cotações desatualizadas."}
                </p>
              )}
            </TabsContent>
            <TabsContent value="transacoes">
              {pid && (
                <Card className="gap-0 py-0">
                  <TransactionsList
                    portfolioId={pid}
                    onEdit={(tx) => {
                      setEditing(tx);
                      setFormOpen(true);
                    }}
                  />
                </Card>
              )}
            </TabsContent>
          </Tabs>
        </>
      )}

      {pid && (
        <>
          <TransactionDialog open={formOpen} onOpenChange={setFormOpen} portfolioId={pid} transaction={editing} />
          <CsvImportDialog open={importOpen} onOpenChange={setImportOpen} portfolioId={pid} />
        </>
      )}
    </>
  );
}
