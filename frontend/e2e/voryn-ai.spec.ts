import { expect, test } from "@playwright/test";

import { login, registerAndVerify, uniqueEmail } from "./helpers";

// The e2e stack runs without an Anthropic key; the assistant must say so instead of failing.
test("Voryn AI explains when the assistant is not configured", async ({ page }) => {
  const email = uniqueEmail("ai");
  await registerAndVerify(page, email);
  await login(page, email);

  // Desktop: sidebar link. Mobile: the "Mais" sheet of the bottom bar.
  const sidebarLink = page.getByRole("link", { name: "Voryn AI" }).first();
  const desktop = await sidebarLink.isVisible();
  if (desktop) await sidebarLink.click();
  else {
    await page.getByRole("button", { name: "Mais" }).click();
    await page.getByRole("dialog").getByRole("link", { name: /Voryn AI/ }).click();
  }
  await expect(page).toHaveURL(/\/voryn-ai$/);
  await expect(page.getByRole("heading", { name: "Voryn AI", level: 1 })).toBeVisible();
  await expect(page.getByText("Voryn AI indisponível neste ambiente")).toBeVisible();
  if (desktop) await expect(page.getByText("Suas conversas aparecem aqui.").first()).toBeVisible();
});

// UI contract test: the AI endpoints are mocked at the network layer (no model is called),
// so this covers streaming, rendering and provenance display — not the model's answers.
test("Voryn AI streams a reply and shows the data it used", async ({ page }) => {
  const email = uniqueEmail("ai-chat");
  await registerAndVerify(page, email);
  await login(page, email);

  const now = new Date().toISOString();
  const conv = { id: "7f1c1f3e-0000-4000-8000-000000000001", title: "Como está minha carteira hoje?", model: "claude-opus-5-5", turns: 0, created_at: now, updated_at: now };
  const answer = "## Dados observados\n\n| Ativo | Peso |\n| --- | --- |\n| BTC | 60% |\n\n**Riscos:** concentração elevada.";
  const source = "Carteira · até 28/10/2026 21:00";
  let stored = false;

  await page.route("**/api/v1/ai/status", (r) =>
    r.fulfill({ json: { enabled: true, model: conv.model, messages_per_hour: 30, max_turns_per_conversation: 30, usage_today: {} } }),
  );
  await page.route("**/api/v1/ai/conversations", (r) =>
    r.request().method() === "POST" ? r.fulfill({ status: 201, json: conv }) : r.fulfill({ json: stored ? [conv] : [] }),
  );
  await page.route(`**/api/v1/ai/conversations/${conv.id}/messages`, (r) => {
    stored = true;
    const events = [
      ["start", { conversation_id: conv.id }],
      ["status", { text: "Consultando sua carteira…" }],
      ["delta", { text: answer.slice(0, 40) }],
      ["delta", { text: answer.slice(40) }],
      ["done", { sources: [source], tool_calls: [] }],
    ];
    return r.fulfill({
      headers: { "content-type": "text/event-stream" },
      body: events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join(""),
    });
  });
  await page.route(`**/api/v1/ai/conversations/${conv.id}`, (r) =>
    r.fulfill({
      json: {
        ...conv,
        turns: stored ? 1 : 0,
        can_continue: true,
        messages: stored
          ? [
              { id: 1, role: "user", text: conv.title, sources: [], tool_calls: [], created_at: now },
              { id: 2, role: "assistant", text: answer, sources: [source], tool_calls: [{ name: "get_portfolio_summary", ok: true }], created_at: now },
            ]
          : [],
      },
    }),
  );

  await page.goto("/voryn-ai");
  await page.getByRole("button", { name: conv.title }).click();
  await expect(page).toHaveURL(new RegExp(`c=${conv.id}`));
  await expect(page.getByRole("heading", { name: "Dados observados" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "BTC" })).toBeVisible();
  await expect(page.getByText(conv.title, { exact: true }).last()).toBeVisible();
  await page.getByText("Dados consultados (1)").click();
  await expect(page.getByText(source)).toBeVisible();
  await expect(page.getByLabel("Mensagem para o Voryn AI")).toBeEnabled();
});
