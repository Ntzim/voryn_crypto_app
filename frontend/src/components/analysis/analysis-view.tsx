"use client";

import { cn } from "cn";
import { ArrowLeft, CandlestickChart, SearchX } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { AssetSignalCard } from "@/components/signals/asset-signal-card";
import { ChangeBadge } from "@/components/common/change-badge";
import { EmptyState, ErrorState } from "@/components/common/states";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TIMEFRAMES, useAnalysis } from "@/lib/analysis-queries";
import { isApiError } from "@/lib/api/client";
import type { Timeframe } from "@/lib/api/types";
import { formatPrice } from "@/lib/format";
import { useAsset, usePreferences } from "@/lib/queries";

import { IndicatorsCard, LevelsCard, SourceNote, TrendBadge, TrendCard } from "./analysis-panels";
import { CandleChart, OVERLAY_COLORS, type Oscillator, type Overlay } from "./candle-chart";
import { WatchlistMenu } from "./watchlist-button";

const OVERLAYS: { key: Overlay; label: string; color?: string }[] = [
  { key: "ema9", label: "EMA 9", color: OVERLAY_COLORS.ema9 },
  { key: "ema21", label: "EMA 21", color: OVERLAY_COLORS.ema21 },
  { key: "ema50", label: "EMA 50", color: OVERLAY_COLORS.ema50 },
  { key: "ema200", label: "EMA 200", color: OVERLAY_COLORS.ema200 },
  { key: "bollinger", label: "Bollinger" },
  { key: "levels", label: "Suporte/Resistência" },
];
const OSCILLATORS: { key: Oscillator; label: string }[] = [
  { key: "rsi", label: "RSI" },
  { key: "macd", label: "MACD" },
];

function Chip({ active, onClick, children, color }: { active: boolean; onClick: () => void; children: React.ReactNode; color?: string }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors",
        active ? "border-border-strong bg-card text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {color && <span className="size-2 rounded-full" style={{ backgroundColor: active ? color : "transparent", boxShadow: `inset 0 0 0 1px ${color}` }} />}
      {children}
    </button>
  );
}

export function AnalysisView({ slug }: { slug: string }) {
  const { locale, timeZone } = usePreferences();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const requested = params.get("tf");
  const timeframe: Timeframe = TIMEFRAMES.some((t) => t.value === requested) ? (requested as Timeframe) : "1d";
  const analysis = useAnalysis(slug, timeframe);
  const asset = useAsset(slug, "USD");
  const [overlays, setOverlays] = useState<Set<Overlay>>(() => new Set(["ema21", "ema50", "ema200", "levels"]));
  const [oscillators, setOscillators] = useState<Set<Oscillator>>(() => new Set(["rsi", "macd"]));

  const toggle = <T,>(set: Set<T>, key: T) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  };
  const overlaysKey = useMemo(() => overlays, [overlays]);
  const info = asset.data?.asset;
  const data = analysis.data;

  return (
    <>
      <Link href={`/mercado/${slug}`} className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Visão geral do ativo
      </Link>

      <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="flex items-center gap-3">
          {info ? <AssetIcon src={info.image_url} symbol={info.symbol} size={40} /> : <Skeleton className="size-10 rounded-full" />}
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold">{info?.name ?? <Skeleton className="h-7 w-32" />}</h1>
              {data && <TrendBadge trend={data.trend} />}
            </div>
            {info && (
              <p className="num mt-1 flex items-center gap-2 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{formatPrice(info.price, "USD", locale)}</span>
                <ChangeBadge value={info.change_pct_24h} locale={locale} /> 24h
              </p>
            )}
          </div>
        </div>
        {info && <WatchlistMenu assetId={info.id} />}
      </div>

      <Card className="gap-3 py-4">
        <div className="flex flex-col gap-3 px-4 lg:flex-row lg:items-center lg:justify-between">
          <div role="radiogroup" aria-label="Intervalo" className="inline-flex w-fit rounded-lg border border-border bg-surface p-0.5">
            {TIMEFRAMES.map((t) => (
              <button
                key={t.value}
                type="button"
                role="radio"
                aria-checked={timeframe === t.value}
                onClick={() => router.replace(`${pathname}?tf=${t.value}`, { scroll: false })}
                className={cn(
                  "num h-8 min-w-11 rounded-md px-2.5 text-xs font-medium transition-colors",
                  timeframe === t.value ? "bg-card text-foreground ring-1 ring-border-strong" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1">
            {OVERLAYS.map((o) => (
              <Chip key={o.key} active={overlays.has(o.key)} color={o.color} onClick={() => setOverlays((s) => toggle(s, o.key))}>
                {o.label}
              </Chip>
            ))}
            <span className="mx-1 hidden w-px bg-border sm:block" />
            {OSCILLATORS.map((o) => (
              <Chip key={o.key} active={oscillators.has(o.key)} onClick={() => setOscillators((s) => toggle(s, o.key))}>
                {o.label}
              </Chip>
            ))}
          </div>
        </div>
        <CardContent className="px-2 sm:px-4">
          {analysis.isError ? (
            isApiError(analysis.error, "candles_unavailable") ? (
              <EmptyState
                icon={SearchX}
                title="Gráfico indisponível para este ativo"
                description={`${analysis.error.message} A Voryn usa o par do ativo contra USDT na Binance e só o exibe quando o preço confere com a cotação de referência.`}
              />
            ) : (
              <ErrorState error={analysis.error} onRetry={() => analysis.refetch()} />
            )
          ) : !data ? (
            <Skeleton className="h-[700px] w-full rounded-lg" />
          ) : (
            <div className={cn("transition-opacity", analysis.isPlaceholderData && "opacity-50")}>
              <CandleChart analysis={data} overlays={overlaysKey} oscillators={oscillators} locale={locale} timeZone={timeZone} />
            </div>
          )}
        </CardContent>
      </Card>

      {data && (
        <>
          <div className="mt-4">
            <AssetSignalCard slug={slug} timeframe={timeframe} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <TrendCard trend={data.trend} />
            <IndicatorsCard analysis={data} locale={locale} timeZone={timeZone} />
            <LevelsCard analysis={data} locale={locale} />
          </div>
          <div className="mt-4">
            <SourceNote analysis={data} locale={locale} />
          </div>
        </>
      )}
      {!data && !analysis.isError && (
        <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
          <CandlestickChart className="size-4" /> Carregando candles e indicadores…
        </p>
      )}
    </>
  );
}
