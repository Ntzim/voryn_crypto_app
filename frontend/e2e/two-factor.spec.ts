import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";

import { PASSWORD, login, registerAndVerify, uniqueEmail } from "./helpers";

/** RFC 6238 code for a base32 secret (what an authenticator app shows). */
function totp(secret: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  const hmac = createHmac("sha1", key).update(counter).digest();
  const offset = hmac[hmac.length - 1] & 0xf;
  return String((hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

test("enabling 2FA asks for the password before showing the secret", async ({ page }) => {
  const email = uniqueEmail("mfa");
  await registerAndVerify(page, email);
  await login(page, email);
  await page.goto("/configuracoes?aba=seguranca");
  await page.getByRole("button", { name: "Ativar 2FA" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Confirme sua senha para continuar.")).toBeVisible();
  await expect(dialog.getByText("Não consegue escanear? Digite a chave")).toHaveCount(0); // no secret yet

  await dialog.getByLabel("Senha", { exact: true }).fill("senha-errada-123");
  await dialog.getByRole("button", { name: "Continuar" }).click();
  await expect(dialog.getByText("Senha atual incorreta.")).toBeVisible();

  await dialog.getByLabel("Senha", { exact: true }).fill(PASSWORD);
  await dialog.getByRole("button", { name: "Continuar" }).click();
  await dialog.getByText("Não consegue escanear? Digite a chave").click();
  const secret = (await dialog.locator("code").textContent())!.trim();

  await dialog.getByLabel("Código de 6 dígitos").fill(totp(secret));
  await expect(dialog.getByRole("heading", { name: "Guarde seus códigos de recuperação" })).toBeVisible();
});
