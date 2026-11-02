"use client";

import { ArrowLeft, CalendarOff, CandlestickChart, SearchX } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { ChangeBadge } from "@/components/common/change-badge";
import { EmptyState, ErrorState } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { useB3Asset, useB3History } from "@/lib/b3-queries";
import { isApiError } from "@/lib/api/client";
import type { Currency, ExchangeDetail, Locale } from "@/lib/api/types";
import { formatMoney, formatNumber, formatPrice } from "@/lib/format";
import { usePreferences } from "@/lib/queries";

import { B3PriceChart } from "./b3-price-chart";
import { ASSET_TYPE_LABEL, B3DataNote, B3SessionBadge, sectorLabel, unavailableMessage } from "./b3-status";

const RANGE_LABEL: Record<string, string> = { "1mo": "1M", "3mo": "3M", "1y": "1A", "5y": "5A" };

export function B3AssetView({ symbol }: { symbol: string }) {
  const { locale, timeZone } = usePreferences();
  const query = useB3Asset(symbol);

  return (
    <>
      <Link href="/b3" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Bolsa B3
      </Link>
      {query.isError ? (
        <Card>
          {isApiError(query.error, "market_disabled") ? (
            <EmptyState icon={CalendarOff} title="B3 ainda não disponível" description="Este mercado ainda não foi liberado na Voryn." />
          ) : isApiError(query.error, "not_found") ? (
            <EmptyState icon={SearchX} title="Ativo não encontrado" description={`${symbol} não está entre os ativos listados acompanhados.`} />
          ) : (
            <ErrorState error={query.error} onRetry={() => query.refetch()} />
          )}
        </Card>
      ) : !query.data ? (
        <div className="space-y-4">
          <Skeleton className="h-28 w-full rounded-2xl" />
          <Skeleton className="h-96 w-full rounded-2xl" />
        </div>
      ) : (
        <Detail data={query.data} locale={locale} timeZone={timeZone} symbol={symbol} />
      )}
    </>
  );
}

function Detail({ data, locale, timeZone, symbol }: { data: ExchangeDetail; locale: Locale; timeZone: string; symbol: string }) {
  const { asset, status } = data;
  const currency = asset.currency as Currency;
  const sector = sectorLabel(asset.sector);
  const money = (value: string | null) => formatPrice(value, currency, locale);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-3">
          <AssetIcon src={asset.image_url} symbol={asset.symbol} size={40} />
          <div className="min-w-0">
            <h1 className="flex flex-wrap items-center gap-2 font-heading text-2xl font-semibold text-foreground">
              {asset.symbol}
              <Badge variant="outline">{ASSET_TYPE_LABEL[asset.asset_type] ?? asset.asset_type}</Badge>
            </h1>
            <p className="truncate text-sm text-muted-foreground">
              {asset.name}
              {sector && ` · ${sector}`}
            </p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="num font-heading text-4xl font-semibold tracking-tight text-foreground">{money(asset.price)}</span>
          <ChangeBadge value={asset.change_pct} locale={locale} variant="pill" />
          <span className="text-xs text-muted-foreground">sobre o fechamento anterior</span>
        </div>
        <B3SessionBadge status={status} locale={locale} timeZone={timeZone} className="mt-3" />
      </div>

      <PriceHistory symbol={symbol} locale={locale} />

      <Card>
        <CardHeader>
          <CardTitle className="font-heading text-sm font-medium">Dados do pregão</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
            <Figure label="Abertura" value={money(data.open)} />
            <Figure label="Fechamento anterior" value={money(data.previous_close)} />
            <Figure label="Mínima do dia" value={money(data.day_low)} />
            <Figure label="Máxima do dia" value={money(data.day_high)} />
            <Figure label="Mínima em 52 semanas" value={money(data.week52_low)} />
            <Figure label="Máxima em 52 semanas" value={money(data.week52_high)} />
            <Figure label="Volume" value={formatNumber(asset.volume, locale, { compact: true })} />
            <Figure label="Valor negociado" value={formatMoney(asset.traded_value, currency, locale, { compact: true })} />
            <Figure label="Capitalização" value={formatMoney(asset.market_cap, currency, locale, { compact: true })} />
          </dl>
          {data.detail_unavailable && (
            <p className="mt-4 text-xs text-muted-foreground">
              Parte destes dados não está disponível. {unavailableMessage(data.detail_unavailable)}
            </p>
          )}
        </CardContent>
      </Card>

      <B3DataNote status={status} locale={locale} timeZone={timeZone} />
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="num mt-0.5 text-sm font-medium text-foreground">{value}</dd>
    </div>
  );
}

function PriceHistory({ symbol, locale }: { symbol: string; locale: Locale }) {
  const [range, setRange] = useState("3mo");
  const query = useB3History(symbol, range);
  const data = query.data;
  const ranges = data?.allowed_ranges ?? [];

  return (
    <Card className="gap-3">
      <CardHeader className="flex items-center justify-between gap-3">
        <CardTitle className="font-heading text-sm font-medium">Histórico diário</CardTitle>
      </CardHeader>
      <CardContent>
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : !data ? (
          <Skeleton className="h-72 w-full rounded-lg md:h-96" />
        ) : data.unavailable ? (
          <EmptyState icon={CandlestickChart} title="Histórico indisponível" description={unavailableMessage(data.unavailable)} />
        ) : data.bars.length === 0 ? (
          <EmptyState icon={CandlestickChart} title="Sem histórico" description="A fonte de dados não tem pregões recentes para este ativo." />
        ) : (
          <B3PriceChart bars={data.bars} locale={locale} />
        )}
        {ranges.length > 1 && !data?.unavailable && (
          <Segmented
            label="Período"
            value={range}
            onChange={setRange}
            className="mt-3 flex w-full *:flex-1"
            options={ranges.map((value) => ({ value, label: RANGE_LABEL[value] ?? value }))}
          />
        )}
      </CardContent>
    </Card>
  );
}
