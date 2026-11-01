"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { Analysis, Locale } from "@/lib/api/types";
import { useChartPalette, type ChartPalette } from "@/lib/chart-theme";

export type Overlay = "ema9" | "ema21" | "ema50" | "ema200" | "bollinger" | "levels";
export type Oscillator = "rsi" | "macd";

export function overlayColors(p: ChartPalette): Record<Exclude<Overlay, "levels" | "bollinger">, string> {
  // EMA 200, the long trend, uses the strongest neutral of the theme (white or near-black).
  return { ema9: p.sky, ema21: p.violet, ema50: p.amber, ema200: p.emphasis };
}

/**
 * Lightweight Charts renders timestamps as UTC; shift them by the viewer's timezone offset
 * so the axis shows the user's local time (the library's recommended approach).
 */
function chartTime(iso: string, timeZone: string): UTCTimestamp {
  const date = new Date(iso);
  const local = new Date(date.toLocaleString("en-US", { timeZone }));
  const utc = new Date(date.toLocaleString("en-US", { timeZone: "UTC" }));
  return ((date.getTime() + (local.getTime() - utc.getTime())) / 1000) as UTCTimestamp;
}


export function CandleChart({
  analysis,
  overlays,
  oscillators,
  locale,
  timeZone,
  height = 460,
}: {
  analysis: Analysis;
  overlays: Set<Overlay>;
  oscillators: Set<Oscillator>;
  locale: Locale;
  timeZone: string;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const palette = useChartPalette();

  useEffect(() => {
    const el = container.current;
    if (!el || !palette) return;
    const p = palette;
    const UP = p.up;
    const DOWN = p.down;
    const GRID = p.grid;
    const emas = overlayColors(p);
    const intraday = ["15m", "1h", "4h"].includes(analysis.timeframe);
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: p.text,
        fontFamily: "var(--font-inter)",
        attributionLogo: false,
        panes: { separatorColor: p.separator, separatorHoverColor: p.alpha(p.primary, 0.3) },
      },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false, rightOffset: 4 },
      crosshair: { horzLine: { labelBackgroundColor: p.label }, vertLine: { labelBackgroundColor: p.label } },
      localization: { locale },
    });
    chartRef.current = chart;

    const times = analysis.candles.map((c) => chartTime(c.time, timeZone));
    const line = (values: (string | null)[]) =>
      values.flatMap((v, i) => (v === null ? [] : [{ time: times[i], value: Number(v) }]));

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceLineColor: p.primary,
    });
    candles.setData(
      analysis.candles.map((c, i) => ({
        time: times[i],
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
      })),
    );

    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(
      analysis.candles.map((c, i) => ({
        time: times[i],
        value: Number(c.volume),
        color: Number(c.close) >= Number(c.open) ? p.alpha(UP, 0.28) : p.alpha(DOWN, 0.28),
      })),
    );

    for (const key of ["ema9", "ema21", "ema50", "ema200"] as const) {
      if (!overlays.has(key)) continue;
      chart
        .addSeries(LineSeries, { color: emas[key], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
        .setData(line(analysis.indicators[key]));
    }
    if (overlays.has("bollinger")) {
      for (const key of ["bb_upper", "bb_lower"] as const) {
        chart
          .addSeries(LineSeries, { color: p.alpha(p.neutral, 0.7), lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
          .setData(line(analysis.indicators[key]));
      }
      chart
        .addSeries(LineSeries, { color: p.alpha(p.neutral, 0.45), lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
        .setData(line(analysis.indicators.sma20));
    }
    if (overlays.has("levels")) {
      for (const level of analysis.supports) {
        candles.createPriceLine({ price: Number(level.price), color: p.alpha(UP, 0.7), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: `S ${level.touches}×` });
      }
      for (const level of analysis.resistances) {
        candles.createPriceLine({ price: Number(level.price), color: p.alpha(DOWN, 0.7), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: `R ${level.touches}×` });
      }
    }

    let pane = 1;
    if (oscillators.has("rsi")) {
      const rsi = chart.addSeries(LineSeries, { color: p.violet, lineWidth: 1, priceLineVisible: false }, pane);
      rsi.setData(line(analysis.indicators.rsi));
      for (const [price, color] of [[70, p.alpha(DOWN, 0.5)], [30, p.alpha(UP, 0.5)]] as const) {
        rsi.createPriceLine({ price, color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
      }
      pane += 1;
    }
    if (oscillators.has("macd")) {
      chart
        .addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane)
        .setData(
          analysis.indicators.macd_hist.flatMap((v, i) =>
            v === null ? [] : [{ time: times[i], value: Number(v), color: Number(v) >= 0 ? p.alpha(UP, 0.5) : p.alpha(DOWN, 0.5) }],
          ),
        );
      chart.addSeries(LineSeries, { color: p.primary, lineWidth: 1, priceLineVisible: false }, pane).setData(line(analysis.indicators.macd));
      chart.addSeries(LineSeries, { color: p.amber, lineWidth: 1, priceLineVisible: false }, pane).setData(line(analysis.indicators.macd_signal));
    }
    const panes = chart.panes();
    panes.forEach((p, i) => p.setStretchFactor(i === 0 ? 3 : 1));

    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, times.length - 160), to: times.length + 4 });
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [analysis, overlays, oscillators, locale, timeZone, palette]);

  const extraPanes = oscillators.size;
  return <div ref={container} style={{ height: height + extraPanes * 120 }} className="w-full" />;
}


