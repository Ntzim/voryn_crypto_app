"use client";

import { cn } from "cn";
import { TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import type { DataStatus as DataStatusType, Locale } from "@/lib/api/types";
import { formatDateTime, formatNumber, formatRelative } from "@/lib/format";

/** Re-render periodically so "há 3 min" stays truthful without refetching. */
function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/**
 * Provenance + freshness for market data. Required wherever prices are shown: users must
 * always know the source, the time of the data and whether it is stale.
 */
export function DataStatus({
  status,
  locale = "pt-BR",
  timeZone,
  className,
}: {
  status: DataStatusType;
  locale?: Locale;
  timeZone?: string;
  className?: string;
}) {
  const now = useNow();
  const updated = status.fetched_at
    ? `atualizado ${formatRelative(status.fetched_at, locale, now)}`
    : "aguardando primeira sincronização";

  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground", className)}>
      {status.is_stale ? (
        <span className="inline-flex items-center gap-1.5 rounded-md bg-warning/10 px-2 py-1 font-medium text-warning">
          <TriangleAlert className="size-3.5" aria-hidden />
          Dados desatualizados ({updated}). Valores podem não refletir o mercado atual.
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5">
          <span className="size-1.5 rounded-full bg-success" aria-hidden />
          <span title={formatDateTime(status.fetched_at, locale, timeZone)}>{updated}</span>
        </span>
      )}
      <span>{status.attribution}</span>
      {status.currency === "BRL" && status.fx_rate && (
        <span title={`Câmbio observado ${formatDateTime(status.fx_observed_at, locale, timeZone)}`}>
          Convertido a USD/BRL {formatNumber(status.fx_rate, locale, { digits: 4 })}; variações em base USD
        </span>
      )}
    </div>
  );
}
