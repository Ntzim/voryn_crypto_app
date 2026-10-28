"use client";

import { ArrowLeft, ChartCandlestick, SearchX } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { ChangeBadge } from "@/components/common/change-badge";
import { DataStatus } from "@/components/common/data-status";
import { EmptyState, ErrorState } from "@/components/common/states";
import { CurrencyToggle } from "@/components/market/currency-toggle";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/client";
import type { Asset, Currency, Locale } from "@/lib/api/types";
import { formatDateTime, formatMoney, formatNumber, formatPercent, formatPrice } from "@/lib/format";
import { useAsset, usePreferences } from "@/lib/queries";

export function AssetView({ slug }: { slug: string }) {
  const prefs = usePreferences();
  const [currency, setCurrency] = useState<Currency | null>(null);
  const activeCurrency = currency ?? prefs.currency;
  const query = useAsset(slug, activeCurrency);
  const { locale, timeZone } = prefs;

  return (
    <>
      <Link href="/mercado" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Mercado
      </Link>

      {query.isError ? (
        isApiError(query.error, "not_found") ? (
          <Card>
            <EmptyState icon={SearchX} title="Ativo não encontrado" description="Este ativo não está entre os acompanhados pela Voryn." />
          </Card>
        ) : (
          <Card>
            <ErrorState error={query.error} onRetry={() => query.refetch()} />
          </Card>
        )
      ) : !query.data ? (
        <AssetSkeleton />
      ) : (
        <AssetDetail
          asset={query.data.asset}
          currency={activeCurrency}
          locale={locale}
          timeZone={timeZone}
          onCurrencyChange={setCurrency}
          footer={<DataStatus status={query.data.status} locale={locale} timeZone={timeZone} className="mt-5" />}
        />
      )}
    </>
  );
}

function AssetDetail({
  asset,
  currency,
  locale,
  timeZone,
  onCurrencyChange,
  footer,
}: {
  asset: Asset;
  currency: Currency;
  locale: Locale;
  timeZone: string;
  onCurrencyChange: (c: Currency) => void;
  footer: React.ReactNode;
}) {
  const money = (v: string | null) => formatMoney(v, currency, locale, { compact: true });
  const price = (v: string | null) => formatPrice(v, currency, locale);
  const supply = (v: string | null) => (v ? `${formatNumber(v, locale, { compact: true })} ${asset.symbol}` : "—");

  return (
    <>
      <div className="mb-6 flex flex-col gap-5 md:mb-8 md:flex-row md:items-end md:justify-between">
        <div className="flex items-start gap-4">
          <AssetIcon src={asset.image_url} symbol={asset.symbol} size={44} className="mt-1" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold md:text-[28px]">{asset.name}</h1>
              <Badge variant="outline" className="text-muted-foreground">{asset.symbol}</Badge>
              {asset.market_cap_rank && (
                <Badge variant="secondary" className="num">#{asset.market_cap_rank}</Badge>
              )}
            </div>
            <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="num font-heading text-3xl font-semibold text-foreground md:text-4xl">{price(asset.price)}</span>
              <ChangeBadge value={asset.change_pct_24h} locale={locale} variant="pill" />
              <span className="text-xs text-muted-foreground">24h</span>
            </div>
          </div>
        </div>
        <CurrencyToggle value={currency} onChange={onCurrencyChange} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="font-heading text-sm font-medium">Desempenho</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-3 gap-4">
              <Metric label="1 hora" value={<ChangeBadge value={asset.change_pct_1h} locale={locale} />} />
              <Metric label="24 horas" value={<ChangeBadge value={asset.change_pct_24h} locale={locale} />} />
              <Metric label="7 dias" value={<ChangeBadge value={asset.change_pct_7d} locale={locale} />} />
            </div>
            <RangeBar low={asset.low_24h} high={asset.high_24h} current={asset.price} format={price} />
            <div className="flex items-center gap-3 rounded-lg border border-dashed border-border-strong bg-surface px-4 py-3 text-sm text-muted-foreground">
              <ChartCandlestick className="size-4 shrink-0 text-subtle-foreground" />
              Gráfico de candles e indicadores técnicos chegam com o módulo de Análise de Ativos.
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-heading text-sm font-medium">Máxima histórica</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Metric label="Preço máximo" value={price(asset.ath)} />
            <Metric label="Data" value={formatDateTime(asset.ath_date, locale, timeZone, { dateStyle: "medium" })} />
            <Metric
              label="Distância da máxima"
              value={<span className="text-foreground">{formatPercent(asset.ath_change_pct, locale, 1)}</span>}
            />
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="font-heading text-sm font-medium">Mercado e oferta</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-3 xl:grid-cols-6">
            <Metric label="Capitalização" value={money(asset.market_cap)} />
            <Metric label="Valor totalmente diluído" value={money(asset.fully_diluted_valuation)} />
            <Metric label="Volume 24h" value={money(asset.total_volume)} />
            <Metric label="Oferta circulante" value={supply(asset.circulating_supply)} />
            <Metric label="Oferta total" value={supply(asset.total_supply)} />
            <Metric label="Oferta máxima" value={asset.max_supply ? supply(asset.max_supply) : "Ilimitada"} />
          </dl>
        </CardContent>
      </Card>
      {footer}
    </>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="num mt-1 truncate text-sm font-medium text-foreground">{value}</dd>
    </div>
  );
}

function RangeBar({
  low,
  high,
  current,
  format,
}: {
  low: string | null;
  high: string | null;
  current: string;
  format: (v: string | null) => string;
}) {
  const l = Number(low);
  const h = Number(high);
  const c = Number(current);
  if (!low || !high || !(h > l)) return null;
  const position = Math.min(100, Math.max(0, ((c - l) / (h - l)) * 100));
  return (
    <div>
      <div className="mb-2 flex justify-between text-xs text-muted-foreground">
        <span>Mínima 24h</span>
        <span>Máxima 24h</span>
      </div>
      <div className="relative h-1.5 rounded-full bg-accent">
        <div className="absolute inset-y-0 left-0 rounded-full bg-primary/40" style={{ width: `${position}%` }} />
        <div
          className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-foreground"
          style={{ left: `${position}%` }}
          aria-hidden
        />
      </div>
      <div className="num mt-2 flex justify-between text-sm font-medium text-foreground">
        <span>{format(low)}</span>
        <span>{format(high)}</span>
      </div>
    </div>
  );
}

function AssetSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Skeleton className="size-11 rounded-full" />
        <div className="space-y-2">
          <Skeleton className="h-7 w-40" />
          <Skeleton className="h-9 w-56" />
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-64 rounded-xl lg:col-span-2" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
      <Skeleton className="h-36 rounded-xl" />
    </div>
  );
}
