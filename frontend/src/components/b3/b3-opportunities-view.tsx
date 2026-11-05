"use client";

import { cn } from "cn";
import { ArrowRight, CalendarOff, Info, Radar } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { Hint } from "@/components/common/hint";
import { PageHeader } from "@/components/common/page-header";
import { EmptyState, ErrorState } from "@/components/common/states";
import {
  ClassificationBadge,
  ComponentBars,
  DataQualityNotice,
  RisksAndInvalidation,
  ScoreGauge,
} from "@/components/signals/signal-parts";
import { Card } from "@/components/ui/card";
import { Segmented } from "@/components/ui/segmented";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/client";
import type { B3Signal, Currency, Locale, SignalClass } from "@/lib/api/types";
import { useB3Signals, type B3SignalType } from "@/lib/b3-queries";
import { formatDateTime, formatNumber, formatPercent, formatPrice } from "@/lib/format";
import { usePreferences } from "@/lib/queries";
import { SIGNAL_META } from "@/lib/signal-queries";

import { B3DataNote, B3SessionBadge, sectorLabel } from "./b3-status";

/** A FII without P/VP and income has 55% of its score filled with neutral values: not a score. */
function hasScore(signal: B3Signal): boolean {
  const f = signal.fundamentals;
  return signal.asset_type !== "FII" || Boolean(f?.price_to_nav && f.dividend_yield_12m);
}

const CLASSES: SignalClass[] = ["buy_potential", "attention", "neutral", "sell_potential"];

export function B3OpportunitiesView() {
  const { locale, timeZone } = usePreferences();
  const params = useSearchParams();
  const pathname = usePathname();
  const assetType: B3SignalType = params.get("tipo") === "FII" ? "FII" : "STOCK";
  const filter = (params.get("classe") as SignalClass | null) ?? null;
  const query = useB3Signals(assetType);
  const [open, setOpen] = useState<B3Signal | null>(null);

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    window.history.replaceState(null, "", `${pathname}${next.size ? `?${next}` : ""}`);
  };

  const all = query.data?.items;
  const counts = useMemo(() => {
    const c = { buy_potential: 0, attention: 0, neutral: 0, sell_potential: 0 } as Record<SignalClass, number>;
    for (const s of all ?? []) c[s.classification] += 1;
    return c;
  }, [all]);
  const items = (all ?? []).filter((s) => !filter || s.classification === filter);

  if (isApiError(query.error, "market_disabled")) {
    return (
      <>
        <PageHeader title="Oportunidades B3" description="Sinais quantitativos para ações e FIIs." />
        <Card>
          <EmptyState icon={CalendarOff} title="B3 ainda não disponível" description="Este mercado ainda não foi liberado na Voryn." />
        </Card>
      </>
    );
  }

  const data = query.data;
  return (
    <>
      <PageHeader
        title="Oportunidades B3"
        description="Sinais quantitativos para as ações e os FIIs mais negociados, com score, justificativa, riscos e condições de invalidação."
        actions={
          <Segmented
            label="Tipo de ativo"
            value={assetType}
            onChange={(v) => update({ tipo: v === "FII" ? "FII" : null, classe: null })}
            options={[
              { value: "STOCK", label: "Ações" },
              { value: "FII", label: "FIIs" },
            ]}
          />
        }
      />
      {data && <B3SessionBadge status={data.status} locale={locale} timeZone={timeZone} className="mb-3" />}

      {/* What the analysis leaves out comes first: it changes how every score should be read. */}
      {data && (
        <div role="note" className="mb-4 flex gap-2 rounded-lg border border-border bg-surface p-3 text-sm text-muted-foreground">
          <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>{data.scope}</p>
        </div>
      )}

      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="-mx-4 scroll-row gap-1.5 scroll-px-4 px-4 md:mx-0 md:flex-wrap md:overflow-visible md:px-0">
          <FilterChip active={!filter} onClick={() => update({ classe: null })}>
            Todos <span className="num text-subtle-foreground">{all?.length ?? 0}</span>
          </FilterChip>
          {CLASSES.map((c) => (
            <FilterChip key={c} active={filter === c} onClick={() => update({ classe: filter === c ? null : c })}>
              <span className="size-2 rounded-full" style={{ backgroundColor: SIGNAL_META[c].color }} />
              {SIGNAL_META[c].label} <span className="num text-subtle-foreground">{counts[c]}</span>
            </FilterChip>
          ))}
        </div>
        {data && (
          <Hint
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            content={
              <>
                <p className="font-medium">{data.strategy.name}</p>
                <p>
                  Pesos:{" "}
                  {Object.entries(data.strategy.weights_pct)
                    .map(([key, pct]) => `${WEIGHT_LABEL[key] ?? key} ${formatNumber(pct, locale, { digits: 0 })}%`)
                    .join(", ")}
                  .
                </p>
                <p>
                  Score ≥ {formatNumber(data.strategy.buy_threshold, locale, { digits: 0 })}: potencial de compra · ≤{" "}
                  {formatNumber(data.strategy.sell_threshold, locale, { digits: 0 })}: potencial de venda. Pesos ainda sem validação por backtest.
                </p>
              </>
            }
          >
            <Info className="size-3.5" /> Metodologia
          </Hint>
        )}
      </div>

      {query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      ) : !data ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-48 rounded-xl" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={Radar}
            title={all?.length ? "Nenhum sinal neste filtro" : "Sinais ainda não gerados"}
            description={all?.length ? "Tente outra classificação." : "Os sinais são calculados uma vez por pregão, depois do fechamento, para os ativos mais negociados."}
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {items.map((signal) => (
            <SignalCard key={signal.id} signal={signal} locale={locale} onOpen={() => setOpen(signal)} />
          ))}
        </div>
      )}

      {data && (
        <>
          <p className="mt-5 text-xs text-subtle-foreground">{data.disclaimer}</p>
          <B3DataNote status={data.status} locale={locale} timeZone={timeZone} className="mt-2" />
        </>
      )}

      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
          {open && <B3SignalDetail signal={open} locale={locale} />}
        </SheetContent>
      </Sheet>
    </>
  );
}

const WEIGHT_LABEL: Record<string, string> = {
  trend: "tendência",
  momentum: "momentum",
  volume: "volume",
  volatility: "volatilidade",
  levels: "suportes/resistências",
  market: "mercado",
  valuation: "P/VP",
  income: "rendimentos",
};

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium whitespace-nowrap transition-colors",
        active ? "border-border-strong bg-card text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function SignalCard({ signal, locale, onOpen }: { signal: B3Signal; locale: Locale; onOpen: () => void }) {
  const currency = signal.currency as Currency;
  const f = signal.fundamentals;
  return (
    <Card className="pressable gap-3">
      <button type="button" onClick={onOpen} aria-label={`Ver análise de ${signal.asset.symbol}`} className="flex h-full flex-col gap-3 px-(--card-spacing) text-left">
        <div className="flex items-center gap-3">
          <AssetIcon src={signal.asset.image_url} symbol={signal.asset.symbol} size={32} />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">{signal.asset.symbol}</p>
            <p className="truncate text-xs text-muted-foreground">{signal.asset.name}</p>
          </div>
          {hasScore(signal) ? (
            <ScoreGauge score={signal.score} classification={signal.classification} size={64} />
          ) : (
            <span className="text-xs text-subtle-foreground">Sem score</span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ClassificationBadge value={signal.classification} />
          <span className="num text-sm font-medium text-foreground">{formatPrice(signal.current_price ?? signal.reference_price, currency, locale)}</span>
        </div>
        {f && (
          <dl className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt className="text-muted-foreground">P/VP</dt>
              <dd className="num font-medium text-foreground">{f.price_to_nav ? formatNumber(f.price_to_nav, locale, { digits: 2 }) : "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Yield 12 meses</dt>
              <dd className="num font-medium text-foreground">{f.dividend_yield_12m ? `${formatNumber(f.dividend_yield_12m, locale, { digits: 1 })}%` : "—"}</dd>
            </div>
          </dl>
        )}
        {hasScore(signal) && <p className="line-clamp-3 text-xs text-muted-foreground">{signal.justification}</p>}
        {signal.data_quality !== "valid" && <p className="text-xs font-medium text-warning">{signal.quality_reasons[0] ?? "Dados insuficientes."} Compra e venda suspensas.</p>}
      </button>
    </Card>
  );
}

export function B3SignalDetail({ signal, locale, showLink = true }: { signal: B3Signal; locale: Locale; showLink?: boolean }) {
  const currency = signal.currency as Currency;
  const sector = sectorLabel(signal.sector);
  const change =
    signal.current_price && Number(signal.reference_price) > 0
      ? (Number(signal.current_price) / Number(signal.reference_price) - 1) * 100
      : null;
  return (
    <div className="flex flex-col gap-5 px-4 pb-6">
      <SheetHeader className="px-0">
        <SheetTitle className="flex items-center gap-2">
          {signal.asset.symbol} <ClassificationBadge value={signal.classification} />
        </SheetTitle>
        <SheetDescription>
          {signal.asset.name}
          {sector && ` · ${sector}`}
        </SheetDescription>
      </SheetHeader>
      <B3SignalBody signal={signal} locale={locale} />
      <p className="text-xs text-subtle-foreground">
        Pregão de {formatDateTime(signal.candle_time, locale, "UTC", { dateStyle: "short" })} · fechamento de referência {formatPrice(signal.reference_price, currency, locale)}
        {change !== null && <> ({formatPercent(change, locale)} desde então)</>} · estratégia {signal.strategy_key} v{signal.strategy_version}
      </p>
      {showLink && (
        <Link href={`/b3/${signal.asset.symbol}`} className="inline-flex items-center gap-1 text-sm font-medium text-primary-ink">
          Ver página do ativo <ArrowRight className="size-4" />
        </Link>
      )}
    </div>
  );
}

/** Justification, fundamentals, components, risks and scope: shared by the sheet and the asset page. */
export function B3SignalBody({ signal, locale }: { signal: B3Signal; locale: Locale }) {
  const f = signal.fundamentals;
  const currency = signal.currency as Currency;
  return (
    <>
      <DataQualityNotice signal={signal} />
      {hasScore(signal) ? (
        <div className="flex items-center gap-4">
          <ScoreGauge score={signal.score} classification={signal.classification} />
          <p className="text-sm text-foreground">{signal.justification}</p>
        </div>
      ) : (
        <p className="text-sm text-foreground">Sem P/VP e rendimentos não há score para este fundo: mais da metade do cálculo depende deles.</p>
      )}
      {f && (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg bg-muted p-3 text-sm">
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
