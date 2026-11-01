import { useMemo } from "react";

import { useTheme } from "@/lib/theme";

/**
 * Chart colors resolved from the active theme's CSS tokens (globals.css).
 *
 * Canvas charts (lightweight-charts) and SVG presentation attributes (recharts) cannot use
 * CSS variables, so the tokens are read once per theme and handed over as plain colors.
 * Charts list the palette in their effect dependencies and redraw when the theme changes.
 */
export type ChartPalette = {
  text: string;
  grid: string;
  separator: string;
  /** crosshair axis label background */
  label: string;
  up: string;
  down: string;
  neutral: string;
  emphasis: string;
  primary: string;
  violet: string;
  green: string;
  amber: string;
  sky: string;
  /** categorical series, in order */
  series: string[];
  tooltip: { background: string; border: string; text: string };
  alpha: (color: string, opacity: number) => string;
};

/** `rgba()` from a hex token; lightweight-charts parses rgba but not every CSS color syntax. */
export function withAlpha(hex: string, opacity: number): string {
  const value = hex.trim().replace("#", "");
  const full = value.length === 3 ? [...value].map((c) => c + c).join("") : value.slice(0, 6);
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
  if ([r, g, b].some(Number.isNaN)) return hex;
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

export function readChartPalette(style: Pick<CSSStyleDeclaration, "getPropertyValue">): ChartPalette {
  const token = (name: string) => style.getPropertyValue(`--${name}`).trim();
  const foreground = token("foreground");
  const palette = {
    text: token("chart-axis"),
    grid: withAlpha(foreground, 0.06),
    separator: withAlpha(foreground, 0.1),
    label: token("chart-label"),
    up: token("chart-up"),
    down: token("chart-down"),
    neutral: token("chart-neutral"),
    emphasis: token("chart-emphasis"),
    primary: token("chart-1"),
    violet: token("chart-2"),
    green: token("chart-3"),
    amber: token("chart-4"),
    sky: token("chart-5"),
    tooltip: { background: token("popover"), border: token("border-strong"), text: token("popover-foreground") },
    alpha: withAlpha,
  };
  return {
    ...palette,
    series: [palette.primary, palette.violet, palette.sky, palette.green, palette.amber, palette.neutral],
  };
}

/** Palette of the active theme; `null` until the theme is known (server, hydration). */
export function useChartPalette(): ChartPalette | null {
  const resolved = useTheme()?.resolved;
  return useMemo(
    // `resolved` is the cache key: the computed tokens change exactly when it does.
    () => (resolved ? readChartPalette(getComputedStyle(document.documentElement)) : null),
    [resolved],
  );
}
