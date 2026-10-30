import { expect, test } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

test("run a backtest in the worker and read train vs validation results", async ({ page }) => {
  const email = uniqueEmail("bt");
  await registerAndVerify(page, email);
  await login(page, email);

  await page.goto("/estrategias");
  await expect(page.getByText("Configure e execute um backtest")).toBeVisible();

  await page.getByLabel("Ativo").click();
  await page.getByLabel("Buscar ativo").fill("btc");
  await page.getByRole("option", { name: /Bitcoin/ }).first().click();
  await page.getByLabel("Estratégia").click();
  await page.getByRole("option", { name: "Cruzamento de médias (EMA)" }).click();
  await page.getByLabel("Otimizar parâmetros no treino").click();
  await page.getByRole("button", { name: "Executar backtest" }).click();

  await expect(page).toHaveURL(/\?run=/);
  await expect(page.getByText("Validação (fora da amostra)")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("cell", { name: "Retorno total" })).toBeVisible();
  await expect(page.getByText("Otimização no treino")).toBeVisible();
  await expect(page.getByText("escolhido", { exact: true })).toBeVisible();
  await expect(page.getByText(/sem uso de dados futuros/)).toBeVisible();
  await expect(page.getByRole("button", { name: /BTC · Cruzamento de médias/ })).toBeVisible();
});
