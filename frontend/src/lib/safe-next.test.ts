import { describe, expect, it } from "vitest";

import { safeNext } from "./safe-next";

describe("safeNext", () => {
  it("keeps same-origin paths with query and hash", () => {
    expect(safeNext("/carteira?aba=transacoes#x")).toBe("/carteira?aba=transacoes#x");
    expect(safeNext("/analise/bitcoin")).toBe("/analise/bitcoin");
  });

  it("falls back without a usable path", () => {
    expect(safeNext(null)).toBe("/dashboard");
    expect(safeNext("")).toBe("/dashboard");
    expect(safeNext("dashboard")).toBe("/dashboard");
    expect(safeNext("javascript:alert(1)")).toBe("/dashboard");
    expect(safeNext("https://evil.example")).toBe("/dashboard");
  });

  it.each([
    "//evil.example",
    "/\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "/\r/evil.example",
    "/\t\\evil.example",
    "\t//evil.example",
  ])("rejects %j, which a browser resolves to another site", (next) => {
    expect(safeNext(next)).toBe("/dashboard");
  });
});
