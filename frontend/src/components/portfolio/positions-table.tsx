"use client";

import { Hint } from "@/components/common/hint";
import { cn } from "cn";
import Link from "next/link";

import { AssetIcon } from "@/components/common/asset-icon";
import { ChangeBadge } from "@/components/common/change-badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { Currency, Locale, Position } from "@/lib/api/types";
import { formatMoney, formatNumber, formatPercent, formatPrice, trendOf } from "@/lib/format";

const TREND = { up: "text-success", down: "text-destructive", flat: "text-muted-foreground" } as const;

function Pnl({ value, pct, currency, locale }: { value: string; pct: string | null; currency: Currency; locale: Locale }) {
  const trend = trendOf(value);
  const money = formatMoney(value, currency, locale);
  return (
    <div className={cn("text-right", TREND[trend])}>
      <div className="font-medium">{trend === "up" ? `+${money}` : money}</div>
      {pct !== null && <div className="text-xs">{formatPercent(pct, locale)}</div>}
    </div>
  );
}

function Price({ position, currency, locale }: { position: Position; currency: Currency; locale: Locale }) {
  if (!position.price_estimated) return <>{formatPrice(position.price, currency, locale)}</>;
  return (
    <Hint className="text-warning" content={<>Ainda não há cotação ao vivo para este ativo; o valor usa o preço da última transação.</>}>
      sem cotação
    </Hint>
  );
}

export function PositionsTable({
  positions,
  currency,
  locale,
  loading,
  compact = false,
}: {
  positions: Position[] | undefined;
  currency: Currency;
  locale: Locale;
  loading?: boolean;
  /** Dashboard variant: fewer columns. */
  compact?: boolean;
}) {
  if (loading || !positions) {
    return (
      <div className="space-y-3 p-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  return (
    <>
      {/* Phones: stacked cards with the essentials. */}
      <ul className="divide-y divide-border md:hidden">
        {positions.map((p) => (
          <li key={p.asset.id}>
            <Link href={`/mercado/${p.asset.slug}`} className="pressable flex items-center gap-3 px-5 py-3.5 active:bg-white/4">
              <AssetIcon src={p.asset.image_url} symbol={p.asset.symbol} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">{p.asset.name}</p>
                <p className="num text-xs text-muted-foreground">
                  {formatNumber(p.quantity, locale, { digits: 8 })} {p.asset.symbol} ·{" "}
                  {formatNumber(p.weight_pct, locale, { digits: 1 })}%
                </p>
              </div>
              <div className="num text-right">
                <p className="text-sm font-medium text-foreground">{formatMoney(p.market_value, currency, locale)}</p>
                <ChangeBadge value={p.unrealized_pct} locale={locale} className="text-xs" />
              </div>
            </Link>
          </li>
        ))}
      </ul>

      <div className="hidden overflow-x-auto md:block">
        <table className="num w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs text-muted-foreground">
              <th className="h-11 px-3 pl-5 text-left font-medium">Ativo</th>
              <th className="px-3 text-right font-medium">Preço</th>
              {!compact && <th className="hidden px-3 text-right font-medium lg:table-cell">24h</th>}
              <th className="px-3 text-right font-medium">Quantidade</th>
              {!compact && <th className="hidden px-3 text-right font-medium xl:table-cell">Preço médio</th>}
              {!compact && <th className="hidden px-3 text-right font-medium 2xl:table-cell">Investido</th>}
              <th className="px-3 text-right font-medium whitespace-nowrap">Valor de mercado</th>
              <th className="px-3 text-right font-medium">Resultado</th>
              {!compact && <th className="hidden px-3 text-right font-medium 2xl:table-cell">Realizado</th>}
              <th className="px-3 pr-5 text-right font-medium">Peso</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.asset.id} className="border-b border-border transition-colors last:border-0 hover:bg-card-hover">
                <td className="h-14 px-3 pl-5">
                  <Link href={`/mercado/${p.asset.slug}`} className="flex items-center gap-3">
                    <AssetIcon src={p.asset.image_url} symbol={p.asset.symbol} size={24} />
                    <span className="font-medium text-foreground">{p.asset.name}</span>
                    <span className="text-xs text-muted-foreground">{p.asset.symbol}</span>
                  </Link>
                </td>
                <td className="px-3 text-right text-foreground">
                  <Price position={p} currency={currency} locale={locale} />
                </td>
                {!compact && (
                  <td className="hidden px-3 text-right lg:table-cell">
                    <ChangeBadge value={p.change_pct_24h} locale={locale} />
                  </td>
                )}
                <td className="px-3 text-right text-muted-foreground">{formatNumber(p.quantity, locale, { digits: 8 })}</td>
                {!compact && (
                  <td className="hidden px-3 text-right text-muted-foreground xl:table-cell">
                    {formatPrice(p.average_cost, currency, locale)}
                  </td>
                )}
                {!compact && (
                  <td className="hidden px-3 text-right text-muted-foreground 2xl:table-cell">
                    {formatMoney(p.cost_basis, currency, locale)}
                  </td>
                )}
                <td className="px-3 text-right font-medium text-foreground">{formatMoney(p.market_value, currency, locale)}</td>
                <td className="px-3">
                  <Pnl value={p.unrealized_pnl} pct={p.unrealized_pct} currency={currency} locale={locale} />
                </td>
                {!compact && (
                  <td className={cn("hidden px-3 text-right 2xl:table-cell", TREND[trendOf(p.realized_pnl)])}>
                    {formatMoney(p.realized_pnl, currency, locale)}
                  </td>
                )}
                <td className="px-3 pr-5 text-right">
                  <div className="ml-auto flex w-20 items-center justify-end gap-2">
                    <span className="h-1 flex-1 overflow-hidden rounded-full bg-accent">
                      <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.min(100, Number(p.weight_pct))}%` }} />
                    </span>
                    <span className="w-10 text-xs text-muted-foreground">{formatNumber(p.weight_pct, locale, { digits: 1 })}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
