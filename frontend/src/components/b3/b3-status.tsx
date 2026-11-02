"use client";

import { cn } from "cn";
import { TriangleAlert } from "lucide-react";

import type { ExchangeStatus, Locale } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

export const ASSET_TYPE_LABEL: Record<string, string> = {
  STOCK: "Ação",
  FII: "FII",
  ETF: "ETF",
  BDR: "BDR",
};

const SECTOR_LABEL: Record<string, string> = {
  "Commercial Services": "Serviços comerciais",
  Communications: "Comunicações",
  "Consumer Durables": "Bens duráveis",
  "Consumer Non-Durables": "Bens de consumo",
  "Consumer Services": "Serviços ao consumidor",
  "Distribution Services": "Distribuição",
  "Electronic Technology": "Tecnologia eletrônica",
  "Energy Minerals": "Energia e combustíveis",
  Finance: "Finanças",
  "Health Services": "Serviços de saúde",
  "Health Technology": "Tecnologia em saúde",
  "Industrial Services": "Serviços industriais",
  Miscellaneous: "Diversos",
  "Non-Energy Minerals": "Mineração",
  "Process Industries": "Indústria de base",
  "Producer Manufacturing": "Bens industriais",
  "Retail Trade": "Varejo",
  "Technology Services": "Serviços de tecnologia",
  Transportation: "Transportes",
  Utilities: "Utilidade pública",
};

export function sectorLabel(sector: string | null | undefined): string | null {
  if (!sector) return null;
  return SECTOR_LABEL[sector] ?? sector;
}

export function delayLabel(seconds: number): string {
  return `${Math.round(seconds / 60)} min de atraso`;
}

/**
 * Session state and quote delay, required wherever B3 quotes appear: they are delayed by the
 * data plan and must never read as real time.
 */
export function B3SessionBadge({
  status,
  locale,
  timeZone,
  className,
}: {
  status: ExchangeStatus;
  locale: Locale;
  timeZone: string;
  className?: string;
}) {
  const open = status.state === "open";
  const short = { dateStyle: "short", timeStyle: "short" } as const;
  return (
    <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground", className)}>
      <span className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 font-medium text-foreground">
        <span className={cn("size-1.5 rounded-full", open ? "bg-success" : "bg-subtle-foreground")} aria-hidden />
        {open ? "Pregão aberto" : "Pregão fechado"}
      </span>
      <span className="rounded-md bg-warning/10 px-2 py-1 font-medium text-warning">Cotações com {delayLabel(status.delay_seconds)}</span>
      {!open && status.next_open && <span>Próxima abertura: {formatDateTime(status.next_open, locale, timeZone, short)}</span>}
    </div>
  );
}

/** Time and source of the data, plus a warning when it stopped updating. */
export function B3DataNote({
  status,
  locale,
  timeZone,
  className,
}: {
  status: ExchangeStatus;
  locale: Locale;
  timeZone: string;
  className?: string;
}) {
  const short = { dateStyle: "short", timeStyle: "short" } as const;
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground", className)}>
      {status.is_stale && (
        <span className="inline-flex items-center gap-1.5 rounded-md bg-warning/10 px-2 py-1 font-medium text-warning">
          <TriangleAlert className="size-3.5" aria-hidden />
          {status.as_of ? "Dados desatualizados. Os valores podem não refletir o último pregão." : "Aguardando a primeira sincronização."}
        </span>
      )}
      {status.as_of && <span>Dados de {formatDateTime(status.as_of, locale, timeZone, short)}</span>}
      <span>{status.attribution}</span>
      <span>Informativo, não é recomendação de investimento.</span>
    </div>
  );
}

export function unavailableMessage(reason: string): string {
  if (reason === "quota_reached") return "O limite mensal de consultas à fonte de dados foi atingido.";
  if (reason === "provider_unavailable") return "A fonte de dados não respondeu agora. Tente novamente em instantes.";
  return "O plano de dados atual não libera este ativo.";
}
