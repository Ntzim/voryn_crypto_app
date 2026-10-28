import { expect, test } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

test("protected pages redirect to login and come back after sign-in", async ({ page }) => {
  const email = uniqueEmail("redirect");
  await registerAndVerify(page, email);

  await page.goto("/mercado");
  await expect(page).toHaveURL(/\/entrar\?next=%2Fmercado/);
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha", { exact: true }).fill("uma-frase-longa-e-segura");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL("**/mercado");
});

test("wrong password shows a generic error", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail").fill(uniqueEmail("nobody"));
  await page.getByLabel("Senha", { exact: true }).fill("not-the-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("E-mail ou senha incorretos.")).toBeVisible();
});

test("dashboard, market and asset pages show real market data", async ({ page }, testInfo) => {
  const email = uniqueEmail("market");
  await registerAndVerify(page, email);
  await login(page, email);

  await expect(page.getByRole("heading", { name: "Olá, Ana" })).toBeVisible();
  await expect(page.getByText("Dados fornecidos por CoinGecko").first()).toBeVisible();
  await expect(page.getByText("Sua carteira aparece aqui")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("dashboard.png"), fullPage: true });

  await page.goto("/mercado");
  await expect(page.getByRole("link", { name: /Bitcoin/ }).first()).toBeVisible();
  await page.getByLabel("Buscar ativo").fill("eth");
  await expect(page).toHaveURL(/q=eth/);
  await expect(page.getByRole("link", { name: /Ethereum/ }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("market.png"), fullPage: true });

  await page.getByRole("link", { name: /Ethereum/ }).first().click();
  await expect(page.getByRole("heading", { name: "Ethereum" })).toBeVisible();
  await expect(page.getByText("Máxima histórica").first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("asset.png"), fullPage: true });
});

test("navigation adapts to the viewport", async ({ page, isMobile }) => {
  const email = uniqueEmail("nav");
  await registerAndVerify(page, email);
  await login(page, email);

  const bottomBar = page.locator("nav.fixed");
  if (isMobile) {
    await expect(bottomBar).toBeVisible();
    await bottomBar.getByText("Mais").click();
    await expect(page.getByRole("dialog").getByRole("link", { name: /Configurações/ })).toBeVisible();
  } else {
    await expect(bottomBar).toBeHidden();
    await expect(page.getByRole("complementary", { name: "Navegação principal" })).toBeVisible();
  }
});

test("settings: change preferences and sign out", async ({ page }, testInfo) => {
  const email = uniqueEmail("settings");
  await registerAndVerify(page, email);
  await login(page, email);

  await page.goto("/configuracoes?aba=seguranca");
  await expect(page.getByText("Sessões ativas")).toBeVisible();
  await expect(page.getByText("Esta sessão")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("settings-security.png"), fullPage: true });

  await page.getByRole("tab", { name: "Preferências" }).click();
  await page.getByLabel("Moeda base").click();
  await page.getByRole("option", { name: /Dólar americano/ }).click();
  await expect(page.getByText("Preferências salvas.")).toBeVisible();

  await page.goto("/mercado");
  await expect(page.getByRole("radio", { name: "USD" })).toHaveAttribute("aria-checked", "true");
});
