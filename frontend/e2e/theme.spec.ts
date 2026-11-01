import { expect, test, type Page } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

const BACKGROUND = { light: "rgb(245, 245, 247)", dark: "rgb(11, 13, 18)" };

const isDark = (page: Page) => page.evaluate(() => document.documentElement.classList.contains("dark"));

/** Body background at DOMContentLoaded: before React hydrates, i.e. what the first paint shows. */
async function firstPaintBackground(page: Page, path: string): Promise<string> {
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      (window as unknown as { __firstBg: string }).__firstBg = getComputedStyle(document.body).backgroundColor;
    });
  });
  await page.goto(path);
  return page.evaluate(() => (window as unknown as { __firstBg: string }).__firstBg);
}

test.describe("theme", () => {
  test("follows the system setting with no saved preference, without a flash", async ({ browser }) => {
    for (const scheme of ["light", "dark"] as const) {
      const context = await browser.newContext({ colorScheme: scheme });
      const page = await context.newPage();
      expect(await firstPaintBackground(page, "/entrar")).toBe(BACKGROUND[scheme]);
      expect(await isDark(page)).toBe(scheme === "dark");
      await context.close();
    }
  });

  test("the switch applies instantly and survives a reload", async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: "dark" });
    const page = await context.newPage();
    await page.goto("/entrar");
    await page.waitForLoadState("networkidle");
    const toggle = page.getByRole("switch", { name: "Alternar tema" });
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(await isDark(page)).toBe(false);
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(BACKGROUND.light);

    // Saved choice beats the system setting, from the very first paint.
    expect(await firstPaintBackground(page, "/entrar")).toBe(BACKGROUND.light);
    await context.close();
  });

  test("the preference belongs to the account, not the browser", async ({ browser }) => {
    test.setTimeout(120_000);
    const owner = uniqueEmail("theme-owner");
    const other = uniqueEmail("theme-other");

    // Owner picks light on one device (system is dark).
    const first = await browser.newContext({ colorScheme: "dark" });
    const page = await first.newPage();
    await registerAndVerify(page, owner);
    await registerAndVerify(page, other, "Bruno Lima");
    await login(page, owner);
    const save = page.waitForResponse((r) => r.url().includes("/me/settings") && r.request().method() === "PATCH");
    await page.getByRole("switch", { name: "Alternar tema" }).click();
    expect((await save).ok()).toBe(true);
    expect(await isDark(page)).toBe(false);

    // The settings page shows the same choice.
    await page.goto("/configuracoes?aba=preferencias");
    await expect(page.getByRole("radio", { name: "Claro" })).toHaveAttribute("aria-checked", "true");

    // Another person on the same browser gets their own (default: system → dark).
    await page.context().clearCookies();
    await login(page, other);
    await expect.poll(() => isDark(page)).toBe(true);
    await first.close();

    // The owner on a fresh device (no local storage) gets light after signing in.
    const second = await browser.newContext({ colorScheme: "dark" });
    const fresh = await second.newPage();
    await login(fresh, owner);
    await expect.poll(() => isDark(fresh)).toBe(false);
    // And "Sistema" hands control back to the device.
    await fresh.goto("/configuracoes?aba=preferencias");
    await fresh.getByRole("radio", { name: "Sistema" }).click();
    await expect.poll(() => isDark(fresh)).toBe(true);
    await second.close();
  });

  test("charts redraw with the new theme colors", async ({ browser }) => {
    test.setTimeout(120_000);
    const context = await browser.newContext({ colorScheme: "dark" });
    const page = await context.newPage();
    const email = uniqueEmail("theme-chart");
    await registerAndVerify(page, email);
    await login(page, email);
    await page.goto("/analise/bitcoin");
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 30_000 });
    const before = await canvas.screenshot();
    await page.getByRole("switch", { name: "Alternar tema" }).click();
    await expect.poll(() => isDark(page)).toBe(false);
    await expect.poll(async () => Buffer.compare(before, await canvas.screenshot()) !== 0).toBe(true);
    await context.close();
  });
});
