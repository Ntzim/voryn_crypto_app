"use client";

import Link from "next/link";

import { AssetIcon } from "@/components/common/asset-icon";
import { ChangeBadge } from "@/components/common/change-badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { Asset, Currency, Locale } from "@/lib/api/types";
import { formatPrice } from "@/lib/format";

/** Compact asset rows (dashboard widgets, mobile market list). */
export function AssetList({
  assets,
  currency,
  locale,
  loading,
  rows = 5,
  showRank = false,
}: {
  assets: Asset[] | undefined;
  currency: Currency;
  locale: Locale;
  loading?: boolean;
  rows?: number;
  showRank?: boolean;
}) {
  if (loading || !assets) {
    return (
      <ul className="divide-y divide-border">
        {Array.from({ length: rows }, (_, i) => (
          <li key={i} className="flex items-center gap-3 py-3">
            <Skeleton className="size-7 rounded-full" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="h-3 w-12" />
            </div>
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
          <Link
            href={`/mercado/${asset.slug}`}
            className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-3 transition-colors hover:bg-card-hover"
          >
            {showRank && (
              <span className="num w-5 text-right text-xs text-subtle-foreground">{asset.market_cap_rank ?? "—"}</span>
            )}
            <AssetIcon src={asset.image_url} symbol={asset.symbol} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-foreground">{asset.name}</p>
              <p className="text-xs text-muted-foreground">{asset.symbol}</p>
            </div>
            <div className="text-right">
              <p className="num text-sm font-medium text-foreground">{formatPrice(asset.price, currency, locale)}</p>
              <ChangeBadge value={asset.change_pct_24h} locale={locale} className="text-xs" />
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
