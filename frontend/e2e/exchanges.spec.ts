import { expect, test } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

// No real credentials in tests: a made-up key must be validated at Binance and refused,
// and nothing may be stored.
test("a key that Binance does not accept is refused before anything is saved", async ({ page }) => {
  const email = uniqueEmail("exchange");
  await registerAndVerify(page, email);
  await login(page, email);

  await page.goto("/configuracoes?aba=integracoes");
  await expect(page.getByText("Nenhuma exchange conectada")).toBeVisible();
  await page.getByRole("button", { name: "Conectar Binance" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/somente/)).toBeVisible();
  await dialog.getByLabel("Chave de API").fill("voryn-e2e-invalid-key-0000000000000000");
  await dialog.getByLabel("Segredo").fill("voryn-e2e-invalid-secret-000000000000000");
  await dialog.getByRole("button", { name: "Validar e conectar" }).click();
  await expect(dialog.getByText(/Binance/).last()).toBeVisible({ timeout: 20_000 });
  await expect(dialog.locator("p.text-destructive")).toBeVisible();
  await dialog.getByRole("button", { name: "Cancelar" }).click();
  await expect(page.getByText("Nenhuma exchange conectada")).toBeVisible();
});
