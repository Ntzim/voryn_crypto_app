"use client";

import { cn } from "cn";

import { useMarkets } from "@/lib/b3-queries";
import { formatDateTime } from "@/lib/format";
import { usePreferences } from "@/lib/queries";

/** B3 session at a glance; shows nothing while the market is not enabled. */
export function SessionPill({ className }: { className?: string }) {
  const { data: markets } = useMarkets();
  const { locale, timeZone } = usePreferences();
  const b3 = markets?.find((m) => m.market === "B3");
  if (!b3) return null;
  const open = b3.state === "open";
  const next = b3.next_open ? formatDateTime(b3.next_open, locale, timeZone, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : null;
  return (
    <span className={cn("inline-flex h-9 items-center gap-2 rounded-full border border-border px-3 text-xs text-muted-foreground", className)}>
      <span aria-hidden className={cn("size-2 rounded-full", open ? "bg-signal-buy" : "bg-signal-neutral-dot")} />
      {open ? `Pregão aberto · ${Math.round(b3.delay_seconds / 60)} min de atraso` : `Pregão fechado${next ? ` · abre ${next}` : ""}`}
    </span>
  );
}
