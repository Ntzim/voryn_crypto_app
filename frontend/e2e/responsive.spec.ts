import { expect, test, type Page } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

const PAGES = ["/dashboard", "/carteira", "/mercado", "/analise/bitcoin", "/mercado/bitcoin", "/oportunidades", "/risco", "/alertas", "/estrategias", "/configuracoes"];

/** Adds two positions with history through the API, so data-heavy pages (risk table,
 * charts) render as they do for real users. */
async function addBitcoin(page: Page) {
  const csrf = (await (await page.request.get("/api/v1/auth/csrf")).json()).csrf_token as string;
  const headers = { "X-CSRF-Token": csrf };
  const pid = (await (await page.request.get("/api/v1/portfolios")).json())[0].id as string;
  const executed_at = new Date(Date.now() - 120 * 86_400_000).toISOString();
  for (const [q, quantity] of [["bitcoin", "0.01"], ["ethereum", "0.3"]]) {
    const asset = (await (await page.request.get(`/api/v1/market/assets?q=${q}&page_size=1`)).json()).items[0];
    const response = await page.request.post(`/api/v1/portfolios/${pid}/transactions`, {
      headers,
      data: { type: "buy", asset_id: asset.id, quantity, unit_price: asset.price, quote_currency: "BRL", executed_at },
    });
    expect(response.ok()).toBe(true);
  }
}

// Limitation: the risk page shows its wide per-asset table only after the worker has filled
// the price history (every 6 h), which a fresh test account does not have; that state was
// checked with a seeded account instead (see docs/UX.md).
test("no page scrolls sideways on phones, tablets or desktops", async ({ page, browser }, info) => {
  test.skip(info.project.name !== "desktop", "widths are set explicitly below");
  test.setTimeout(240_000);
  const email = uniqueEmail("responsive");
  await registerAndVerify(page, email);
  await login(page, email);
  await addBitcoin(page);

  const storageState = await page.context().storageState();
  // Phones are emulated with touch: coarse pointers get the larger 44px controls, which is
  // what overflows when a layout is too tight. Wider screens use a mouse.
  for (const [width, touch] of [[320, true], [375, true], [768, false], [1024, false]] as const) {
    const context = await browser.newContext({
      storageState,
      baseURL: info.project.use.baseURL,
      viewport: { width, height: 800 },
      isMobile: touch,
      hasTouch: touch,
    });
    const tab = await context.newPage();
    for (const path of PAGES) {
      await tab.goto(path);
      await tab.waitForLoadState("networkidle");
      const { scroll, client } = await tab.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }));
      expect(scroll, `${path} at ${width}px`).toBeLessThanOrEqual(client);
    }
    await context.close();
  }
});

test("explanations open with a tap on touch screens", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile", "touch only");
  const email = uniqueEmail("hint");
  await registerAndVerify(page, email);
  await login(page, email);
  await addBitcoin(page);
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Sobre: Patrimônio" }).tap();
  await expect(page.getByText("Valor de mercado das posições abertas a preços atuais.")).toBeVisible();
});

test("segmented controls follow the arrow keys", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "keyboard");
  const email = uniqueEmail("segmented");
  await registerAndVerify(page, email);
  await login(page, email);
  await page.goto("/mercado");
  const group = page.getByRole("radiogroup", { name: "Moeda de exibição" });
  await group.getByRole("radio", { checked: true }).focus();
  const before = await group.getByRole("radio", { checked: true }).textContent();
  await page.keyboard.press("ArrowRight");
  const after = group.getByRole("radio", { checked: true });
  await expect(after).not.toHaveText(before ?? "");
  await expect(after).toBeFocused();
});
