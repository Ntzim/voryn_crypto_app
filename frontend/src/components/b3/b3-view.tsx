"use client";

import { cn } from "cn";
import { ArrowDown, ArrowUp, CalendarOff, ChevronLeft, ChevronRight, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { ChangeBadge } from "@/components/common/change-badge";
import { PageHeader } from "@/components/common/page-header";
import { EmptyState, ErrorState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/client";
import type { Currency, ExchangeAsset, ExchangeAssetType, ExchangeOverview, ExchangeSort, Locale } from "@/lib/api/types";
import { useB3Assets, useB3Overview } from "@/lib/b3-queries";
import { formatMoney, formatPrice } from "@/lib/format";
import { usePreferences } from "@/lib/queries";

import { ASSET_TYPE_LABEL, B3DataNote, B3SessionBadge } from "./b3-status";

const PAGE_SIZE = 50;
const ALL = "all";

const TYPE_OPTIONS = [
  { value: ALL, label: "Todos" },
  { value: "STOCK", label: "Ações" },
  { value: "FII", label: "FIIs" },
  { value: "ETF", label: "ETFs" },
  { value: "BDR", label: "BDRs" },
];

// Most traded first: market cap would lead with BDRs, whose figure is the foreign company's
// global value (AAPL34 at R$ 27 tri), not what trades here.
const DEFAULT_SORT: ExchangeSort = "traded_value";

const SORT_LABELS: Record<ExchangeSort, string> = {
  market_cap: "Capitalização",
  traded_value: "Valor negociado",
  change: "Variação do dia",
  price: "Preço",
  name: "Nome",
};

const DEFAULT_ORDER: Record<ExchangeSort, "asc" | "desc"> = {
  market_cap: "desc",
  traded_value: "desc",
  change: "desc",
  price: "desc",
  name: "asc",
};

function money(asset: ExchangeAsset) {
  return asset.currency as Currency;
}

export function B3View() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { locale, timeZone } = usePreferences();

  const q = searchParams.get("q") ?? "";
  const typeParam = searchParams.get("tipo");
  const assetType = TYPE_OPTIONS.some((o) => o.value === typeParam && o.value !== ALL) ? (typeParam as ExchangeAssetType) : null;
  const sortParam = searchParams.get("ordenar") as ExchangeSort | null;
  const sort: ExchangeSort = sortParam && sortParam in SORT_LABELS ? sortParam : DEFAULT_SORT;
  const orderParam = searchParams.get("ordem");
  const order = orderParam === "asc" || orderParam === "desc" ? orderParam : DEFAULT_ORDER[sort];
  const page = Math.max(1, Number(searchParams.get("pagina")) || 1);
  const [search, setSearch] = useState(q);

  const update = (changes: Record<string, string | null>) => {
    // Read the URL now, not from the render: the debounced search runs 300 ms later and would
    // otherwise undo a filter changed in between.
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    // Client-only filters: no server round trip, and the URL is current for the next update.
    window.history.replaceState(null, "", `${pathname}${next.size ? `?${next}` : ""}`);
  };

  useEffect(() => {
    if (search === q) return;
    const id = setTimeout(() => update({ q: search.trim() || null, pagina: null }), 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const overview = useB3Overview();
  const list = useB3Assets({ q, assetType, sort, order, page, pageSize: PAGE_SIZE });
  const data = list.data;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  const setSort = (key: ExchangeSort) => {
    const nextOrder = key === sort ? (order === "asc" ? "desc" : "asc") : DEFAULT_ORDER[key];
    update({ ordenar: key === DEFAULT_SORT ? null : key, ordem: nextOrder === DEFAULT_ORDER[key] ? null : nextOrder, pagina: null });
  };

  if (isApiError(overview.error, "market_disabled") || isApiError(list.error, "market_disabled")) {
    return (
      <>
        <PageHeader title="Bolsa B3" description="Ações, FIIs, ETFs e BDRs listados na bolsa brasileira." />
        <Card>
          <EmptyState icon={CalendarOff} title="B3 ainda não disponível" description="Este mercado ainda não foi liberado na Voryn." />
        </Card>
      </>
    );
  }

  const status = overview.data?.status ?? data?.status;

  return (
    <>
      <PageHeader title="Bolsa B3" description="Ações, FIIs, ETFs e BDRs listados na bolsa brasileira." />
      {status ? <B3SessionBadge status={status} locale={locale} timeZone={timeZone} className="mb-5" /> : <Skeleton className="mb-5 h-7 w-72" />}

      <OverviewSection overview={overview.data} error={overview.error} onRetry={() => overview.refetch()} locale={locale} />

      <h2 className="mt-8 mb-3 font-heading text-lg font-semibold text-foreground">Ativos</h2>
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="relative flex-1 lg:max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle-foreground" />
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por código ou nome"
            aria-label="Buscar ativo"
            className="h-10 bg-surface pl-9"
            maxLength={64}
          />
        </div>
        <div className="scroll-row -mx-4 px-4 sm:mx-0 sm:px-0">
          <Segmented label="Tipo de ativo" value={assetType ?? ALL} onChange={(v) => update({ tipo: v === ALL ? null : v, pagina: null })} options={TYPE_OPTIONS} />
        </div>
        <div className="md:hidden">
          <Select
            value={`${sort}:${order}`}
            onValueChange={(v) => {
              const [key, ord] = v.split(":") as [ExchangeSort, "asc" | "desc"];
              update({ ordenar: key === DEFAULT_SORT ? null : key, ordem: ord === DEFAULT_ORDER[key] ? null : ord, pagina: null });
            }}
          >
            <SelectTrigger className="h-10 w-full bg-surface" aria-label="Ordenar por">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(SORT_LABELS) as ExchangeSort[]).flatMap((key) =>
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

      <Card className="gap-0 py-0">
        {list.isError ? (
          <ErrorState error={list.error} onRetry={() => list.refetch()} />
        ) : data && data.items.length === 0 ? (
          q ? (
            <EmptyState icon={Search} title="Nenhum ativo encontrado" description={`Nada corresponde a “${q}”. Tente outro código ou nome.`} />
          ) : (
            <EmptyState icon={Search} title="Sem ativos ainda" description="O catálogo da B3 aparece aqui depois da primeira sincronização." />
          )
        ) : (
          <>
            <div className="px-4 md:hidden">
              <MobileList assets={data?.items} locale={locale} />
            </div>
            <div className="hidden md:block">
              <AssetTable assets={data?.items} locale={locale} sort={sort} order={order} onSort={setSort} stale={list.isPlaceholderData} />
            </div>
          </>
        )}
      </Card>

      <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        {status ? <B3DataNote status={status} locale={locale} timeZone={timeZone} /> : <span />}
        {data && totalPages > 1 && (
          <div className="flex items-center gap-2 self-end">
            <span className="num text-xs whitespace-nowrap text-muted-foreground">
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

// --------------------------------------------------------------------------- overview

const MOVER_TABS = [
  { value: "gainers", label: "Altas" },
  { value: "losers", label: "Baixas" },
  { value: "traded", label: "Mais negociados" },
] as const;

function OverviewSection({
  overview,
  error,
  onRetry,
  locale,
}: {
  overview: ExchangeOverview | undefined;
  error: unknown;
  onRetry: () => void;
  locale: Locale;
}) {
  const [tab, setTab] = useState<(typeof MOVER_TABS)[number]["value"]>("gainers");

  if (error) {
    return (
      <Card>
        <ErrorState error={error} onRetry={onRetry} />
      </Card>
    );
  }
  if (!overview) {
    return (
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-64 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl lg:col-span-2" />
      </div>
    );
  }

  const movers = tab === "gainers" ? overview.top_gainers : tab === "losers" ? overview.top_losers : overview.most_traded;
  const reference = overview.reference;
  const breadth = overview.advancers + overview.decliners;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <CardContent className="flex h-full flex-col gap-5">
          {reference ? (
            <Link href={`/b3/${reference.symbol}`} className="block rounded-lg outline-offset-4">
              <p className="text-xs text-muted-foreground">Referência do Ibovespa</p>
              <p className="mt-1 flex items-baseline gap-2">
                <span className="num font-heading text-2xl font-semibold text-foreground">{formatPrice(reference.price, money(reference), locale)}</span>
                <ChangeBadge value={reference.change_pct} locale={locale} className="text-sm" />
              </p>
              {/* Index values are licensed data: this is the ETF's quote, and it says so. */}
              <p className="mt-1 text-xs text-muted-foreground">{reference.symbol}, ETF que acompanha o índice. Não é o valor do Ibovespa.</p>
            </Link>
          ) : (
            <p className="text-sm text-muted-foreground">A referência do índice aparece após a primeira sincronização.</p>
          )}
          <div className="mt-auto">
            <p className="text-xs text-muted-foreground">Altas × baixas (ativos com liquidez)</p>
            <p className="num mt-1 text-lg font-semibold">
              <span className="text-success">{overview.advancers}</span>
              <span className="text-muted-foreground"> / </span>
              <span className="text-destructive">{overview.decliners}</span>
            </p>
            {breadth > 0 && (
              <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                <span className="bg-success" style={{ width: `${(overview.advancers / breadth) * 100}%` }} />
                <span className="flex-1 bg-destructive" />
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        <CardContent>
          <div className="scroll-row mb-2">
            <Segmented label="Destaques" value={tab} onChange={setTab} options={[...MOVER_TABS]} />
          </div>
          {movers.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Nenhum ativo neste destaque agora.</p>
          ) : (
            <ul className="divide-y divide-border">
              {movers.map((asset) => (
                <li key={asset.id}>
                  <AssetRow asset={asset} locale={locale} detail={tab === "traded" ? formatMoney(asset.traded_value, money(asset), locale, { compact: true }) : undefined} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function AssetRow({ asset, locale, detail }: { asset: ExchangeAsset; locale: Locale; detail?: string }) {
  return (
    <Link href={`/b3/${asset.symbol}`} className="pressable -mx-2 flex items-center gap-3 rounded-xl px-2 py-3 transition-colors hover:bg-card-hover active:bg-card-hover">
      <AssetIcon src={asset.image_url} symbol={asset.symbol} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{asset.symbol}</p>
        <p className="truncate text-xs text-muted-foreground">{asset.name}</p>
      </div>
      <div className="text-right">
        <p className="num text-sm font-medium text-foreground">{formatPrice(asset.price, money(asset), locale)}</p>
        {detail ? <p className="num text-xs text-muted-foreground">{detail}</p> : <ChangeBadge value={asset.change_pct} locale={locale} className="text-xs" />}
      </div>
    </Link>
  );
}

// --------------------------------------------------------------------------- listing

function MobileList({ assets, locale }: { assets: ExchangeAsset[] | undefined; locale: Locale }) {
  if (!assets) {
    return (
      <ul className="divide-y divide-border">
        {Array.from({ length: 10 }, (_, i) => (
          <li key={i} className="flex items-center gap-3 py-3">
            <Skeleton className="size-7 rounded-full" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-4 w-20" />
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ul className="divide-y divide-border">
      {assets.map((asset) => (
        <li key={asset.id}>
          <AssetRow asset={asset} locale={locale} />
        </li>
      ))}
    </ul>
  );
}

type Column = {
  key: string;
  label: string;
  sortKey?: ExchangeSort;
  className?: string;
  render: (asset: ExchangeAsset, locale: Locale) => React.ReactNode;
};

const COLUMNS: Column[] = [
  {
    key: "asset",
    label: "Ativo",
    sortKey: "name",
    className: "text-left",
    render: (a) => (
      <Link href={`/b3/${a.symbol}`} className="flex items-center gap-3 after:absolute after:inset-0">
        <AssetIcon src={a.image_url} symbol={a.symbol} size={24} />
        <span className="font-medium text-foreground">{a.symbol}</span>
        <span className="max-w-64 truncate text-xs text-muted-foreground">{a.name}</span>
      </Link>
    ),
  },
  { key: "type", label: "Tipo", className: "text-left hidden lg:table-cell", render: (a) => ASSET_TYPE_LABEL[a.asset_type] ?? a.asset_type },
  { key: "price", label: "Preço", sortKey: "price", className: "text-right", render: (a, l) => <span className="font-medium text-foreground">{formatPrice(a.price, money(a), l)}</span> },
  { key: "change", label: "Dia", sortKey: "change", className: "text-right", render: (a, l) => <ChangeBadge value={a.change_pct} locale={l} /> },
  { key: "traded", label: "Negociado", sortKey: "traded_value", className: "text-right", render: (a, l) => formatMoney(a.traded_value, money(a), l, { compact: true }) },
  { key: "cap", label: "Capitalização", sortKey: "market_cap", className: "text-right hidden lg:table-cell", render: (a, l) => formatMoney(a.market_cap, money(a), l, { compact: true }) },
];

function AssetTable({
  assets,
  locale,
  sort,
  order,
  onSort,
  stale,
}: {
  assets: ExchangeAsset[] | undefined;
  locale: Locale;
  sort: ExchangeSort;
  order: "asc" | "desc";
  onSort: (key: ExchangeSort) => void;
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
                    <button type="button" onClick={() => onSort(col.sortKey!)} className={cn("inline-flex items-center gap-1 hover:text-foreground", active && "text-foreground")}>
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
                      {col.render(asset, locale)}
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
