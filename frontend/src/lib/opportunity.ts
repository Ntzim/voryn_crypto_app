import type { B3Signal, Signal, SignalClass } from "@/lib/api/types";

/**
 * View model for the opportunity list and detail, adapted from the signal contract without
 * changing the API. RSI and ATR come structured (`indicators`); trend balance, volatility level
 * and price levels only exist inside the engine's component sentences, so they are read from
 * there. Anything that cannot be read stays `undefined` and shows as "—": never guessed.
 */
export type Direction = "alta" | "baixa" | "indefinida";

export type Opportunity = {
  id: number;
  symbol: string;
  /** link target of the full analysis */
  href: string;
  name: string;
  imageUrl: string | null;
  market: "CRYPTO" | "B3";
  assetType: string;
  currency: "USD" | "BRL";
  score: number;
  signal: SignalClass;
  price: number | null;
  trend?: { saldo: number; total: number; direction: Direction };
  rsi?: number;
  atrPct?: number;
  volatility?: { level: "baixa" | "moderada" | "elevada"; percentile?: number; window?: number };
  support?: { value: number; distPct: number };
  resistance?: { value: number; distPct: number };
  /** the engine's one-sentence reading */
  summary: string;
  evidence: string[];
  risks: string[];
  invalidation: string;
  dataQuality: Signal["data_quality"];
  qualityReasons: string[];
  /** FIIs without P/VP and income have no meaningful score */
  hasScore: boolean;
  signalRaw: Signal | B3Signal;
};

/** "1.234,56" or "1234.56" → 1234.56 */
export function parseLocaleNumber(text: string): number | undefined {
  const cleaned = text.trim().replace(/\s/g, "");
  if (!cleaned) return undefined;
  const normalized = cleaned.includes(",") ? cleaned.replace(/\./g, "").replace(",", ".") : cleaned;
  const value = Number(normalized);
  return Number.isFinite(value) ? value : undefined;
}

function toNumber(value: unknown): number | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

const DIRECTION: Record<string, Direction> = { uptrend: "alta", downtrend: "baixa" };

export function parseTrend(detail: string | undefined, trend: string): Opportunity["trend"] {
  const match = detail?.match(/saldo\s+([+\-−]?\d+)\s*\/\s*(\d+)/i);
  if (!match) return undefined;
  const saldo = Number(match[1].replace("−", "-"));
  const total = Number(match[2]);
  if (!Number.isFinite(saldo) || !Number.isFinite(total) || total <= 0) return undefined;
  return { saldo, total, direction: DIRECTION[trend] ?? "indefinida" };
}

export function parseVolatility(detail: string | undefined): Opportunity["volatility"] {
  const level = detail?.match(/Volatilidade (baixa|moderada|elevada)/i)?.[1]?.toLowerCase();
  if (level !== "baixa" && level !== "moderada" && level !== "elevada") return undefined;
  const percentile = detail?.match(/percentil (\d+)/i)?.[1];
  const window = detail?.match(/últimos (\d+) candles/i)?.[1];
  return {
    level,
    percentile: percentile !== undefined ? Number(percentile) : undefined,
    window: window !== undefined ? Number(window) : undefined,
  };
}

const MONEY = String.raw`(?:R\$|US\$)\s*([\d.,]+)`;
const DIST = String.raw`\(([\d.,]+)%\s*(?:abaixo|acima)\)`;

export function parseLevels(detail: string | undefined): Pick<Opportunity, "support" | "resistance"> {
  if (!detail) return {};
  const support = detail.match(new RegExp(`Suporte em ${MONEY}\\s*${DIST}`, "i"));
  const resistance = detail.match(new RegExp(`resistência em ${MONEY}\\s*${DIST}`, "i"));
  const level = (m: RegExpMatchArray | null) => {
    if (!m) return undefined;
    const value = parseLocaleNumber(m[1]);
    const distPct = parseLocaleNumber(m[2]);
    return value !== undefined && distPct !== undefined ? { value, distPct } : undefined;
  };
  return { support: level(support), resistance: level(resistance) };
}

/** First sentence of the justification: the engine's verdict in one line. */
export function firstSentence(text: string): string {
  const match = text.match(/^.*?[.!?](?=\s|$)/);
  return (match ? match[0] : text).trim();
}

function isB3(signal: Signal | B3Signal): signal is B3Signal {
  return "asset_type" in signal;
}

export function toOpportunity(signal: Signal | B3Signal): Opportunity {
  const byKey = new Map(signal.components.map((c) => [c.key, c]));
  const b3 = isB3(signal);
  const indicators = signal.indicators as Record<string, unknown>;
  const strongest = [...signal.components]
    .sort((a, b) => Math.abs(Number(b.score) - 50) * Number(b.weight_pct) - Math.abs(Number(a.score) - 50) * Number(a.weight_pct))
    .slice(0, 3)
    .map((c) => c.detail);
  const fundamentals = b3 ? signal.fundamentals : null;
  const hasScore = !b3 || signal.asset_type !== "FII" || Boolean(fundamentals?.price_to_nav && fundamentals.dividend_yield_12m);
  return {
    id: signal.id,
    symbol: signal.asset.symbol,
    href: b3 ? `/b3/${signal.asset.symbol}` : `/analise/${signal.asset.slug}`,
    name: signal.asset.name,
    imageUrl: signal.asset.image_url,
    market: b3 ? "B3" : "CRYPTO",
    assetType: b3 ? signal.asset_type : "CRYPTO",
    currency: b3 ? "BRL" : "USD",
    score: Number(signal.score),
    signal: signal.classification,
    price: toNumber(signal.current_price ?? signal.reference_price) ?? null,
    trend: parseTrend(byKey.get("trend")?.detail, signal.trend),
    rsi: toNumber(indicators.rsi),
    atrPct: toNumber(indicators.atr_pct),
    volatility: parseVolatility(byKey.get("volatility")?.detail),
    ...parseLevels(byKey.get("levels")?.detail),
    summary: firstSentence(signal.justification),
    evidence: strongest,
    risks: signal.risks,
    invalidation: signal.invalidation.join(" "),
    dataQuality: signal.data_quality,
    qualityReasons: signal.quality_reasons,
    hasScore,
    signalRaw: signal,
  };
}

export type SortKey = "score" | "ticker" | "trend" | "price";

const TREND_RANK: Record<Direction, number> = { alta: 2, indefinida: 1, baixa: 0 };

export function sortOpportunities(items: Opportunity[], key: SortKey): Opportunity[] {
  const sorted = [...items];
  const byScore = (a: Opportunity, b: Opportunity) => Number(b.hasScore) - Number(a.hasScore) || b.score - a.score;
  sorted.sort((a, b) => {
    if (key === "ticker") return a.symbol.localeCompare(b.symbol, "pt-BR");
    if (key === "price") return (b.price ?? -Infinity) - (a.price ?? -Infinity) || a.symbol.localeCompare(b.symbol);
    if (key === "trend") {
      const ta = a.trend ? TREND_RANK[a.trend.direction] * 100 + a.trend.saldo : -Infinity;
      const tb = b.trend ? TREND_RANK[b.trend.direction] * 100 + b.trend.saldo : -Infinity;
      return tb - ta || byScore(a, b);
    }
    return byScore(a, b);
  });
  return sorted;
}

export function filterOpportunities(items: Opportunity[], signal: SignalClass | null, query: string): Opportunity[] {
  const q = query.trim().toLocaleLowerCase("pt-BR");
  return items.filter(
    (o) =>
      (!signal || o.signal === signal) &&
      (!q || o.symbol.toLocaleLowerCase("pt-BR").includes(q) || o.name.toLocaleLowerCase("pt-BR").includes(q)),
  );
}

export type Distribution = Record<SignalClass, number> & { total: number };

export function distribution(items: Opportunity[]): Distribution {
  const d: Distribution = { total: items.length, buy_potential: 0, attention: 0, neutral: 0, sell_potential: 0 };
  for (const o of items) d[o.signal] += 1;
  return d;
}
