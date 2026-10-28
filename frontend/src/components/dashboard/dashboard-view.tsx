"use client";

import { ArrowRight, Wallet } from "lucide-react";
import Link from "next/link";

import { DataStatus } from "@/components/common/data-status";
import { PageHeader } from "@/components/common/page-header";
import { StatCard } from "@/components/common/stat-card";
import { EmptyState, ErrorState } from "@/components/common/states";
import { AssetList } from "@/components/market/asset-list";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime, formatMoney, formatNumber } from "@/lib/format";
import { useAssets, useMarketOverview, useMe, usePreferences } from "@/lib/queries";

const UNIVERSE_HINT =
  "Calculado sobre os 100 maiores ativos por capitalização acompanhados pela Voryn, não sobre o mercado inteiro.";

export function DashboardView() {
  const { data: user } = useMe();
  const { currency, locale, timeZone } = usePreferences();
  const overview = useMarketOverview(currency);
  const top = useAssets({ currency, q: "", sort: "rank", order: "asc", page: 1, pageSize: 8 });
  const data = overview.data;
  const firstName = user?.full_name.split(" ")[0];

  const breadth =
    data && data.advancers_24h + data.decliners_24h > 0
      ? (data.advancers_24h / (data.advancers_24h + data.decliners_24h)) * 100
      : null;

  return (
    <>
      <PageHeader
        title={firstName ? `Olá, ${firstName}` : <Skeleton className="h-8 w-40" />}
        description={formatDateTime(new Date().toISOString(), locale, timeZone, { dateStyle: "full" })}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:row-span-2">
          <CardHeader>
            <CardTitle className="font-heading text-sm font-medium text-muted-foreground">Patrimônio</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-1 items-center justify-center">
            <EmptyState
              icon={Wallet}
              title="Sua carteira aparece aqui"
              description="Em breve você poderá registrar transações e importar extratos para acompanhar patrimônio, resultado e rentabilidade."
              className="py-6"
            />
          </CardContent>
        </Card>

        {overview.isError ? (
          <Card className="lg:col-span-2 lg:row-span-2">
            <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
          </Card>
        ) : (
          <div className="grid grid-cols-2 gap-4 lg:col-span-2 lg:row-span-2">
            <StatCard
              label="Capitalização"
              hint={UNIVERSE_HINT}
              loading={!data}
              value={data && formatMoney(data.total_market_cap, currency, locale, { compact: true })}
              footer={data && `${data.tracked_assets} ativos acompanhados`}
            />
            <StatCard
              label="Volume 24h"
              hint={UNIVERSE_HINT}
              loading={!data}
              value={data && formatMoney(data.total_volume_24h, currency, locale, { compact: true })}
              footer="Soma do volume negociado"
            />
            <StatCard
              label="Dominância do Bitcoin"
              hint={UNIVERSE_HINT}
              loading={!data}
              value={data && `${formatNumber(data.btc_dominance_pct, locale, { digits: 1 })}%`}
              footer="Participação do BTC na capitalização"
            />
            <StatCard
              label="Altas × baixas (24h)"
              loading={!data}
              value={
                data && (
                  <>
                    <span className="text-success">{data.advancers_24h}</span>
                    <span className="text-subtle-foreground"> / </span>
                    <span className="text-destructive">{data.decliners_24h}</span>
                  </>
                )
              }
              footer={
                breadth !== null && (
                  <div
                    className="flex h-1.5 overflow-hidden rounded-full bg-destructive/60"
                    role="img"
                    aria-label={`${Math.round(breadth)}% dos ativos em alta`}
                  >
                    <div className="bg-success" style={{ width: `${breadth}%` }} />
                  </div>
                )
              }
            />
          </div>
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="font-heading text-sm font-medium">Maiores ativos</CardTitle>
            <CardAction>
              <Link href="/mercado" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                Ver mercado <ArrowRight className="size-3.5" />
              </Link>
            </CardAction>
          </CardHeader>
          <CardContent>
            {top.isError ? (
              <ErrorState error={top.error} onRetry={() => top.refetch()} />
            ) : (
              <AssetList assets={top.data?.items} currency={currency} locale={locale} loading={top.isPending} rows={8} showRank />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="font-heading text-sm font-medium">Maiores altas · 24h</CardTitle>
          </CardHeader>
          <CardContent>
            <AssetList assets={data?.top_gainers} currency={currency} locale={locale} loading={!data} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="font-heading text-sm font-medium">Maiores baixas · 24h</CardTitle>
          </CardHeader>
          <CardContent>
            <AssetList assets={data?.top_losers} currency={currency} locale={locale} loading={!data} />
          </CardContent>
        </Card>
      </div>

      {data && <DataStatus status={data.status} locale={locale} timeZone={timeZone} className="mt-5" />}
    </>
  );
}
