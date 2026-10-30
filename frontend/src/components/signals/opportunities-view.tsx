"use client";

import { cn } from "cn";
import { ArrowRight, Info, Radar } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { EmptyState, ErrorState } from "@/components/common/states";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useWatchlists } from "@/lib/analysis-queries";
import type { Signal, SignalClass, Timeframe } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { usePreferences } from "@/lib/queries";
import { SIGNAL_META, useSignalHistory, useSignals } from "@/lib/signal-queries";

import {
  ClassificationBadge,
  ComponentBars,
  RisksAndInvalidation,
  ScoreHistory,
  SignalProvenance,
  SignalSummaryRow,
} from "./signal-parts";

const CLASSES: SignalClass[] = ["buy_potential", "attention", "neutral", "sell_potential"];
const TIMEFRAMES: { value: Timeframe; label: string }[] = [
  { value: "1d", label: "Diário" },
  { value: "4h", label: "4 horas" },
];
const ALL = "all";

export function OpportunitiesView() {
  const { locale, timeZone } = usePreferences();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const timeframe: Timeframe = params.get("tf") === "4h" ? "4h" : "1d";
  const filter = (params.get("classe") as SignalClass | null) ?? null;
  const watchlists = useWatchlists();
  const listId = params.get("lista") ?? undefined;
  const validList = watchlists.data?.some((w) => w.id === listId) ? listId : undefined;
  const query = useSignals(timeframe, validList);
  const [open, setOpen] = useState<Signal | null>(null);

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  };

  const counts = useMemo(() => {
    const c = { buy_potential: 0, attention: 0, neutral: 0, sell_potential: 0 } as Record<SignalClass, number>;
    for (const s of query.data?.items ?? []) c[s.classification] += 1;
    return c;
  }, [query.data]);
  const items = (query.data?.items ?? []).filter((s) => !filter || s.classification === filter);
  const strategy = query.data?.strategy;

  return (
    <>
      <PageHeader
        title="Oportunidades"
        description="Sinais quantitativos transparentes: cada score vem com componentes, justificativa, riscos e condições de invalidação."
        actions={
          <div role="radiogroup" aria-label="Intervalo" className="inline-flex rounded-lg border border-border bg-surface p-0.5">
            {TIMEFRAMES.map((t) => (
              <button
                key={t.value}
                type="button"
                role="radio"
                aria-checked={timeframe === t.value}
                onClick={() => update({ tf: t.value === "1d" ? null : t.value })}
                className={cn("h-8 rounded-md px-3 text-xs font-medium", timeframe === t.value ? "bg-card text-foreground ring-1 ring-border-strong" : "text-muted-foreground hover:text-foreground")}
              >
                {t.label}
              </button>
            ))}
          </div>
        }
      />

      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-1.5">
          <FilterChip active={!filter} onClick={() => update({ classe: null })}>
            Todos <span className="num text-subtle-foreground">{query.data?.items.length ?? 0}</span>
          </FilterChip>
          {CLASSES.map((c) => (
            <FilterChip key={c} active={filter === c} onClick={() => update({ classe: filter === c ? null : c })}>
              <span className="size-2 rounded-full" style={{ backgroundColor: SIGNAL_META[c].color }} />
              {SIGNAL_META[c].label} <span className="num text-subtle-foreground">{counts[c]}</span>
            </FilterChip>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Select value={validList ?? ALL} onValueChange={(v) => update({ lista: v === ALL ? null : v })}>
            <SelectTrigger className="h-9 w-48 bg-surface" aria-label="Lista">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Todos os ativos</SelectItem>
              {watchlists.data?.map((w) => (
                <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {strategy && (
            <Tooltip>
              <TooltipTrigger className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                <Info className="size-3.5" /> Metodologia
              </TooltipTrigger>
              <TooltipContent className="max-w-80 space-y-1.5">
                <p className="font-medium">{strategy.name}</p>
                <p>
                  Pesos: tendência {strategy.weights_pct.trend}%, momentum {strategy.weights_pct.momentum}%, volume{" "}
                  {strategy.weights_pct.volume}%, volatilidade {strategy.weights_pct.volatility}%, suportes/resistências{" "}
                  {strategy.weights_pct.levels}%, mercado {strategy.weights_pct.market}%.
                </p>
                <p>
                  Score ≥ {formatNumber(strategy.buy_threshold, locale, { digits: 0 })}: potencial de compra · ≤{" "}
                  {formatNumber(strategy.sell_threshold, locale, { digits: 0 })}: potencial de venda.
                </p>
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      </div>

      {query.isError ? (
        <Card><ErrorState error={query.error} onRetry={() => query.refetch()} /></Card>
      ) : !query.data ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-48 rounded-xl" />)}
        </div>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={Radar}
            title="Nenhum sinal para os filtros escolhidos"
            description="Os sinais são gerados a cada candle fechado para os principais ativos e para os que você acompanha. Tente outro filtro ou intervalo."
          />
        </Card>
      ) : (
        <div className={cn("grid gap-4 md:grid-cols-2 xl:grid-cols-3", query.isPlaceholderData && "opacity-60")}>
          {items.map((signal) => (
            <button
              key={signal.id}
              type="button"
              onClick={() => setOpen(signal)}
              className="group rounded-xl border border-border bg-card p-4 text-left transition-colors hover:border-border-strong hover:bg-card-hover"
            >
              <SignalSummaryRow signal={signal} locale={locale} />
              <div className="mt-3 flex items-center justify-between">
                <ClassificationBadge value={signal.classification} />
                {signal.risks.length > 0 && (
                  <span className="text-xs text-warning">{signal.risks.length} risco(s)</span>
                )}
              </div>
              <p className="mt-3 line-clamp-3 text-sm text-muted-foreground">{signal.justification}</p>
            </button>
          ))}
        </div>
      )}

      {query.data && <p className="mt-5 text-xs text-subtle-foreground">{query.data.disclaimer}</p>}

      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
          {open && <SignalDetail signal={open} locale={locale} timeZone={timeZone} />}
        </SheetContent>
      </Sheet>
    </>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors",
        active ? "border-border-strong bg-card text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function SignalDetail({ signal, locale, timeZone }: { signal: Signal; locale: "pt-BR" | "en-US"; timeZone: string }) {
  const history = useSignalHistory(signal.asset.slug, signal.timeframe);
  return (
    <>
      <SheetHeader>
        <SheetTitle>{signal.asset.name}</SheetTitle>
        <SheetDescription className="sr-only">Detalhes do sinal</SheetDescription>
      </SheetHeader>
      <div className="space-y-6 px-4 pb-6">
        <SignalSummaryRow signal={signal} locale={locale} />
        <ClassificationBadge value={signal.classification} />
        <p className="text-sm text-foreground">{signal.justification}</p>
        <section>
          <h3 className="mb-3 text-sm font-medium">Composição do score</h3>
          <ComponentBars signal={signal} locale={locale} />
        </section>
        <RisksAndInvalidation signal={signal} />
        <section>
          <h3 className="mb-2 text-sm font-medium">Histórico do score</h3>
          <ScoreHistory points={history.data} loading={history.isPending} locale={locale} />
        </section>
        <SignalProvenance signal={signal} locale={locale} timeZone={timeZone} />
        <Link href={`/analise/${signal.asset.slug}?tf=${signal.timeframe}`} className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
          Abrir análise técnica <ArrowRight className="size-4" />
        </Link>
        <p className="text-xs text-subtle-foreground">
          O score mede o alinhamento de condições favoráveis segundo regras fixas; não é probabilidade de lucro nem recomendação.
        </p>
      </div>
    </>
  );
}
