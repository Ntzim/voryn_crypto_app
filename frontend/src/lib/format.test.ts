import { describe, expect, it } from "vitest";

import { formatMoney, formatPercent, formatPrice, formatRelative, trendOf } from "./format";

// Intl inserts non-breaking spaces; normalize for readable assertions.
const n = (s: string) => s.replace(/ | /g, " ");

describe("formatPrice", () => {
  it("uses two decimals for prices above one", () => {
    expect(n(formatPrice("80536.743471716750000000", "BRL"))).toBe("R$ 80.536,74");
    expect(n(formatPrice("1.325461157528358400", "USD", "en-US"))).toBe("$1.33");
  });

  it("keeps significant digits for sub-unit prices", () => {
    expect(n(formatPrice("0.000012345678901234", "USD", "en-US"))).toBe("$0.00001235");
    expect(n(formatPrice("0.998758895588707300", "USD", "en-US"))).toBe("$0.9988");
  });

  it("renders a dash for missing values", () => {
    expect(formatPrice(null, "USD")).toBe("—");
    expect(formatPrice("not-a-number", "USD")).toBe("—");
  });
});

describe("formatMoney", () => {
  it("supports compact notation for large aggregates", () => {
    expect(n(formatMoney("1280000000000", "USD", "en-US", { compact: true }))).toBe("$1.28T");
  });
});

describe("formatPercent", () => {
  it("always shows the sign", () => {
    expect(formatPercent("2.5", "en-US")).toBe("+2.50%");
    expect(formatPercent("-1.234", "en-US")).toBe("-1.23%");
    expect(formatPercent("0", "en-US")).toBe("0.00%");
  });
});

describe("trendOf", () => {
  it("classifies direction", () => {
    expect(trendOf("1")).toBe("up");
    expect(trendOf("-0.1")).toBe("down");
    expect(trendOf(null)).toBe("flat");
  });
});

describe("formatRelative", () => {
  it("formats minutes ago", () => {
    const now = Date.parse("2026-01-01T12:10:00Z");
    expect(formatRelative("2026-01-01T12:05:00Z", "en-US", now)).toBe("5 minutes ago");
    expect(formatRelative("2026-01-01T12:09:50Z", "pt-BR", now)).toBe("agora");
  });
});
