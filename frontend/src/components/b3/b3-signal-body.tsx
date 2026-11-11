"use client";

import { Info } from "lucide-react";

import { ComponentBars, DataQualityNotice, RisksAndInvalidation, ScoreGauge } from "@/components/signals/signal-parts";
import type { B3Signal, Currency, Locale } from "@/lib/api/types";
import { formatDateTime, formatNumber, formatPrice } from "@/lib/format";

/** A FII without P/VP and income has 55% of its score filled with neutral values: not a score. */
function hasScore(signal: B3Signal): boolean {
  const f = signal.fundamentals;
  return signal.asset_type !== "FII" || Boolean(f?.price_to_nav && f.dividend_yield_12m);
}

/** The asset page's signal card: justification, fundamentals, components, risks and scope. */
export function B3SignalBody({ signal, locale }: { signal: B3Signal; locale: Locale }) {
  const f = signal.fundamentals;
  const currency = signal.currency as Currency;
  return (
    <>
      <DataQualityNotice signal={signal} />
      {hasScore(signal) ? (
        <div className="flex items-center gap-4">
          <ScoreGauge score={signal.score} />
          <p className="text-sm text-foreground">{signal.justification}</p>
        </div>
      ) : (
        <p className="text-sm text-foreground">Sem P/VP e rendimentos não há score para este fundo: mais da metade do cálculo depende deles.</p>
      )}
      {f && (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-[10px] bg-background p-3 text-sm">
          <Fact label="P/VP" value={f.price_to_nav ? formatNumber(f.price_to_nav, locale, { digits: 2 }) : "—"} hint={f.nav_as_of ? `patrimônio de ${formatDateTime(f.nav_as_of, locale, "UTC", { month: "2-digit", year: "numeric" })}` : undefined} />
          <Fact label="Yield em 12 meses" value={f.dividend_yield_12m ? `${formatNumber(f.dividend_yield_12m, locale, { digits: 1 })}%` : "—"} hint="sobre o preço atual" />
          <Fact label="Meses com pagamento" value={f.months_paid_12m !== null ? `${f.months_paid_12m} de 12` : "—"} />
          <Fact label="Último rendimento" value={f.last_payment_rate ? formatPrice(f.last_payment_rate, currency, locale) : "—"} hint={f.last_payment_date ? `pago em ${formatDateTime(f.last_payment_date, locale, "UTC", { dateStyle: "short" })}` : undefined} />
        </dl>
      )}
      {hasScore(signal) && (
        <>
          <ComponentBars signal={signal} locale={locale} />
          <RisksAndInvalidation signal={signal} />
        </>
      )}
      <p className="flex gap-2 text-xs text-muted-foreground">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {signal.scope}
      </p>
    </>
  );
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="num font-medium text-foreground">{value}</dd>
      {hint && <dd className="text-xs text-subtle-foreground">{hint}</dd>}
    </div>
  );
}
