/**
 * Display formatting only. Monetary values arrive from the API as decimal strings and are
 * never used for arithmetic in the browser; Number() here only feeds Intl formatting.
 */
import type { Currency, Locale } from "@/lib/api/types";

type Numeric = string | number | null | undefined;

const cache = new Map<string, Intl.NumberFormat>();

function formatter(locale: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = locale + JSON.stringify(options);
  let f = cache.get(key);
  if (!f) {
    f = new Intl.NumberFormat(locale, options);
    cache.set(key, f);
  }
  return f;
}

function toNumber(value: Numeric): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export const EMPTY = "—";

/** Prices: 2 decimals above 1, significant digits below (micro-cap tokens). */
export function formatPrice(value: Numeric, currency: Currency, locale: Locale = "pt-BR"): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  const abs = Math.abs(n);
  const options: Intl.NumberFormatOptions =
    abs >= 1 || abs === 0
      ? { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }
      : { style: "currency", currency, minimumSignificantDigits: 2, maximumSignificantDigits: 4 };
  return formatter(locale, options).format(n);
}

export function formatMoney(
  value: Numeric,
  currency: Currency,
  locale: Locale = "pt-BR",
  { compact = false }: { compact?: boolean } = {},
): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  return formatter(locale, {
    style: "currency",
    currency,
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 2 : 2,
    minimumFractionDigits: compact ? 0 : 2,
  }).format(n);
}

export function formatNumber(
  value: Numeric,
  locale: Locale = "pt-BR",
  { compact = false, digits = 2 }: { compact?: boolean; digits?: number } = {},
): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  return formatter(locale, {
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: digits,
  }).format(n);
}

/** Signed percentage: "+2,51%" / "−1,20%". */
export function formatPercent(value: Numeric, locale: Locale = "pt-BR", digits = 2): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  return formatter(locale, {
    style: "percent",
    signDisplay: "exceptZero",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n / 100);
}

export type Trend = "up" | "down" | "flat";

export function trendOf(value: Numeric): Trend {
  const n = toNumber(value);
  if (n === null || n === 0) return "flat";
  return n > 0 ? "up" : "down";
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

export function formatRelative(iso: string | null | undefined, locale: Locale = "pt-BR", now = Date.now()): string {
  if (!iso) return EMPTY;
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, size] of RELATIVE_UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return locale === "pt-BR" ? "agora" : "just now";
}

export function formatDateTime(
  iso: string | null | undefined,
  locale: Locale = "pt-BR",
  timeZone?: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" },
): string {
  if (!iso) return EMPTY;
  return new Intl.DateTimeFormat(locale, { ...options, timeZone }).format(new Date(iso));
}
