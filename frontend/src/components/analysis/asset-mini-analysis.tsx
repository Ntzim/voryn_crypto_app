"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useAnalysis } from "@/lib/analysis-queries";
import { isApiError } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";
import { usePreferences } from "@/lib/queries";

import { TrendBadge } from "./analysis-panels";
import { CandleChart, type Oscillator, type Overlay } from "./candle-chart";

const OVERLAYS = new Set<Overlay>(["ema50", "ema200"]);
const NO_OSCILLATORS = new Set<Oscillator>();

/** Daily chart + trend summary on the asset overview page. */
export function AssetMiniAnalysis({ slug }: { slug: string }) {
  const { locale, timeZone } = usePreferences();
  const analysis = useAnalysis(slug, "1d");
  const data = analysis.data;
  const overlays = useMemo(() => OVERLAYS, []);

  if (analysis.isError) {
    return (
      <p className="rounded-lg border border-dashed border-border-strong bg-surface px-4 py-3 text-sm text-muted-foreground">
        {isApiError(analysis.error, "candles_unavailable")
          ? "Gráfico indisponível: não há mercado de referência confiável para este ativo."
          : "Não foi possível carregar o gráfico agora."}
      </p>
    );
  }
  if (!data) return <Skeleton className="h-72 w-full rounded-lg" />;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <TrendBadge trend={data.trend} />
          {data.snapshot?.rsi && (
            <span className="num text-xs text-muted-foreground">RSI {formatNumber(data.snapshot.rsi, locale, { digits: 1 })}</span>
          )}
          <span className="text-xs text-muted-foreground">· gráfico diário, EMA 50/200</span>
        </div>
        <Link href={`/analise/${slug}`} className="inline-flex items-center gap-1 text-xs font-medium text-primary-ink hover:underline">
          Análise técnica completa <ArrowRight className="size-3.5" />
        </Link>
      </div>
      <CandleChart analysis={data} overlays={overlays} oscillators={NO_OSCILLATORS} locale={locale} timeZone={timeZone} height={300} />
    </div>
  );
}
