"use client";

import { cn } from "cn";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Search, Star } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { FavoriteStar } from "@/components/analysis/watchlist-button";
import { AssetIcon } from "@/components/common/asset-icon";
import { ChangeBadge } from "@/components/common/change-badge";
import { DataStatus } from "@/components/common/data-status";
import { PageHeader } from "@/components/common/page-header";
import { EmptyState, ErrorState } from "@/components/common/states";
import { AssetList } from "@/components/market/asset-list";
import { CurrencyToggle } from "@/components/market/currency-toggle";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { Asset, Currency, Locale, SortKey } from "@/lib/api/types";
import { formatMoney, formatNumber, formatPercent, formatPrice } from "@/lib/format";
import { useWatchlists } from "@/lib/analysis-queries";
import { usePreferences, useAssets } from "@/lib/queries";

const PAGE_SIZE = 50;
const ALL_ASSETS = "all";

const SORT_LABELS: Record<SortKey, string> = {
  rank: "Ranking",
  market_cap: "Capitalização",
  price: "Preço",
  change_24h: "Variação 24h",
  change_7d: "Variação 7d",
  volume: "Volume 24h",
  name: "Nome",
};

// Ranking and name read naturally ascending; numeric columns are most useful descending first.
const DEFAULT_ORDER: Record<SortKey, "asc" | "desc"> = {
  rank: "asc",
  name: "asc",
  market_cap: "desc",
  price: "desc",
  change_24h: "desc",
  change_7d: "desc",
  volume: "desc",
};

function useMarketParams() {
  const params = useSearchParams();
  const prefs = usePreferences();
  const sort = (params.get("ordenar") as SortKey | null) ?? "rank";
  const validSort: SortKey = sort in SORT_LABELS ? sort : "rank";
  const order = params.get("ordem") === "desc" ? "desc" : params.get("ordem") === "asc" ? "asc" : DEFAULT_ORDER[validSort];
  const currencyParam = params.get("moeda");
  const currency: Currency = currencyParam === "USD" || currencyParam === "BRL" ? currencyParam : prefs.currency;
  return {
    q: params.get("q") ?? "",
    sort: validSort,
    order: order as "asc" | "desc",
    page: Math.max(1, Number(params.get("pagina")) || 1),
    currency,
    locale: prefs.locale,
    timeZone: prefs.timeZone,
  };
}

export function MarketView() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { q, sort, order, page, currency, locale, timeZone } = useMarketParams();
  const [search, setSearch] = useState(q);

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  };

  // Debounce typing into the URL (source of truth for shareable, back-button friendly state).
  useEffect(() => {
    if (search === q) return;
    const id = setTimeout(() => update({ q: search.trim() || null, pagina: null }), 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const watchlists = useWatchlists();
  const listParam = searchParams.get("lista");
  const watchlistId = watchlists.data?.some((w) => w.id === listParam) ? (listParam ?? undefined) : undefined;
  const query = useAssets({ currency, q, sort, order, page, pageSize: PAGE_SIZE, watchlistId });
  const data = query.data;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  const setSort = (key: SortKey) => {
    const nextOrder = key === sort ? (order === "asc" ? "desc" : "asc") : DEFAULT_ORDER[key];
    update({ ordenar: key === "rank" && nextOrder === "asc" ? null : key, ordem: nextOrder === DEFAULT_ORDER[key] ? null : nextOrder, pagina: null });
  };

  return (
    <>
      <PageHeader
        title="Mercado"
        description="As 100 maiores criptomoedas por capitalização, atualizadas continuamente."
        actions={<CurrencyToggle value={currency} onChange={(c) => update({ moeda: c })} />}
      />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle-foreground" />
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por nome ou símbolo"
            aria-label="Buscar ativo"
            className="h-10 bg-surface pl-9"
            maxLength={64}
          />
        </div>
        {/* Phones: list and sort side by side under the search; wider screens keep one row. */}
        <div className="grid grid-cols-2 gap-2 sm:contents">
        <Select value={watchlistId ?? ALL_ASSETS} onValueChange={(v) => update({ lista: v === ALL_ASSETS ? null : v, pagina: null })}>
          <SelectTrigger className="h-10 w-full bg-surface sm:w-48" aria-label="Lista">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_ASSETS}>Todos os ativos</SelectItem>
            {watchlists.data?.map((w) => (
              <SelectItem key={w.id} value={w.id}>
                {w.name} ({w.asset_ids.length})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="md:hidden">
          <Select value={`${sort}:${order}`} onValueChange={(v) => {
            const [key, ord] = v.split(":") as [SortKey, "asc" | "desc"];
            update({ ordenar: key === "rank" ? null : key, ordem: ord === DEFAULT_ORDER[key] ? null : ord, pagina: null });
          }}>
            <SelectTrigger className="h-10 w-full bg-surface" aria-label="Ordenar por">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(SORT_LABELS) as SortKey[]).flatMap((key) =>
                (["desc", "asc"] as const).map((ord) => (
                  <SelectItem key={`${key}:${ord}`} value={`${key}:${ord}`}>
                    {SORT_LABELS[key]} {ord === "asc" ? "↑" : "↓"}
                  </SelectItem>
                )),
              )}
            </SelectContent>
          </Select>
        </div>
        </div>
      </div>

      <Card className="gap-0 py-0">
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : data && data.items.length === 0 ? (
          watchlistId && !q ? (
            <EmptyState icon={Star} title="Lista vazia" description="Toque na estrela de um ativo para acompanhá-lo nesta lista." />
          ) : (
            <EmptyState icon={Search} title="Nenhum ativo encontrado" description={`Nada corresponde a “${q}”. Tente outro nome ou símbolo.`} />
          )
        ) : (
          <>
            <div className="px-4 md:hidden">
              <AssetList assets={data?.items} currency={currency} locale={locale} loading={!data} rows={10} showRank />
            </div>
            <div className="hidden md:block">
              <AssetTable
                assets={data?.items}
                currency={currency}
                locale={locale}
                sort={sort}
                order={order}
                onSort={setSort}
                stale={query.isPlaceholderData}
              />
            </div>
          </>
        )}
      </Card>

      <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        {data ? <DataStatus status={data.status} locale={locale} timeZone={timeZone} /> : <span />}
        {data && totalPages > 1 && (
          <div className="flex items-center gap-2 self-end">
            <span className="num text-xs text-muted-foreground">
              Página {page} de {totalPages}
            </span>
            <Button variant="outline" size="icon-sm" disabled={page <= 1} onClick={() => update({ pagina: page - 1 > 1 ? String(page - 1) : null })} aria-label="Página anterior">
              <ChevronLeft />
            </Button>
            <Button variant="outline" size="icon-sm" disabled={page >= totalPages} onClick={() => update({ pagina: String(page + 1) })} aria-label="Próxima página">
              <ChevronRight />
            </Button>
          </div>
        )}
      </div>
    </>
  );
}

type Column = {
  key: string;
  label: string;
  sortKey?: SortKey;
  className?: string;
  render: (asset: Asset, ctx: { currency: Currency; locale: Locale }) => React.ReactNode;
};

const COLUMNS: Column[] = [
  {
    key: "fav",
    label: "",
    className: "w-10",
    render: (a) => <FavoriteStar assetId={a.id} />,
  },
  {
    key: "rank",
    label: "#",
    sortKey: "rank",
    className: "w-12 text-right",
    render: (a) => <span className="text-subtle-foreground">{a.market_cap_rank ?? "—"}</span>,
  },
  {
    key: "asset",
    label: "Ativo",
    sortKey: "name",
    className: "text-left",
    render: (a) => (
      <Link href={`/mercado/${a.slug}`} className="flex items-center gap-3 after:absolute after:inset-0">
        <AssetIcon src={a.image_url} symbol={a.symbol} size={24} />
        <span className="truncate font-medium text-foreground">{a.name}</span>
        <span className="text-xs text-muted-foreground">{a.symbol}</span>
      </Link>
    ),
  },
  { key: "price", label: "Preço", sortKey: "price", className: "text-right", render: (a, c) => <span className="font-medium text-foreground">{formatPrice(a.price, c.currency, c.locale)}</span> },
  { key: "24h", label: "24h", sortKey: "change_24h", className: "text-right", render: (a, c) => <ChangeBadge value={a.change_pct_24h} locale={c.locale} /> },
  { key: "7d", label: "7d", sortKey: "change_7d", className: "text-right", render: (a, c) => <ChangeBadge value={a.change_pct_7d} locale={c.locale} /> },
  { key: "cap", label: "Capitalização", sortKey: "market_cap", className: "text-right hidden lg:table-cell", render: (a, c) => formatMoney(a.market_cap, c.currency, c.locale, { compact: true }) },
  { key: "vol", label: "Volume 24h", sortKey: "volume", className: "text-right hidden lg:table-cell", render: (a, c) => formatMoney(a.total_volume, c.currency, c.locale, { compact: true }) },
  { key: "supply", label: "Oferta circulante", className: "text-right hidden 2xl:table-cell", render: (a, c) => `${formatNumber(a.circulating_supply, c.locale, { compact: true })} ${a.symbol}` },
  { key: "ath", label: "Máx. histórica", className: "text-right hidden xl:table-cell", render: (a, c) => formatPrice(a.ath, c.currency, c.locale) },
  {
    key: "athdist",
    label: "Dist. da máx.",
    className: "text-right hidden xl:table-cell",
    render: (a, c) => <span className={cn(Number(a.ath_change_pct) > -10 ? "text-foreground" : "text-muted-foreground")}>{formatPercent(a.ath_change_pct, c.locale, 1)}</span>,
  },
];

function AssetTable({
  assets,
  currency,
  locale,
  sort,
  order,
  onSort,
  stale,
}: {
  assets: Asset[] | undefined;
  currency: Currency;
  locale: Locale;
  sort: SortKey;
  order: "asc" | "desc";
  onSort: (key: SortKey) => void;
  stale: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className={cn("num w-full text-sm transition-opacity", stale && "opacity-60")}>
        <thead>
          <tr className="border-b border-border text-xs text-muted-foreground">
            {COLUMNS.map((col) => {
              const active = col.sortKey === sort;
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={active ? (order === "asc" ? "ascending" : "descending") : undefined}
                  className={cn("h-11 px-3 font-medium whitespace-nowrap first:pl-5 last:pr-5", col.className)}
                >
                  {col.sortKey ? (
                    <button
                      type="button"
                      onClick={() => onSort(col.sortKey!)}
                      className={cn("inline-flex items-center gap-1 hover:text-foreground", active && "text-foreground")}
                    >
                      {col.label}
                      {active && (order === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {assets
            ? assets.map((asset) => (
                <tr key={asset.id} className="relative border-b border-border transition-colors last:border-0 hover:bg-card-hover">
                  {COLUMNS.map((col) => (
                    <td key={col.key} className={cn("h-14 px-3 whitespace-nowrap text-muted-foreground first:pl-5 last:pr-5", col.className)}>
                      {col.render(asset, { currency, locale })}
                    </td>
                  ))}
                </tr>
              ))
            : Array.from({ length: 12 }, (_, i) => (
                <tr key={i} className="border-b border-border">
                  {COLUMNS.map((col) => (
                    <td key={col.key} className={cn("h-14 px-3 first:pl-5 last:pr-5", col.className)}>
                      <Skeleton className={cn("h-4", col.key === "asset" ? "w-36" : "ml-auto w-16")} />
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}
