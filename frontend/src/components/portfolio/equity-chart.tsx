"use client";

import { cn } from "cn";
import {
  AreaSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  LineSeries,
  LineStyle,
  type IChartApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import type { Locale, Performance, SeriesPoint } from "@/lib/api/types";
import { formatMoney } from "@/lib/format";

type Mode = "value" | "return";
type Range = "30" | "90" | "365" | "all";

const COLORS = {
  value: "#6366F1",
  invested: "#94A3B8",
  btc: "#F59E0B",
  eth: "#8B5CF6",
  grid: "rgba(148, 163, 184, 0.08)",
  text: "#94A3B8",
  inflow: "#22C55E",
  outflow: "#EF4444",
};

function toTime(day: string): UTCTimestamp {
  return (Date.parse(`${day}T00:00:00Z`) / 1000) as UTCTimestamp;
}

/** Portfolio evolution (value vs. net invested, with flow markers) or TWR vs. BTC/ETH. */
export function EquityChart({ performance, locale }: { performance: Performance | undefined; locale: Locale }) {
  const [mode, setMode] = useState<Mode>("value");
  const [range, setRange] = useState<Range>("90");
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const points = useMemo(() => {
    const series = performance?.series ?? [];
    if (range === "all") return series;
    return series.slice(-Number(range));
  }, [performance, range]);

  useEffect(() => {
    const el = container.current;
    if (!el || points.length < 2 || !performance) return;
    const currency = performance.currency;
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: COLORS.text, fontFamily: "var(--font-inter)", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: COLORS.grid } },
      // Headroom keeps the top axis label inside the canvas.
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { horzLine: { labelBackgroundColor: "#151D28" }, vertLine: { labelBackgroundColor: "#151D28" } },
      localization: {
        locale,
        priceFormatter:
          mode === "value"
            ? (v: number) => formatMoney(v, currency, locale, { compact: true })
            : (v: number) => `${v.toLocaleString(locale, { maximumFractionDigits: 1 })}%`,
      },
      handleScroll: false,
      handleScale: false,
    });
    chartRef.current = chart;

    if (mode === "value") {
      const area = chart.addSeries(AreaSeries, {
        lineColor: COLORS.value,
        topColor: "rgba(99, 102, 241, 0.28)",
        bottomColor: "rgba(99, 102, 241, 0.02)",
        lineWidth: 2,
        priceLineVisible: false,
      });
      area.setData(points.map((p) => ({ time: toTime(p.day), value: Number(p.value) })));
      const invested = chart.addSeries(LineSeries, {
        color: COLORS.invested,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      invested.setData(points.map((p) => ({ time: toTime(p.day), value: Number(p.net_invested) })));
      const markers: SeriesMarker<Time>[] = points
        .filter((p) => Number(p.flow) !== 0)
        .map((p) => {
          const inflow = Number(p.flow) > 0;
          return {
            time: toTime(p.day),
            position: inflow ? "belowBar" : "aboveBar",
            shape: inflow ? "arrowUp" : "arrowDown",
            color: inflow ? COLORS.inflow : COLORS.outflow,
            // On narrow charts the words overlap the line; the arrows alone still mark the flows.
            text: el.clientWidth >= 480 ? (inflow ? "Aporte" : "Retirada") : "",
          };
        });
      createSeriesMarkers(area, markers);
    } else {
      const lines: [keyof SeriesPoint, string, number][] = [
        ["twr_pct", COLORS.value, 2],
        ["btc_pct", COLORS.btc, 1],
        ["eth_pct", COLORS.eth, 1],
      ];
      for (const [key, color, width] of lines) {
        const series = chart.addSeries(LineSeries, { color, lineWidth: width as 1 | 2, priceLineVisible: false });
        // Rebase each line to 0% at the first visible day so ranges compare fairly.
        const first = points.find((p) => p[key] !== null)?.[key];
        if (first === undefined || first === null) continue;
        const base = 1 + Number(first) / 100;
        series.setData(
          points
            .filter((p) => p[key] !== null)
            .map((p) => ({ time: toTime(p.day), value: ((1 + Number(p[key]) / 100) / base - 1) * 100 })),
        );
      }
    }
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [points, mode, locale, performance]);

  const estimated = points.some((p) => p.estimated);

  return (
    <Card className="gap-3">
      <CardHeader className="flex items-center justify-between gap-3">
        <CardTitle className="font-heading text-sm font-medium">Evolução da carteira</CardTitle>
        <CardAction>
          <Segmented
            label="Visualização"
            value={mode}
            onChange={setMode}
            options={[
              { value: "value", label: "Patrimônio", short: "Valor" },
              { value: "return", label: "Rentabilidade", short: "Retorno" },
            ]}
          />
        </CardAction>
      </CardHeader>
      <CardContent>
        {!performance ? (
          <Skeleton className="h-64 w-full rounded-lg" />
        ) : points.length < 2 ? (
          <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-border-strong text-center text-sm text-muted-foreground">
            O gráfico aparece a partir do segundo dia de histórico da carteira.
          </div>
        ) : (
          <div ref={container} className="h-64 w-full md:h-72" />
        )}
        {/* Period under the chart, full width: where the thumb is (as in Apple's Stocks). */}
        <Segmented
          label="Período"
          value={range}
          onChange={setRange}
          className="mt-3 flex w-full *:flex-1"
          options={[
            { value: "30", label: "30D" },
            { value: "90", label: "90D" },
            { value: "365", label: "1A" },
            { value: "all", label: "Tudo" },
          ]}
        />
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {mode === "value" ? (
            <>
              <Legend color={COLORS.value} label="Patrimônio" />
              <Legend color={COLORS.invested} label="Capital investido líquido" dashed />
            </>
          ) : (
            <>
              <Legend color={COLORS.value} label="Carteira (TWR)" />
              <Legend color={COLORS.btc} label="Bitcoin" />
              <Legend color={COLORS.eth} label="Ethereum" />
            </>
          )}
          <span className="ml-auto">Fechamentos diários (UTC)</span>
        </div>
        {performance && (!performance.history_complete || estimated) && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-warning">
            <TriangleAlert className="size-3.5" />
            {performance.history_start && performance.inception_date && performance.history_start > performance.inception_date
              ? "Histórico de preços disponível apenas para os últimos 365 dias; rentabilidade desde o início não pode ser calculada."
              : "Parte do histórico de preços ainda está sendo carregada; alguns pontos usam o preço da última transação."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-0.5 w-4 rounded-full", dashed && "border-t border-dashed bg-transparent")} style={dashed ? { borderColor: color } : { backgroundColor: color }} />
      {label}
    </span>
  );
}
