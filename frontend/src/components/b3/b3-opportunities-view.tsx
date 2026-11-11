"use client";

import { CalendarOff } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { PageHeader } from "@/components/common/page-header";
import { EmptyState } from "@/components/common/states";
import { OpportunityTabs } from "@/components/opportunities/market-tabs";
import { OpportunitiesBoard } from "@/components/opportunities/opportunities-board";
import { isApiError } from "@/lib/api/client";
import { useB3Signals, type B3SignalType } from "@/lib/b3-queries";
import { formatDateTime } from "@/lib/format";
import { toOpportunity } from "@/lib/opportunity";
import { usePreferences } from "@/lib/queries";

export function B3OpportunitiesView() {
  const { locale, timeZone } = usePreferences();
  const params = useSearchParams();
  const assetType: B3SignalType = params.get("tipo") === "FII" ? "FII" : "STOCK";
  const query = useB3Signals(assetType);
  const items = useMemo(() => query.data?.items.map(toOpportunity), [query.data]);
  const status = query.data?.status;

  if (isApiError(query.error, "market_disabled")) {
    return (
      <>
        <PageHeader title="Oportunidades" description="Sinais quantitativos por mercado." />
        <div className="rounded-2xl border border-border bg-surface">
          <EmptyState icon={CalendarOff} title="B3 ainda não disponível" description="Este mercado ainda não foi liberado na Voryn." />
        </div>
      </>
    );
  }

  const fii = assetType === "FII";
  return (
    <OpportunitiesBoard
      title={fii ? "Oportunidades em FIIs" : "Oportunidades B3"}
      description={
        fii
          ? "Sinais para os FIIs mais negociados: P/VP, rendimentos e análise técnica, com score, evidências, riscos e condição de invalidação."
          : "Sinais técnicos para os ativos mais negociados, com score, evidências, riscos e condição de invalidação."
      }
      noun={fii ? "FIIs" : "ações"}
      items={items}
      error={query.error}
      onRetry={() => query.refetch()}
      locale={locale}
      tabs={<OpportunityTabs current={assetType} />}
      meta={
        <>
          {status && (
            <span className="inline-flex items-center rounded-full bg-signal-watch-soft px-2.5 py-1 font-medium text-signal-watch">
              Cotações com {Math.round(status.delay_seconds / 60)} min de atraso
            </span>
          )}
          {status?.as_of && <span>Atualizado em {formatDateTime(status.as_of, locale, timeZone, { dateStyle: "short", timeStyle: "short" })}</span>}
        </>
      }
      limits={query.data ? `${query.data.scope} ${query.data.disclaimer}` : "Carregando…"}
      footnote="Score mede a força da evidência (0–100); o sinal indica a direção. Pesos ainda sem validação por backtest. Não é recomendação de investimento."
    />
  );
}
