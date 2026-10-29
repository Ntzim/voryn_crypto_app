import { expect, test } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

test("opportunities list signals with explanation and detail", async ({ page }, testInfo) => {
  const email = uniqueEmail("signals");
  await registerAndVerify(page, email);
  await login(page, email);

  await page.goto("/oportunidades");
  await expect(page.getByRole("heading", { name: "Oportunidades" })).toBeVisible();
  await expect(page.getByText(/não é probabilidade de lucro/)).toBeVisible({ timeout: 20_000 });
  const firstCard = page.locator("main button.rounded-xl").first();
  await expect(firstCard).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("oportunidades.png"), fullPage: true });

  await firstCard.click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByText("Composição do score")).toBeVisible();
  await expect(sheet.getByText("Condições de invalidação")).toBeVisible();
  await expect(sheet.getByText(/estratégia voryn-core v1/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("sinal-detalhe.png") });
});

test("asset analysis shows the opportunity signal", async ({ page }) => {
  const email = uniqueEmail("assetsignal");
  await registerAndVerify(page, email);
  await login(page, email);
  await page.goto("/analise/bitcoin");
  await expect(page.getByText("Sinal de oportunidade · 1d")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("img", { name: /Score \d+ de 100/ }).first()).toBeVisible();
});

test("create, toggle and delete an alert", async ({ page }) => {
  const email = uniqueEmail("alerts");
  await registerAndVerify(page, email);
  await login(page, email);

  await page.goto("/alertas");
  await expect(page.getByText("Nenhum alerta configurado")).toBeVisible();
  await page.getByRole("button", { name: "Novo alerta" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Ativo").click();
  await page.getByLabel("Buscar ativo").fill("btc");
  await page.getByRole("option", { name: /Bitcoin/ }).first().click();
  await dialog.getByLabel("Preço-alvo").fill("250.000");
  await expect(dialog.getByText("= US$ 250.000,00")).toBeVisible();
  await dialog.getByRole("button", { name: "Criar alerta" }).click();
  await expect(page.getByText("Alerta criado.")).toBeVisible();
  await expect(page.getByText(/BTC · Preço acima de 250000 USD/)).toBeVisible(); // 250.000 read as 250 mil

  await page.getByRole("switch", { name: "Desativar alerta" }).click();
  await expect(page.getByRole("switch", { name: "Ativar alerta" })).toBeVisible();

  await page.getByRole("button", { name: "Notificações" }).first().click();
  await expect(page.getByText("Nenhuma notificação ainda.")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Excluir alerta" }).click();
  await expect(page.getByText("Alerta excluído.")).toBeVisible();
  await expect(page.getByText("Nenhum alerta configurado")).toBeVisible();
});
