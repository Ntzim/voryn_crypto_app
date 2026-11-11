"use client";

import { CandlestickSeries, ColorType, createChart, HistogramSeries } from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { ExchangeHistory, Locale } from "@/lib/api/types";
import { useChartPalette } from "@/lib/chart-theme";

/** Daily candles and volume. Days are plain dates, so no timezone shift applies. */
export function B3PriceChart({ bars, locale }: { bars: ExchangeHistory["bars"]; locale: Locale }) {
  const container = useRef<HTMLDivElement>(null);
  const palette = useChartPalette();

  useEffect(() => {
    const el = container.current;
    if (!el || !palette || bars.length === 0) return;
    const p = palette;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: p.text,
        fontFamily: "var(--font-inter)",
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: p.grid } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { horzLine: { labelBackgroundColor: p.label }, vertLine: { labelBackgroundColor: p.label } },
      localization: { locale },
      handleScroll: false,
      handleScale: false,
    });
    chart
      .addSeries(CandlestickSeries, {
        upColor: p.up,
        downColor: p.down,
        borderVisible: false,
        wickUpColor: p.up,
        wickDownColor: p.down,
        priceLineColor: p.primary,
      })
      .setData(
        bars.map((b) => ({
          time: b.day,
          open: Number(b.open),
          high: Number(b.high),
          low: Number(b.low),
          close: Number(b.close),
        })),
      );
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    volume.setData(
      bars.filter((b) => b.volume !== null).map((b) => ({
        time: b.day,
        value: Number(b.volume),
        color: p.alpha(Number(b.close) >= Number(b.open) ? p.up : p.down, 0.3),
      })),
    );
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, locale, palette]);

  return <div ref={container} className="h-72 w-full md:h-96" />;
}
