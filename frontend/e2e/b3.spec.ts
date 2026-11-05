import { expect, test, type Page } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

/** Whether this stack runs with MARKETS_ENABLED including B3 (off by default). */
async function b3Enabled(page: Page): Promise<boolean> {
  const response = await page.request.get("/api/v1/market/markets");
  const markets = (await response.json()) as { market: string }[];
  return markets.some((m) => m.market === "B3");
}

async function signIn(page: Page, prefix: string) {
  const email = uniqueEmail(prefix);
  await registerAndVerify(page, email);
  await login(page, email);
}

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("with B3 disabled the market stays out of the app", async ({ page }) => {
  await signIn(page, "b3-off");
  test.skip(await b3Enabled(page), "B3 is enabled on this stack");
  await expect(page.getByRole("link", { name: "Bolsa B3" })).toHaveCount(0);
  await page.goto("/b3");
  await expect(page.getByText("B3 ainda não disponível")).toBeVisible();
});

test("explore the B3: delay labeled, filters, asset page", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, "b3-on");
  test.skip(!(await b3Enabled(page)), "needs MARKETS_ENABLED=CRYPTO,B3");
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && /hydrat|did not match|Content Security Policy/i.test(m.text())) problems.push(m.text().slice(0, 300));
  });

  await page.goto("/b3");
  await expect(page.getByRole("heading", { name: "Bolsa B3" })).toBeVisible();
  // Delayed quotes are never presented as real time.
  await expect(page.getByText(/Cotações com \d+ min de atraso/)).toBeVisible();
  await expect(page.getByText(/Pregão (aberto|fechado)/)).toBeVisible();
  // The index reference is the ETF, and says so.
  await expect(page.getByText("Referência do Ibovespa")).toBeVisible();
  await expect(page.getByText(/ETF que acompanha o índice/)).toBeVisible();
  await expect(page.getByText(/brapi\.dev/).first()).toBeVisible();
  await noHorizontalOverflow(page);

  // Filter by type and search, kept in the URL.
  await page.getByRole("radio", { name: "FIIs" }).click();
  await expect(page).toHaveURL(/tipo=FII/);
  await page.getByRole("radio", { name: "Todos" }).click();
  await page.getByLabel("Buscar ativo").fill("PETR4");
  await expect(page).toHaveURL(/q=PETR4/);
  await expect(page).not.toHaveURL(/tipo=/);
  const row = page.getByRole("link", { name: /PETR4/ }).filter({ visible: true }).last();
  await expect(row).toBeVisible();

  // PETR4 is one of brapi's open test tickers: real session figures and chart without a token.
  await page.goto("/b3/PETR4");
  await expect(page.getByRole("heading", { name: /PETR4/ })).toBeVisible();
  await expect(page.getByText(/Cotações com \d+ min de atraso/)).toBeVisible();
  await expect(page.getByText("Máxima em 52 semanas")).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await noHorizontalOverflow(page);

  await page.goto("/b3/NAOEXISTE3");
  await expect(page.getByText("Ativo não encontrado")).toBeVisible();
  expect(problems).toEqual([]);
});

test("B3 opportunities: scope stated, stocks and FIIs, no real-time claim", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, "b3-signals");
  test.skip(!(await b3Enabled(page)), "needs MARKETS_ENABLED=CRYPTO,B3");
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && /hydrat|did not match|Content Security Policy/i.test(m.text())) problems.push(m.text().slice(0, 300));
  });

  await page.goto("/oportunidades-b3");
  await expect(page.getByRole("heading", { name: "Oportunidades B3" })).toBeVisible();
  await expect(page.getByText(/Análise somente técnica/).first()).toBeVisible();
  await expect(page.getByText(/Cotações com \d+ min de atraso/)).toBeVisible();
  await expect(page.getByText(/Não constituem recomendação de investimento/)).toBeVisible();
  await expect(page.getByText(/validados por backtest/)).toBeVisible();
  await noHorizontalOverflow(page);

  await page.getByRole("radio", { name: "FIIs" }).click();
  await expect(page).toHaveURL(/tipo=FII/);
  await expect(page.getByText(/Considera P\/VP/).first()).toBeVisible();
  await noHorizontalOverflow(page);
  expect(problems).toEqual([]);
});

