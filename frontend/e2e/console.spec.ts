import { expect, test } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

test("app pages render without hydration errors", async ({ page }) => {
  // Sign-up plus twelve pages: under the full parallel suite on the dev server, 60 s is tight.
  test.setTimeout(120_000);
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && /hydrat|did not match|instant navigation/i.test(m.text())) problems.push(m.text().slice(0, 300));
  });
  const email = uniqueEmail("console");
  await registerAndVerify(page, email);
  await login(page, email);
  for (const path of ["/dashboard", "/mercado", "/carteira", "/analise", "/analise/bitcoin", "/mercado/bitcoin", "/oportunidades", "/alertas", "/voryn-ai", "/risco", "/estrategias", "/configuracoes"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  expect(problems).toEqual([]);
});
