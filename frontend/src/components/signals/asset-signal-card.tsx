"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/client";
import type { Timeframe } from "@/lib/api/types";
import { usePreferences } from "@/lib/queries";
import { useAssetSignal } from "@/lib/signal-queries";

import { ClassificationBadge, ComponentBars, RisksAndInvalidation, ScoreGauge, SignalProvenance } from "./signal-parts";

export function AssetSignalCard({ slug, timeframe }: { slug: string; timeframe: Timeframe }) {
  const { locale, timeZone } = usePreferences();
  const query = useAssetSignal(slug, timeframe);
  const signal = query.data;

  if (query.isError) {
    const message = isApiError(query.error, "signal_not_applicable")
      ? query.error.message
      : "Sinal indisponível para este ativo e intervalo.";
    return (
      <Card>
        <CardContent className="text-sm text-muted-foreground">{message}</CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle className="font-heading text-sm font-medium">Sinal de oportunidade · {timeframe}</CardTitle>
        <Link href="/oportunidades" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          Todas as oportunidades <ArrowRight className="size-3.5" />
        </Link>
      </CardHeader>
      <CardContent>
        {!signal ? (
          <Skeleton className="h-40 w-full rounded-lg" />
        ) : (
          <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)]">
            <div className="space-y-3">
              <ScoreGauge score={signal.score} classification={signal.classification} size={120} />
              <ClassificationBadge value={signal.classification} />
              <p className="text-sm text-foreground">{signal.justification}</p>
            </div>
            <ComponentBars signal={signal} locale={locale} />
            <div className="space-y-4">
              <RisksAndInvalidation signal={signal} />
              <SignalProvenance signal={signal} locale={locale} timeZone={timeZone} />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
