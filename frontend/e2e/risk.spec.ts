import { expect, test } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

function daysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T10:00`;
}

test("risk report and scenario simulation for the current holdings", async ({ page }) => {
  const email = uniqueEmail("risk");
  await registerAndVerify(page, email);
  await login(page, email);

  await page.goto("/risco");
  await expect(page.getByText("Sem posições para analisar")).toBeVisible();

  await page.goto("/carteira");
  await page.getByRole("button", { name: "Registrar transação" }).click();
  const dialog = page.getByRole("dialog");
  await page.getByLabel(/^Ativo$/).click();
  await page.getByLabel("Buscar ativo").fill("btc");
  await page.getByRole("option", { name: /Bitcoin/ }).first().click();
  await dialog.getByLabel("Quantidade").fill("0,1");
  await dialog.getByLabel("Preço unitário").fill("400.000,00");
  await dialog.getByLabel("Data e horário").fill(daysAgo(3));
  await dialog.getByRole("button", { name: "Registrar" }).click();
  await expect(page.getByText("Transação registrada.")).toBeVisible();

  await page.goto("/risco?janela=90");
  await expect(page.getByRole("heading", { name: "Risco", level: 1 })).toBeVisible();
  await expect(page.getByRole("radio", { name: "90 dias" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByText(/retornos diários/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Volatilidade anualizada")).toBeVisible();
  await expect(page.getByRole("cell", { name: /BTC/ }).first()).toBeVisible();

  await page.getByRole("button", { name: "−30%" }).click();
  // BTC alone: the portfolio moves exactly with Bitcoin.
  await expect(page.getByRole("cell", { name: "-30,0%" })).toBeVisible();
  await expect(page.getByText("Simulação mecânica sobre as posições de hoje", { exact: false })).toBeVisible();
});
