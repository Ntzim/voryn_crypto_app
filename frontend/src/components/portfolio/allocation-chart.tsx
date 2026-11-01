"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { Locale, PortfolioSummary } from "@/lib/api/types";
import { useChartPalette } from "@/lib/chart-theme";
import { formatMoney, formatNumber } from "@/lib/format";

/** Categorical series tokens; the SVG needs resolved colors (see useChartPalette). */
const SWATCHES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-5)", "var(--chart-3)", "var(--chart-4)", "var(--chart-neutral)"];
const MAX_SLICES = 5;

export function AllocationChart({ summary, locale }: { summary: PortfolioSummary | undefined; locale: Locale }) {
  const palette = useChartPalette();
  const slices = (() => {
    if (!summary) return [];
    const positions = summary.positions;
    const top = positions.slice(0, MAX_SLICES).map((p) => ({
      name: p.asset.symbol,
      weight: Number(p.weight_pct),
      value: p.market_value,
    }));
    const rest = positions.slice(MAX_SLICES);
    if (rest.length) {
      top.push({
        name: "Outras",
        weight: rest.reduce((acc, p) => acc + Number(p.weight_pct), 0),
        value: "",
      });
    }
    return top;
  })();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Distribuição</CardTitle>
      </CardHeader>
      <CardContent>
        {!summary || !palette ? (
          <Skeleton className="mx-auto size-28 rounded-full sm:size-44" />
        ) : (
          <div className="flex items-center gap-5 lg:flex-col 2xl:flex-row">
            <div className="relative size-28 shrink-0 sm:size-44">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={slices}
                    dataKey="weight"
                    nameKey="name"
                    innerRadius="68%"
                    outerRadius="100%"
                    paddingAngle={slices.length > 1 ? 2 : 0}
                    stroke="none"
                    isAnimationActive={false}
                  >
                    {slices.map((s, i) => (
                      <Cell key={s.name} fill={palette.series[i % palette.series.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    cursor={false}
                    contentStyle={{ background: "var(--popover)", border: "1px solid var(--border-strong)", borderRadius: 8, fontSize: 12 }}
                    itemStyle={{ color: "var(--popover-foreground)" }}
                    formatter={(v) => `${formatNumber(Number(v), locale, { digits: 1 })}%`}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-[11px] text-muted-foreground">{summary.positions.length} {summary.positions.length === 1 ? "ativo" : "ativos"}</span>
              </div>
            </div>
            <ul className="w-full space-y-2.5">
              {slices.map((s, i) => (
                <li key={s.name} className="flex items-center gap-2.5 text-sm">
                  <span className="size-2.5 shrink-0 rounded-sm" style={{ backgroundColor: SWATCHES[i % SWATCHES.length] }} />
                  <span className="flex-1 font-medium text-foreground">{s.name}</span>
                  {s.value && (
                    <span className="num hidden text-xs text-muted-foreground sm:inline">
                      {formatMoney(s.value, summary.currency, locale, { compact: true })}
                    </span>
                  )}
                  <span className="num w-14 text-right text-muted-foreground">
                    {formatNumber(s.weight, locale, { digits: 1 })}%
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
