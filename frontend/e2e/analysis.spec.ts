import { expect, test } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

test("technical analysis with real candles, timeframes and indicators", async ({ page }, testInfo) => {
  const email = uniqueEmail("analysis");
  await registerAndVerify(page, email);
  await login(page, email);

  await page.goto("/analise/bitcoin");
  await expect(page.getByRole("heading", { name: "Bitcoin" })).toBeVisible();
  await expect(page.getByText("Indicadores", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("RSI (14)")).toBeVisible();
  await expect(page.getByText("Suportes e resistências", { exact: true })).toBeVisible();
  await expect(page.getByText(/Candles: Binance BTC\/USDT/)).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("analise-1d.png"), fullPage: true });

  await page.getByRole("radio", { name: "4h" }).click();
  await expect(page).toHaveURL(/tf=4h/);
  await expect(page.getByText(/Último candle fechado/)).toBeVisible();

  // Toggling oscillators off removes their panes.
  await page.getByRole("button", { name: "MACD", exact: true }).click();
  await expect(page.getByRole("button", { name: "MACD", exact: true })).toHaveAttribute("aria-pressed", "false");
});

test("favorites and custom watchlists filter the market", async ({ page }) => {
  const email = uniqueEmail("watch");
  await registerAndVerify(page, email);
  await login(page, email);

  await page.goto("/mercado/ethereum");
  await page.getByRole("button", { name: "Listas" }).click();
  await page.getByRole("menuitemcheckbox", { name: /Favoritos/ }).click();
  await expect(page.getByRole("menuitemcheckbox", { name: /Favoritos/ })).toHaveAttribute("aria-checked", "true");
  await page.getByLabel("Nome da nova lista").fill("Layer 1");
  await page.getByRole("button", { name: "Criar lista" }).click();
  await expect(page.getByText("Lista “Layer 1” criada.")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText(/Análise técnica completa/)).toBeVisible({ timeout: 20_000 });

  await page.goto("/mercado");
  await page.getByLabel("Lista").click();
  await page.getByRole("option", { name: /Favoritos/ }).click();
  await expect(page).toHaveURL(/lista=/);
  await expect(page.getByRole("link", { name: /Ethereum/ }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Bitcoin/ })).toHaveCount(0);

  await page.goto("/analise");
  await expect(page.getByRole("link", { name: /Ethereum/ }).first()).toHaveAttribute("href", "/analise/ethereum");
});
