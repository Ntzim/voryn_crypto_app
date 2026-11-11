import { describe, expect, it } from "vitest";

import {
  distribution,
  filterOpportunities,
  firstSentence,
  parseLevels,
  parseLocaleNumber,
  parseTrend,
  parseVolatility,
  sortOpportunities,
  strongest,
  type Opportunity,
} from "./opportunity";

// Sentences exactly as the signal engine writes them (see backend signals/engine.py).
describe("reading the engine's sentences", () => {
  it("reads the trend balance", () => {
    expect(parseTrend("Tendência de alta (saldo +3/5).", "uptrend")).toEqual({ saldo: 3, total: 5, direction: "alta" });
    expect(parseTrend("Tendência indefinida (saldo -2/5).", "undefined")).toEqual({ saldo: -2, total: 5, direction: "indefinida" });
    expect(parseTrend("Tendência de baixa (saldo -5/6).", "downtrend")?.direction).toBe("baixa");
    expect(parseTrend("Tendência indisponível.", "undefined")).toBeUndefined();
  });

  it("reads the volatility level, percentile and window", () => {
    expect(parseVolatility("Volatilidade elevada em relação aos últimos 42 candles (percentil 100). ATR de 3,63% por candle.")).toEqual({
      level: "elevada",
      percentile: 100,
      window: 42,
    });
    expect(parseVolatility("Volatilidade baixa em relação aos últimos 100 candles (percentil 2).")?.level).toBe("baixa");
    expect(parseVolatility("Volatilidade relativa indisponível.")).toBeUndefined();
  });

  it("reads support and resistance in reais and dollars", () => {
    expect(parseLevels("Suporte em R$ 20,67 (0,4% abaixo) e resistência em R$ 21,77 (4,9% acima).")).toEqual({
      support: { value: 20.67, distPct: 0.4 },
      resistance: { value: 21.77, distPct: 4.9 },
    });
    expect(parseLevels("Suporte em US$ 61.400,50 (1,5% abaixo) e resistência em US$ 68.000,00 (9,6% acima).").support?.value).toBe(61400.5);
    expect(parseLevels("Sem resistência identificado próximo ao preço.")).toEqual({ support: undefined, resistance: undefined });
  });

  it("keeps the verdict sentence and parses pt-BR numbers", () => {
    expect(firstSentence("Há sinais contraditórios ou aumento relevante de risco. Tendência de alta (saldo +5/5).")).toBe(
      "Há sinais contraditórios ou aumento relevante de risco.",
    );
    expect(parseLocaleNumber("1.234,56")).toBe(1234.56);
    expect(parseLocaleNumber("12.5")).toBe(12.5);
    expect(parseLocaleNumber("")).toBeUndefined();
  });
});

function item(symbol: string, score: number, signal: Opportunity["signal"], extra: Partial<Opportunity> = {}): Opportunity {
  return {
    id: score,
    symbol,
    href: `/b3/${symbol}`,
    name: `${symbol} SA`,
    imageUrl: null,
    market: "B3",
    assetType: "STOCK",
    currency: "BRL",
    score,
    signal,
    price: score,
    summary: "",
    evidenceFor: [],
    evidenceAgainst: [],
    risks: [],
    invalidation: "",
    dataQuality: "valid",
    qualityReasons: [],
    hasScore: true,
    favorable: 0,
    against: 0,
    criteria: 6,
    signalRaw: {} as Opportunity["signalRaw"],
    ...extra,
  };
}

describe("list operations", () => {
  const items = [
    item("WEGE3", 56, "attention", { trend: { saldo: 1, total: 5, direction: "indefinida" } }),
    item("CXSE3", 66, "buy_potential", { trend: { saldo: 3, total: 5, direction: "alta" } }),
    item("VALE3", 34, "sell_potential", { trend: { saldo: -5, total: 5, direction: "baixa" }, name: "Vale" }),
    item("HGLG11", 80, "attention", { hasScore: false }),
  ];

  it("sorts by score with unscored items last, and by ticker, trend and price", () => {
    expect(sortOpportunities(items, "score").map((o) => o.symbol)).toEqual(["CXSE3", "WEGE3", "VALE3", "HGLG11"]);
    expect(sortOpportunities(items, "ticker").map((o) => o.symbol)).toEqual(["CXSE3", "HGLG11", "VALE3", "WEGE3"]);
    expect(sortOpportunities(items, "trend")[0].symbol).toBe("CXSE3");
    expect(sortOpportunities(items, "price")[0].symbol).toBe("HGLG11");
  });

  it("filters by signal and by ticker or company, ignoring case", () => {
    expect(filterOpportunities(items, "attention", "").map((o) => o.symbol)).toEqual(["WEGE3", "HGLG11"]);
    expect(filterOpportunities(items, null, "vale").map((o) => o.symbol)).toEqual(["VALE3"]);
    expect(filterOpportunities(items, null, "cxse").map((o) => o.symbol)).toEqual(["CXSE3"]);
  });

  it("counts the distribution", () => {
    expect(distribution(items)).toEqual({ total: 4, buy_potential: 1, attention: 2, neutral: 0, sell_potential: 1 });
  });
});

describe("highlights", () => {
  const items = [
    item("AAA3", 70, "buy_potential"),
    item("BBB3", 82, "buy_potential"),
    item("CCC3", 90, "buy_potential", { dataQuality: "incomplete" }),
    item("DDD3", 30, "sell_potential"),
    item("EEE3", 18, "sell_potential"),
    item("FFF11", 10, "sell_potential", { hasScore: false }),
    item("GGG3", 60, "attention"),
  ];

  it("ranks buy potential by the highest score and sell potential by the lowest", () => {
    expect(strongest(items, "buy_potential").map((o) => o.symbol)).toEqual(["BBB3", "AAA3"]);
    expect(strongest(items, "sell_potential").map((o) => o.symbol)).toEqual(["EEE3", "DDD3"]);
  });

  it("leaves out readings built on incomplete data or without a score", () => {
    expect(strongest(items, "buy_potential").some((o) => o.symbol === "CCC3")).toBe(false);
    expect(strongest(items, "sell_potential").some((o) => o.symbol === "FFF11")).toBe(false);
    expect(strongest([], "buy_potential")).toEqual([]);
  });
});

