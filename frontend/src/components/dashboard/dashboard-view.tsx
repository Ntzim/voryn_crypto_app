"use client";

import { ArrowRight, Plus, Wallet } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import type { ReactNode } from "react";

import { DataStatus } from "@/components/common/data-status";
import { Hint } from "@/components/common/hint";
import { EmptyState, ErrorState } from "@/components/common/states";
import { AssetList } from "@/components/market/asset-list";
import { PositionsTable } from "@/components/portfolio/positions-table";
import { SummaryCards } from "@/components/portfolio/summary-cards";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDateTime, formatMoney, formatNumber } from "@/lib/format";
import { useInsights, usePerformance, usePortfolio, useSummary } from "@/lib/portfolio-queries";
import { useAssets, useMarketOverview, useMe, usePreferences } from "@/lib/queries";

import { AttentionPanel } from "./attention-panel";

// Chart libraries (lightweight-charts, recharts) load after the figures: on a slow connection
// the summary and the lists render first instead of waiting for them.
const chartSkeleton = (height: string) =>
  function ChartSkeleton() {
    return (
      <div className="rounded-2xl border border-border bg-card p-5">
        <Skeleton className={`${height} w-full`} />
      </div>
    );
  };
const EquityChart = dynamic(() => import("@/components/portfolio/equity-chart").then((m) => m.EquityChart), {
  ssr: false,
  loading: chartSkeleton("h-72"),
});
const AllocationChart = dynamic(() => import("@/components/portfolio/allocation-chart").then((m) => m.AllocationChart), {
  ssr: false,
  loading: chartSkeleton("h-44"),
});

const UNIVERSE_HINT =
  "Calculado sobre os 100 maiores ativos por capitalização acompanhados pela Voryn, não sobre o mercado inteiro.";

/**
 * Answers, in order: how much is my portfolio worth and how did it move, how has it evolved,
 * what needs my attention, what do I hold, and how is the market today.
 */
export function DashboardView() {
  const { data: user } = useMe();
  const { currency, locale, timeZone } = usePreferences();
  const portfolio = usePortfolio();
  const summary = useSummary(portfolio.data?.id, currency);
  const performance = usePerformance(portfolio.data?.id, currency);
  const insights = useInsights(portfolio.data?.id);
  const hasPortfolio = (summary.data?.transaction_count ?? 0) > 0;
  const firstName = user?.full_name.split(" ")[0];

  return (
    <>
      <header className="mb-5 md:mb-7">
        <p className="text-xs text-muted-foreground first-letter:uppercase">
          {formatDateTime(new Date().toISOString(), locale, timeZone, { dateStyle: "full" })}
        </p>
        <h1 className="mt-0.5 text-xl font-semibold text-foreground md:text-2xl">
          {firstName ? `Olá, ${firstName}` : <Skeleton className="h-7 w-36" />}
        </h1>
      </header>

      {summary.isPending ? (
        <SummaryCards summary={undefined} performance={undefined} locale={locale} loading />
      ) : hasPortfolio ? (
        <div className="space-y-4">
          <SummaryCards summary={summary.data} performance={performance.data} locale={locale} loading={!summary.data} />
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <EquityChart performance={performance.data} locale={locale} />
            </div>
            <div className="order-last lg:order-none">
              <AllocationChart summary={summary.data} locale={locale} />
            </div>
            <AttentionPanel
              positions={summary.data?.positions}
              insights={insights.data?.items}
              insightsLoading={insights.isPending}
            />
            <section aria-labelledby="positions-title" className="overflow-hidden rounded-2xl border border-border bg-card lg:col-span-2">
              <SectionHeader id="positions-title" title="Principais posições" href="/carteira" linkLabel="Ver carteira" />
              <PositionsTable positions={summary.data?.positions.slice(0, 6)} currency={currency} locale={locale} compact />
            </section>
          </div>
        </div>
      ) : (
        <section className="rounded-2xl border border-border bg-card">
          <EmptyState
            icon={Wallet}
            title="Comece pela sua carteira"
            description="Registre suas compras e vendas ou importe um CSV para acompanhar patrimônio, resultado e rentabilidade."
            action={
              <Button asChild>
                <Link href="/carteira?nova=1">
                  <Plus /> Registrar transação
                </Link>
              </Button>
            }
          />
        </section>
      )}

      <MarketToday />
    </>
  );
}

function SectionHeader({ id, title, href, linkLabel }: { id: string; title: string; href?: string; linkLabel?: string }) {
  return (
    <header className="flex items-center justify-between gap-2 px-5 pt-4 pb-2">
      <h2 id={id} className="font-heading text-sm font-medium">
        {title}
      </h2>
      {href && (
        <Link
          href={href}
          className="-mr-2 inline-flex min-h-10 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground hover:text-foreground"
        >
          {linkLabel} <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      )}
    </header>
  );
}

/** The market in one block: the four figures inline, then movers in tabs instead of three lists. */
function MarketToday() {
  const { currency, locale, timeZone } = usePreferences();
  const overview = useMarketOverview(currency);
  const top = useAssets({ currency, q: "", sort: "rank", order: "asc", page: 1, pageSize: 6 });
  const data = overview.data;
  const breadth =
    data && data.advancers_24h + data.decliners_24h > 0
      ? (data.advancers_24h / (data.advancers_24h + data.decliners_24h)) * 100
      : null;

  return (
    <section aria-labelledby="market-title" className="mt-8 md:mt-10">
      <div className="mb-3 flex items-end justify-between gap-2">
        <h2 id="market-title" className="font-heading text-lg font-semibold">
          Mercado hoje
        </h2>
        <Link
          href="/mercado"
          className="-mr-2 inline-flex min-h-10 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground hover:text-foreground"
        >
          Ver mercado <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </div>

      {overview.isError ? (
        <div className="rounded-2xl border border-border bg-card">
          <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <dl className="grid min-w-0 grid-cols-2 gap-px self-start overflow-hidden rounded-2xl border border-border bg-border">
            <Figure label="Capitalização" hint={UNIVERSE_HINT} loading={!data}>
              {data && formatMoney(data.total_market_cap, currency, locale, { compact: true })}
            </Figure>
            <Figure label="Volume 24h" hint={UNIVERSE_HINT} loading={!data}>
              {data && formatMoney(data.total_volume_24h, currency, locale, { compact: true })}
            </Figure>
            <Figure label="Dominância do Bitcoin" hint={UNIVERSE_HINT} loading={!data}>
              {data && `${formatNumber(data.btc_dominance_pct, locale, { digits: 1 })}%`}
            </Figure>
            <Figure label="Altas × baixas (24h)" loading={!data}>
              {data && (
                <>
                  <span className="text-success">{data.advancers_24h}</span>
                  <span className="text-subtle-foreground"> / </span>
                  <span className="text-destructive">{data.decliners_24h}</span>
                  {breadth !== null && (
                    <span
                      className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-destructive/60"
                      role="img"
                      aria-label={`${Math.round(breadth)}% dos ativos em alta`}
                    >
                      <span className="bg-success" style={{ width: `${breadth}%` }} />
                    </span>
                  )}
                </>
              )}
            </Figure>
          </dl>

          <div className="min-w-0 rounded-2xl border border-border bg-card p-4 lg:col-span-2">
            <Tabs defaultValue="gainers">
              <TabsList className="w-full sm:w-fit">
                <TabsTrigger value="gainers">Altas 24h</TabsTrigger>
                <TabsTrigger value="losers">Baixas 24h</TabsTrigger>
                <TabsTrigger value="top">Ranking</TabsTrigger>
              </TabsList>
              <TabsContent value="gainers">
                <AssetList assets={data?.top_gainers} currency={currency} locale={locale} loading={!data} />
              </TabsContent>
              <TabsContent value="losers">
                <AssetList assets={data?.top_losers} currency={currency} locale={locale} loading={!data} />
              </TabsContent>
              <TabsContent value="top">
                {top.isError ? (
                  <ErrorState error={top.error} onRetry={() => top.refetch()} />
                ) : (
                  <AssetList assets={top.data?.items} currency={currency} locale={locale} loading={top.isPending} rows={6} showRank />
                )}
              </TabsContent>
            </Tabs>
          </div>
        </div>
      )}

      {data && <DataStatus status={data.status} locale={locale} timeZone={timeZone} className="mt-4" />}
    </section>
  );
}

function Figure({ label, hint, loading, children }: { label: string; hint?: string; loading: boolean; children: ReactNode }) {
  return (
    <div className="min-w-0 bg-card px-4 py-3.5">
      <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {label}
        {hint && <Hint label={label} content={hint} />}
      </dt>
      <dd className="num mt-1 font-heading text-lg font-semibold text-foreground">
        {loading ? <Skeleton className="h-6 w-20" /> : children}
      </dd>
    </div>
  );
}
