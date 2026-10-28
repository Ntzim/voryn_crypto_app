import { expect, type Page } from "@playwright/test";

const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8035";
export const PASSWORD = "uma-frase-longa-e-segura";

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/** Polls Mailpit until a message to `email` arrives and returns the token in its link. */
export async function tokenFromMail(email: string, path: string): Promise<string> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const search = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${email}"`)}`);
    const { messages } = (await search.json()) as { messages: { ID: string }[] };
    for (const { ID } of messages ?? []) {
      const message = (await (await fetch(`${MAILPIT}/api/v1/message/${ID}`)).json()) as { Text: string };
      const match = message.Text.match(new RegExp(`${path}\\?token=([A-Za-z0-9_\\-]+)`));
      if (match) return match[1];
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`No e-mail with ${path} for ${email}`);
}

export async function registerAndVerify(page: Page, email: string, name = "Ana Souza"): Promise<void> {
  await page.goto("/criar-conta");
  // Typing before hydration finishes would be reset by React (seen on cold dev compiles).
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Nome").fill(name);
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Criar conta" }).click();
  await expect(page.getByRole("heading", { name: "Confirme seu e-mail" })).toBeVisible();

  const token = await tokenFromMail(email, "/verificar-email");
  await page.goto(`/verificar-email?token=${token}`);
  await expect(page.getByRole("heading", { name: "E-mail confirmado" })).toBeVisible();
}

export async function login(page: Page, email: string): Promise<void> {
  await page.goto("/entrar");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL("**/dashboard");
}
