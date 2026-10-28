import { expect, test, type Page } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

function daysAgo(days: number, hour = 10): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(hour)}:00`;
}

async function pickAsset(page: Page, label: RegExp, query: string, name: RegExp) {
  await page.getByLabel(label).click();
  await page.getByLabel("Buscar ativo").fill(query);
  await page.getByRole("option", { name }).first().click();
}

async function addBuy(page: Page, query: string, name: RegExp, quantity: string, price: string, days: number) {
  await page.getByRole("button", { name: "Nova transação" }).click();
  const dialog = page.getByRole("dialog");
  await pickAsset(page, /^Ativo$/, query, name);
  await dialog.getByLabel("Quantidade").fill(quantity);
  await dialog.getByLabel("Preço unitário").fill(price);
  await dialog.getByLabel("Data e horário").fill(daysAgo(days));
  await dialog.getByRole("button", { name: "Registrar" }).click();
  await expect(page.getByText("Transação registrada.")).toBeVisible();
}

test("register transactions and see positions, results and dashboard", async ({ page }, testInfo) => {
  const email = uniqueEmail("portfolio");
  await registerAndVerify(page, email);
  await login(page, email);

  await page.goto("/carteira");
  await expect(page.getByText("Sua carteira está vazia")).toBeVisible();

  await page.getByRole("button", { name: "Registrar transação" }).click();
  const dialog = page.getByRole("dialog");
  await pickAsset(page, /^Ativo$/, "btc", /Bitcoin/);
  await dialog.getByLabel("Quantidade").fill("0,05");
  await dialog.getByLabel("Preço unitário").fill("380.000,00");
  await dialog.getByLabel(/Taxa em BRL/).fill("25");
  await dialog.getByLabel("Data e horário").fill(daysAgo(6));
  await dialog.getByRole("button", { name: "Registrar" }).click();
  await expect(page.getByText("Transação registrada.")).toBeVisible();

  await addBuy(page, "eth", /Ethereum/, "1,2", "12000", 4);

  // Selling more than held is refused with a clear message.
  await page.getByRole("button", { name: "Nova transação" }).click();
  await page.getByRole("dialog").getByRole("radio", { name: "Venda" }).click();
  await pickAsset(page, /^Ativo$/, "eth", /Ethereum/);
  await page.getByRole("dialog").getByLabel("Quantidade").fill("5");
  await page.getByRole("dialog").getByLabel("Preço unitário").fill("13000");
  await page.getByRole("dialog").getByLabel("Data e horário").fill(daysAgo(1));
  await page.getByRole("dialog").getByRole("button", { name: "Registrar" }).click();
  await expect(page.getByRole("dialog").getByText(/Saldo insuficiente de ETH/)).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancelar" }).click();

  await expect(page.getByText("Patrimônio").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Bitcoin/ }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Ethereum/ }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("carteira.png"), fullPage: true });

  await page.getByRole("tab", { name: "Transações" }).click();
  await expect(page.getByText("2 transação(ões)")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("transacoes.png"), fullPage: true });

  await page.goto("/dashboard");
  await expect(page.getByText("Evolução da carteira")).toBeVisible();
  await expect(page.getByText("Distribuição")).toBeVisible();
  await expect(page.getByText("Insights da carteira")).toBeVisible();
  await expect(page.getByText(/Bitcoin representa/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("dashboard-carteira.png"), fullPage: true });
});

test("import a CSV, skip duplicates, edit and delete", async ({ page }) => {
  const email = uniqueEmail("csv");
  await registerAndVerify(page, email);
  await login(page, email);
  await page.goto("/carteira");

  const csv = [
    "data;tipo;ativo;quantidade;preco_unitario;moeda;taxa;exchange;observacoes",
    `${daysAgo(9).replace("T", " ")};compra;SOL;10;800,00;BRL;5;binance;lote 1`,
    `${daysAgo(8).replace("T", " ")};compra;NAOEXISTE;1;1;BRL;;;`,
  ].join("\n");

  await page.getByRole("button", { name: "Importar CSV" }).first().click();
  await page.getByLabel("Arquivo CSV").setInputFiles({ name: "extrato.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(page.getByText("1 prontas")).toBeVisible();
  await expect(page.getByText(/ativo não encontrado/)).toBeVisible();
  await page.getByRole("button", { name: "Importar 1 transação(ões)" }).click();
  await expect(page.getByText("1 transação(ões) importada(s).")).toBeVisible();

  // Re-importing the same file finds nothing new.
  await page.getByRole("button", { name: "Importar CSV" }).first().click();
  await page.getByLabel("Arquivo CSV").setInputFiles({ name: "extrato.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(page.getByText("1 já importadas")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancelar" }).click();

  await page.getByRole("tab", { name: "Transações" }).click();
  await page.getByRole("button", { name: "Editar transação" }).first().click();
  await page.getByRole("dialog").getByLabel("Quantidade").fill("12");
  await page.getByRole("dialog").getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByText("Transação atualizada.")).toBeVisible();
  await expect(page.getByText(/12 SOL/)).toBeVisible();

  await page.getByRole("button", { name: "Excluir transação" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Excluir" }).click();
  await expect(page.getByText("Transação excluída.")).toBeVisible();
  await expect(page.getByText("Sua carteira está vazia")).toBeVisible();
});
