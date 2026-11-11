"use client";

import { cn } from "cn";
import { ChevronDown, LayoutGrid, List, Radar, Search, Table } from "lucide-react";
import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode } from "react";

import { ErrorState } from "@/components/common/states";
import { EvidenceCount, ScoreBar, SignalBadge, SignalDot, TrendDots, Chip, signalLabel } from "@/components/signals/signal-primitives";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import type { Locale, SignalClass } from "@/lib/api/types";
import { formatNumber, formatPrice } from "@/lib/format";
import {
  distribution,
  filterOpportunities,
  sortOpportunities,
  strongest,
  type Opportunity,
  type SortKey,
} from "@/lib/opportunity";

import { AssetAvatar, OpportunityDetail, capitalize, signed } from "./opportunity-detail";

const SIGNALS: SignalClass[] = ["buy_potential", "attention", "neutral", "sell_potential"];
const SIGNAL_PARAM: Record<SignalClass, string> = { buy_potential: "compra", attention: "atencao", neutral: "neutro", sell_potential: "venda" };
const PARAM_SIGNAL = Object.fromEntries(Object.entries(SIGNAL_PARAM).map(([k, v]) => [v, k])) as Record<string, SignalClass>;
const BAR_COLOR: Record<SignalClass, string> = {
  buy_potential: "bg-signal-buy",
  attention: "bg-signal-watch",
  neutral: "bg-signal-neutral-dot",
  sell_potential: "bg-signal-sell",
};
const SORT_LABEL: Record<SortKey, string> = { score: "Score (maior)", ticker: "Ticker (A–Z)", trend: "Tendência", price: "Preço" };
const VIEW_KEY = "voryn-opportunities-view";

type View = "tabela" | "lista" | "cards";
const VIEWS: View[] = ["tabela", "lista", "cards"];
const VIEW_ICON = { tabela: Table, lista: List, cards: LayoutGrid } as const;

export type BoardProps = {
  title: string;
  description: string;
  /** what is analysed, plural ("ações", "FIIs", "criptoativos") */
  noun: string;
  items: Opportunity[] | undefined;
  error: unknown;
  onRetry: () => void;
  locale: Locale;
  /** tabs between markets, next to the title */
  tabs?: ReactNode;
  /** pills and text under the title (delay, update time) */
  meta: ReactNode;
  /** text behind "Limites da análise" */
  limits: string;
  /** extra controls for this market (timeframe, watchlist) */
  toolbarExtra?: ReactNode;
  footnote: string;
};

const subscribeNever = () => () => {};

const DESKTOP = "(min-width: 1024px)";

/** Panel on desktop, full-screen view below it: only one of the two may be open. */
function useIsDesktop(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const media = window.matchMedia(DESKTOP);
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    },
    () => window.matchMedia(DESKTOP).matches,
    () => true,
  );
}

function readStoredView(): View | null {
  try {
    const saved = localStorage.getItem(VIEW_KEY);
    return VIEWS.includes(saved as View) ? (saved as View) : null;
  } catch {
    return null;
  }
}

/** URL is the source of truth: shareable, and the back button restores the same view. */
function useBoardState() {
  const params = useSearchParams();
  const pathname = usePathname();
  const signal = PARAM_SIGNAL[params.get("sinal") ?? ""] ?? null;
  const sortParam = params.get("ordem") as SortKey | null;
  const sort: SortKey = sortParam && sortParam in SORT_LABEL ? sortParam : "score";
  const query = params.get("q") ?? "";
  const selected = params.get("ativo");
  const viewParam = params.get("vista");
  // Saved choice, read only in the browser (the server renders the default table).
  const storedView = useSyncExternalStore(subscribeNever, readStoredView, () => null);
  const view: View = VIEWS.includes(viewParam as View) ? (viewParam as View) : (storedView ?? "tabela");

  const update = useCallback(
    (changes: Record<string, string | null>) => {
      // Read the URL now, not from the render: a debounced search must not undo a newer change.
      const next = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      }
      window.history.replaceState(null, "", `${pathname}${next.size ? `?${next}` : ""}`);
    },
    [pathname],
  );
  const setView = (next: View) => {
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      // Storage blocked: the URL still carries the choice for this visit.
    }
    update({ vista: next });
  };
  return { signal, sort, query, selected, view, update, setView };
}

export function OpportunitiesBoard(props: BoardProps) {
  const { items, locale } = props;
  const { signal, sort, query, selected, view, update, setView } = useBoardState();
  const [search, setSearch] = useState(query);
  const [limitsOpen, setLimitsOpen] = useState(false);

  useEffect(() => {
    if (search === query) return;
    const id = setTimeout(() => update({ q: search.trim() || null }), 200);
    return () => clearTimeout(id);
  }, [search, query, update]);

  const dist = useMemo(() => distribution(items ?? []), [items]);
  const visible = useMemo(() => sortOpportunities(filterOpportunities(items ?? [], signal, query), sort), [items, signal, query, sort]);
  const highlights = useMemo(
    () => ({ buy: strongest(items ?? [], "buy_potential"), sell: strongest(items ?? [], "sell_potential") }),
    [items],
  );
  const current = items?.find((o) => o.symbol === selected) ?? null;
  const desktop = useIsDesktop();
  const select = (symbol: string | null) => update({ ativo: symbol });

  return (
    <>
      <header className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl leading-[30px] font-semibold text-foreground">{props.title}</h1>
          <p className="mt-1 max-w-2xl text-[13px] leading-5 text-muted-foreground">{props.description}</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
            {props.meta}
            <button
              type="button"
              aria-expanded={limitsOpen}
              aria-controls="analysis-limits"
              onClick={() => setLimitsOpen((o) => !o)}
              className="inline-flex items-center gap-1 font-medium text-primary-ink"
            >
              Limites da análise <ChevronDown className={cn("size-3.5 transition-transform", limitsOpen && "rotate-180")} strokeWidth={1.5} />
            </button>
          </div>
          {limitsOpen && (
            <p id="analysis-limits" className="mt-2 max-w-3xl rounded-[10px] border border-border bg-surface p-3 text-xs leading-[18px] text-muted-foreground">
              {props.limits}
            </p>
          )}
        </div>
        {props.tabs}
      </header>

      {props.error ? (
        <div className="rounded-2xl border border-border bg-surface">
          <ErrorState error={props.error} onRetry={props.onRetry} />
        </div>
      ) : (
        <>
          <DistributionCard dist={dist} noun={props.noun} signal={signal} onSignal={(s) => update({ sinal: s ? SIGNAL_PARAM[s] : null })} loading={!items} />
          <HighlightsCard buy={highlights.buy} sell={highlights.sell} loading={!items} onSelect={select} locale={locale} />

          <div className="mt-5 mb-3 flex flex-col gap-3 md:flex-row md:items-center">
            <div className="relative md:w-72">
              <label htmlFor="opportunity-filter" className="sr-only">Filtrar por ticker ou empresa</label>
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle-foreground" strokeWidth={1.5} aria-hidden />
              <Input id="opportunity-filter" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filtrar por ticker ou empresa" className="h-10 rounded-[10px] bg-surface pl-9" maxLength={64} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={sort} onValueChange={(v) => update({ ordem: v === "score" ? null : v })}>
                <SelectTrigger className="h-10 w-48 rounded-[10px] bg-surface" aria-label="Ordenar por">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(SORT_LABEL) as SortKey[]).map((key) => (
                    <SelectItem key={key} value={key}>
                      {SORT_LABEL[key]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {props.toolbarExtra}
            </div>
            <div className="flex items-center gap-3 md:ml-auto">
              <span className="num text-xs whitespace-nowrap text-subtle-foreground" aria-live="polite">
                {items ? `${visible.length} ${visible.length === 1 ? "ativo" : "ativos"} na lista` : ""}
              </span>
              <div role="group" aria-label="Visualização" className="hidden rounded-[10px] bg-surface-sunken p-0.5 md:inline-flex">
                {VIEWS.map((v) => {
                  const Icon = VIEW_ICON[v];
                  return (
                  <button
                    key={v}
                    type="button"
                    aria-pressed={view === v}
                    onClick={() => setView(v)}
                    className={cn("inline-flex h-8 items-center gap-1.5 rounded-[8px] px-3 text-xs font-medium", view === v ? "bg-surface-raised text-foreground" : "text-muted-foreground hover:text-foreground")}
                  >
                    <Icon className="size-4" strokeWidth={1.5} />
                    {capitalize(v)}
                  </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-start gap-5">
            <div className="min-w-0 flex-[1_1_640px]">
              {!items ? (
                <ListSkeleton />
              ) : visible.length === 0 ? (
                <div className="flex flex-col items-center rounded-2xl border border-border bg-surface px-6 py-12 text-center">
                  <Radar className="mb-3 size-5 text-muted-foreground" strokeWidth={1.5} aria-hidden />
                  <p className="text-sm font-semibold text-foreground">{items.length ? "Nenhum ativo neste filtro" : "Sinais ainda não gerados"}</p>
                  <p className="mt-1 text-[13px] text-muted-foreground">
                    {items.length ? "Ajuste a busca ou escolha outro sinal acima." : "Os sinais são calculados a cada candle fechado para os ativos acompanhados."}
                  </p>
                </div>
              ) : (
                <>
                  <MobileList items={visible} selected={selected} onSelect={select} locale={locale} />
                  <div className="hidden md:block">
                    {view === "tabela" ? (
                      <OpportunityTable items={visible} selected={selected} onSelect={select} locale={locale} footnote={props.footnote} />
                    ) : view === "lista" ? (
                      <OpportunityList items={visible} selected={selected} onSelect={select} locale={locale} />
                    ) : (
                      <OpportunityCards items={visible} selected={selected} onSelect={select} locale={locale} />
                    )}
                  </div>
                </>
              )}
            </div>

            {current && (
              <aside className="sticky top-20 hidden w-full max-w-[400px] flex-[1_1_340px] rounded-2xl border border-border bg-surface p-5 shadow-card lg:block">
                <OpportunityDetail item={current} locale={locale} onClose={() => select(null)} />
              </aside>
            )}
          </div>

          {/* Below lg the detail is its own full-screen view, with a back button. */}
          <Sheet open={Boolean(current) && !desktop} onOpenChange={(open) => !open && select(null)}>
            <SheetContent side="bottom" className="h-dvh max-h-dvh overflow-y-auto rounded-none p-4 pb-28 lg:hidden" showCloseButton={false}>
              <SheetTitle className="sr-only">{current ? `Detalhe de ${current.symbol}` : "Detalhe"}</SheetTitle>
              <SheetDescription className="sr-only">Score, evidências, riscos e condição de invalidação.</SheetDescription>
              {current && <OpportunityDetail item={current} locale={locale} onClose={() => select(null)} variant="page" />}
            </SheetContent>
          </Sheet>
        </>
      )}
    </>
  );
}

function DistributionCard({
  dist,
  noun,
  signal,
  onSignal,
  loading,
}: {
  dist: ReturnType<typeof distribution>;
  noun: string;
  signal: SignalClass | null;
  onSignal: (signal: SignalClass | null) => void;
  loading: boolean;
}) {
  return (
    <section aria-labelledby="distribution-title" className="rounded-2xl border border-border bg-surface p-5 shadow-card">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 id="distribution-title" className="text-[13px] font-semibold text-foreground">Distribuição dos sinais</h2>
        <span className="num text-xs text-subtle-foreground">{loading ? "" : `${dist.total} ${noun} ${noun === "ações" ? "analisadas" : "analisados"}`}</span>
      </div>
      {loading ? (
        <Skeleton className="h-2.5 w-full rounded-full" />
      ) : (
        <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
          {SIGNALS.filter((s) => dist[s] > 0).map((s) => (
            <span key={s} className={cn("h-full transition-opacity", BAR_COLOR[s], signal && signal !== s && "opacity-25")} style={{ flexGrow: dist[s] }} />
          ))}
        </div>
      )}
      <div role="group" aria-label="Filtrar por sinal" className="scroll-row mt-4 -mx-1 gap-2 px-1 md:flex-wrap md:overflow-visible">
        <Chip active={!signal} onClick={() => onSignal(null)}>
          Todos <span className="num text-subtle-foreground">{dist.total}</span>
        </Chip>
        {SIGNALS.map((s) => (
          <Chip key={s} active={signal === s} onClick={() => onSignal(signal === s ? null : s)}>
            <SignalDot value={s} />
            {signalLabel(s)} <span className="num text-subtle-foreground">{dist[s]}</span>
          </Chip>
        ))}
      </div>
    </section>
  );
}

/** The strongest readings each way, side by side: where the evidence is clearest right now. */
function HighlightsCard({
  buy,
  sell,
  loading,
  onSelect,
  locale,
}: {
  buy: Opportunity[];
  sell: Opportunity[];
  loading: boolean;
  onSelect: (symbol: string) => void;
  locale: Locale;
}) {
  const column = (title: string, items: Opportunity[], empty: string, tone: string) => (
    <div className="min-w-0">
      <h3 className={cn("mb-2 text-[13px] font-semibold", tone)}>{title}</h3>
      {loading ? (
        <Skeleton className="h-28 w-full rounded-[10px]" />
      ) : items.length === 0 ? (
        <p className="rounded-[10px] bg-background p-3 text-xs text-muted-foreground">{empty}</p>
      ) : (
        <ol className="space-y-1">
          {items.map((o, i) => (
            <li key={o.id}>
              <button type="button" onClick={() => onSelect(o.symbol)} className="flex w-full items-center gap-3 rounded-[10px] px-2 py-2 text-left hover:bg-card-hover">
                <span className="num w-4 text-xs text-subtle-foreground">{i + 1}</span>
                <AssetAvatar item={o} size={30} />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-foreground">{o.symbol}</span>
                  <EvidenceCount favorable={o.favorable} against={o.against} criteria={o.criteria} className="block truncate" />
                </span>
                <span className="text-right">
                  <span className="num block text-sm font-bold text-foreground">{formatNumber(o.score, locale, { digits: 0 })}</span>
                  <span className="num block text-[11px] text-muted-foreground">{o.price === null ? "—" : formatPrice(o.price, o.currency, locale)}</span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
  return (
    <section aria-labelledby="highlights-title" className="mt-5 rounded-2xl border border-border bg-surface p-5 shadow-card">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="highlights-title" className="text-[13px] font-semibold text-foreground">Principais ativos com potencial</h2>
        <span className="text-xs text-subtle-foreground">Leituras mais fortes do último candle, só com dados completos</span>
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        {column("Potencial de compra", buy, "Nenhum ativo com potencial de compra agora. Quando os indicadores se alinharem para alta, eles aparecem aqui.", "text-signal-buy")}
        {column("Potencial de venda", sell, "Nenhum ativo com potencial de venda agora.", "text-signal-sell")}
      </div>
    </section>
  );
}

function TrendCell({ item }: { item: Opportunity }) {
  if (!item.trend) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <TrendDots saldo={item.trend.saldo} total={item.trend.total} direction={item.trend.direction} />
      <span className="text-xs text-muted-foreground">
        {capitalize(item.trend.direction)} · {signed(item.trend.saldo)}/{item.trend.total}
      </span>
    </span>
  );
}

function VolatilityText({ item }: { item: Opportunity }) {
  if (!item.volatility) return <span className="text-muted-foreground">—</span>;
  const { level, percentile } = item.volatility;
  return (
    <span className={cn("whitespace-nowrap", level === "elevada" ? "text-signal-watch" : "text-muted-foreground")}>
      {capitalize(level)}
      {percentile !== undefined && ` · P${percentile}`}
    </span>
  );
}

function OpportunityTable({
  items,
  selected,
  onSelect,
  locale,
  footnote,
}: {
  items: Opportunity[];
  selected: string | null;
  onSelect: (symbol: string | null) => void;
  locale: Locale;
  footnote: string;
}) {
  const body = useRef<HTMLTableSectionElement>(null);
  // Arrow keys move the selection, Enter opens it, Esc closes the detail.
  const onKeyDown = (event: KeyboardEvent<HTMLTableSectionElement>) => {
    const index = items.findIndex((o) => o.symbol === selected);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = items[Math.max(0, Math.min(items.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))];
      if (next) {
        onSelect(next.symbol);
        body.current?.querySelector<HTMLButtonElement>(`[data-symbol="${next.symbol}"]`)?.focus();
      }
    } else if (event.key === "Escape") {
      onSelect(null);
    }
  };
  const money = (o: Opportunity) => (o.price === null ? "—" : formatPrice(o.price, o.currency, locale));
  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-[13px]">
          <thead>
            <tr className="border-b border-border text-left text-xs text-subtle-foreground">
              <th scope="col" className="h-11 px-4 font-medium">Ativo</th>
              <th scope="col" className="px-3 font-medium">Sinal</th>
              <th scope="col" className="px-3 font-medium">Score</th>
              <th scope="col" className="px-3 text-right font-medium">Preço</th>
              <th scope="col" className="px-3 font-medium">Tendência</th>
              <th scope="col" className="px-3 text-right font-medium">RSI</th>
              <th scope="col" className="px-3 text-right font-medium">ATR</th>
              <th scope="col" className="px-4 font-medium">Volatilidade</th>
            </tr>
          </thead>
          <tbody ref={body} onKeyDown={onKeyDown}>
            {items.map((o) => {
              const active = o.symbol === selected;
              return (
                <tr
                  key={o.id}
                  onClick={() => onSelect(o.symbol)}
                  className={cn(
                    "cursor-pointer border-b border-surface-sunken transition-colors last:border-0",
                    active ? "bg-brand-soft shadow-[inset_3px_0_0_var(--brand)]" : "hover:bg-card-hover",
                  )}
                >
                  <td className="px-4 py-2.5">
                    <button type="button" data-symbol={o.symbol} onClick={(e) => { e.stopPropagation(); onSelect(o.symbol); }} aria-pressed={active} className="flex items-center gap-3 rounded-[8px] text-left">
                      <AssetAvatar item={o} />
                      <span className="min-w-0">
                        <span className="block font-semibold text-foreground">{o.symbol}</span>
                        <span className="block max-w-44 truncate text-xs text-muted-foreground">{o.name}</span>
                      </span>
                    </button>
                  </td>
                  <td className="px-3">
                    <SignalBadge value={o.signal} />
                    {o.dataQuality === "valid" && <span className="num mt-1 block text-[11px] text-subtle-foreground">{o.favorable}/{o.criteria} a favor</span>}
                  </td>
                  <td className="px-3">
                    {o.hasScore ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="num w-7 text-sm font-bold text-foreground">{formatNumber(o.score, locale, { digits: 0 })}</span>
                        <ScoreBar score={o.score} />
                      </span>
                    ) : (
                      <span className="text-xs text-subtle-foreground">Sem score</span>
                    )}
                  </td>
                  <td className="num px-3 text-right text-foreground">{money(o)}</td>
                  <td className="px-3"><TrendCell item={o} /></td>
                  <td className="num px-3 text-right text-muted-foreground">{o.rsi !== undefined ? formatNumber(o.rsi, locale, { digits: 1 }) : "—"}</td>
                  <td className="num px-3 text-right text-muted-foreground">{o.atrPct !== undefined ? `${formatNumber(o.atrPct, locale, { digits: 2 })}%` : "—"}</td>
                  <td className="px-4 text-xs"><VolatilityText item={o} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-border px-4 py-3 text-xs text-subtle-foreground">{footnote}</p>
    </div>
  );
}

function OpportunityCards({ items, selected, onSelect, locale }: { items: Opportunity[]; selected: string | null; onSelect: (symbol: string) => void; locale: Locale }) {
  return (
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4">
      {items.map((o) => (
        <li key={o.id}>
          <button
            type="button"
            aria-pressed={o.symbol === selected}
            onClick={() => onSelect(o.symbol)}
            className={cn(
              "flex h-full w-full flex-col gap-3 rounded-2xl border bg-surface p-5 text-left shadow-card transition-[transform,box-shadow] motion-safe:hover:-translate-y-px motion-safe:hover:shadow-card-hover",
              o.symbol === selected ? "border-brand" : "border-border",
            )}
          >
            <span className="flex items-center gap-3">
              <AssetAvatar item={o} />
              <span className="min-w-0 flex-1">
                <span className="block font-semibold text-foreground">{o.symbol}</span>
                <span className="block truncate text-xs text-muted-foreground">{o.name}</span>
              </span>
              <span className="text-right">
                <span className="num block text-[26px] leading-none font-bold text-foreground">{o.hasScore ? formatNumber(o.score, locale, { digits: 0 }) : "—"}</span>
                <span className="text-[11px] text-subtle-foreground">score</span>
              </span>
            </span>
            <span className="flex items-center justify-between gap-2">
              <SignalBadge value={o.signal} />
              <span className="num text-sm font-medium text-foreground">{o.price === null ? "—" : formatPrice(o.price, o.currency, locale)}</span>
            </span>
            <span className="grid grid-cols-3 gap-2 text-[11px]">
              <span className="rounded-[10px] bg-background p-2">
                <span className="block text-subtle-foreground">Tendência</span>
                <span className="num font-semibold text-foreground">{o.trend ? `${signed(o.trend.saldo)}/${o.trend.total}` : "—"}</span>
              </span>
              <span className="rounded-[10px] bg-background p-2">
                <span className="block text-subtle-foreground">ATR</span>
                <span className="num font-semibold text-foreground">{o.atrPct !== undefined ? `${formatNumber(o.atrPct, locale, { digits: 1 })}%` : "—"}</span>
              </span>
              <span className="rounded-[10px] bg-background p-2">
                <span className="block text-subtle-foreground">Volatilidade</span>
                <span className="font-semibold text-foreground">{o.volatility ? capitalize(o.volatility.level) : "—"}</span>
              </span>
            </span>
            <span className="text-xs text-muted-foreground">{o.summary}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function OpportunityList({ items, selected, onSelect, locale }: { items: Opportunity[]; selected: string | null; onSelect: (symbol: string) => void; locale: Locale }) {
  return (
    <ul className="divide-y divide-surface-sunken overflow-hidden rounded-2xl border border-border bg-surface shadow-card">
      {items.map((o) => {
        const active = o.symbol === selected;
        return (
          <li key={o.id}>
            <button
              type="button"
              aria-pressed={active}
              onClick={() => onSelect(o.symbol)}
              className={cn(
                "grid w-full grid-cols-[180px_1fr_auto] items-center gap-4 px-4 py-3 text-left transition-colors",
                active ? "bg-brand-soft shadow-[inset_3px_0_0_var(--brand)]" : "hover:bg-card-hover",
              )}
            >
              <span className="flex min-w-0 items-center gap-3">
                <AssetAvatar item={o} />
                <span className="min-w-0">
                  <span className="block font-semibold text-foreground">{o.symbol}</span>
                  <span className="block truncate text-xs text-muted-foreground">{o.name}</span>
                </span>
              </span>
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <SignalBadge value={o.signal} />
                  {o.dataQuality === "valid" ? (
                    <EvidenceCount favorable={o.favorable} against={o.against} criteria={o.criteria} />
                  ) : (
                    <span className="text-xs text-signal-watch">Dados insuficientes: compra e venda suspensas</span>
                  )}
                </span>
                <span className="mt-1 block text-[13px] leading-5 text-muted-foreground">{o.summary}</span>
              </span>
              <span className="flex flex-col items-end gap-1">
                {o.hasScore ? (
                  <span className="inline-flex items-center gap-2">
                    <span className="num text-sm font-bold text-foreground">{formatNumber(o.score, locale, { digits: 0 })}</span>
                    <ScoreBar score={o.score} />
                  </span>
                ) : (
                  <span className="text-xs text-subtle-foreground">Sem score</span>
                )}
                <span className="num text-xs text-muted-foreground">{o.price === null ? "—" : formatPrice(o.price, o.currency, locale)}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function MobileList({ items, selected, onSelect, locale }: { items: Opportunity[]; selected: string | null; onSelect: (symbol: string) => void; locale: Locale }) {
  return (
    <ul className="divide-y divide-surface-sunken overflow-hidden rounded-2xl border border-border bg-surface md:hidden">
      {items.map((o) => (
        <li key={o.id}>
          <button type="button" aria-pressed={o.symbol === selected} onClick={() => onSelect(o.symbol)} className="flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left">
            <AssetAvatar item={o} />
            <span className="min-w-0 flex-1">
              <span className="block font-semibold text-foreground">{o.symbol}</span>
              <span className="num block text-xs text-muted-foreground">{o.price === null ? "—" : formatPrice(o.price, o.currency, locale)}</span>
            </span>
            <SignalBadge value={o.signal} />
            <span className="num w-8 text-right text-sm font-bold text-foreground">{o.hasScore ? formatNumber(o.score, locale, { digits: 0 }) : "—"}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-2 rounded-2xl border border-border bg-surface p-4" role="status" aria-label="Carregando oportunidades">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-[34px] rounded-[10px]" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-5 w-28 rounded-[6px]" />
          <Skeleton className="ml-auto h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

