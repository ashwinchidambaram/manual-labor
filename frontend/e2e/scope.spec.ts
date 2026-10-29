import { expect, test } from "@playwright/test";
import { clearSelection, getGroups, putOp, resetSelection, row, stat, waitForTree, waitSettled } from "./helpers";

test.beforeAll(async ({ playwright }) => {
  // A hardware probe must exist for the model panel (E6).
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  const r = await ctx.post("/api/probe");
  expect(r.ok()).toBeTruthy();
  await ctx.dispose();
});

test.beforeEach(async ({ request }) => {
  await resetSelection(request);
});

test.describe("E0 built dist", () => {
  test.use({ baseURL: "http://127.0.0.1:8766" });
  test("labor serve serves dist, with SPA fallback on reload", async ({ page }) => {
    await page.goto("/scope");
    await waitForTree(page);
    await page.reload();
    await waitForTree(page);
    await expect(page.getByRole("heading", { name: "Manual Labor" })).toBeVisible();
  });
});

test("E1 toggle preserves selection and shows coverage in the other view", async ({ page, request }) => {
  await clearSelection(request);
  await page.goto("/scope");
  await waitForTree(page);
  const groups = await getGroups(request);
  const topic = groups[0].groups.topics.find((t) => !t.is_unassigned)!;
  await row(page, topic.id).click();
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(topic.block_count));
  await waitSettled(page);
  const before = {
    blocks: await stat(page, "sum-blocks"),
    pages: await stat(page, "sum-pages"),
    articles: await stat(page, "sum-articles"),
  };

  await page.getByRole("radio", { name: "Document structure" }).click();
  await expect(page).toHaveURL(/view=structure/);
  await expect(page.getByRole("tree", { name: "Document structure" })).toBeVisible();
  expect(await stat(page, "sum-blocks")).toBe(before.blocks);
  expect(await stat(page, "sum-pages")).toBe(before.pages);
  expect(await stat(page, "sum-articles")).toBe(before.articles);
  await waitSettled(page);

  const sel = await (await request.get("/api/scope/selection")).json();
  const cov = sel.coverage.flatMap((c: { structure: unknown[] }) => c.structure) as {
    group_id: string;
    subtree_fraction: number | null;
  }[];
  let checked = 0;
  for (const c of cov) {
    if (!c.subtree_fraction) continue;
    const chip = row(page, c.group_id).getByTestId("coverage-chip");
    if (!(await chip.count())) continue; // collapsed descendant
    const expected = c.subtree_fraction >= 1 ? "100%" : `${Math.round(c.subtree_fraction * 100)}%`;
    await expect(chip).toHaveText(`${expected} selected`);
    checked++;
  }
  expect(checked).toBeGreaterThan(0);

  await page.getByRole("radio", { name: "Suggested topics" }).click();
  await expect(row(page, topic.id)).toHaveAttribute("data-check", "checked");
  expect(await stat(page, "sum-blocks")).toBe(before.blocks);
});

test("E2 counts update live, before the server answers", async ({ page, request }) => {
  await clearSelection(request);
  await page.goto("/scope");
  await waitForTree(page);
  await expect(page.getByTestId("sum-blocks")).toHaveText("0");
  await page.route("**/api/scope/selection", async (route) => {
    if (route.request().method() === "PUT") await new Promise((r) => setTimeout(r, 800));
    await route.continue();
  });
  const groups = await getGroups(request);
  const topic = groups[0].groups.topics.find((t) => !t.is_unassigned)!;
  await row(page, topic.id).click();
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(topic.block_count), { timeout: 100 });
  expect(await stat(page, "sum-pages")).toBeGreaterThan(0);
  await expect(page.locator("[data-testid=coverage-chip][data-stale=true]").first()).toBeVisible();
  await waitSettled(page);
  const server = await (await request.get("/api/scope/summary")).json();
  expect(await stat(page, "sum-blocks")).toBe(server.blocks);
  expect(await stat(page, "sum-figures")).toBe(server.figures);
  expect(await stat(page, "sum-pages")).toBe(server.pages);
  expect(await stat(page, "sum-queued")).toBe(server.review_load.queued);
});

test("E3 keyboard-only flow ends on /verify", async ({ page, request }) => {
  await page.goto("/scope");
  await expect(page.locator("[data-testid=row]:focus")).toBeVisible();
  const kb = page.keyboard;
  await kb.press("n");
  await expect(page.getByTestId("sum-blocks")).toHaveText("0");
  await kb.press("Escape");
  await expect(page.locator("[data-testid=row]:focus")).toBeVisible();
  await kb.press("j"); // row 2
  await kb.press("Space");
  await kb.press("j");
  await kb.press("j");
  await kb.press("Space");
  const groups = await getGroups(request);
  const topics = groups[0].groups.topics; // Unassigned first, then t001, t002, t003
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(topics[1].block_count + topics[3].block_count));
  await expect(row(page, topics[1].id)).toHaveAttribute("data-check", "checked");
  await expect(row(page, topics[2].id)).toHaveAttribute("data-check", "unchecked");
  await expect(row(page, topics[3].id)).toHaveAttribute("data-check", "checked");
  await waitSettled(page);

  await kb.press("t");
  await expect(page).toHaveURL(/view=structure/);
  await expect(page.getByRole("tree", { name: "Document structure" })).toBeVisible();
  await expect(page.locator("[data-testid=coverage-chip]").filter({ hasNotText: "0% selected" }).first()).toBeVisible();

  await kb.press("s");
  await expect(page.getByRole("radio", { name: /per document/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("sum-articles")).toHaveText(await page.getByTestId("sum-docs").innerText());

  await kb.press("m");
  await expect(page.locator("[data-zone=models] :focus")).toHaveCount(1);
  await kb.press("Escape");
  await expect(page.locator("[data-zone=tree] :focus")).toHaveCount(1);
  await kb.press("g");
  await expect(page).toHaveURL(/\/verify$/);
  const jobs = await (await request.get("/api/jobs")).json();
  expect(jobs.filter((j: { plan: { to?: string } }) => j.plan?.to === "score2").length).toBeGreaterThanOrEqual(1);
});

test("E4 low-cohesion marker", async ({ page }) => {
  await page.route("**/api/scope/groups", async (route) => {
    const res = await route.fetch();
    const docs = (await res.json()) as { groups: { topics: { is_unassigned: boolean; cohesion: number | null }[] } }[];
    docs.forEach((d, di) =>
      d.groups.topics.forEach((t, i) => {
        if (t.is_unassigned) t.cohesion = 0.01; // would be "low" if the rule ignored Unassigned
        else t.cohesion = di === 0 && i === 2 ? 0.1 : 0.9;
      }),
    );
    await route.fulfill({ response: res, json: docs });
  });
  await page.goto("/scope");
  await waitForTree(page);
  const badges = page.getByTestId("low-cohesion");
  await expect(badges).toHaveCount(1);
  await expect(badges.first()).toHaveText("Low cohesion");
  await expect(badges.first()).toHaveAttribute("aria-label", "Low cohesion 0.10");
  await expect(page.locator("[data-testid=row]", { hasText: "Unassigned blocks" }).first().getByTestId("low-cohesion")).toHaveCount(0);
});

test("E5 Unassigned topic first, selectable, absent from structure", async ({ page, request }) => {
  await clearSelection(request);
  await page.goto("/scope");
  await waitForTree(page);
  const groups = await getGroups(request);
  const un = groups[0].groups.topics[0];
  expect(un.is_unassigned).toBeTruthy();
  const first = page.getByTestId("row").first();
  await expect(first).toContainText("Unassigned blocks");
  await expect(first).toContainText("Catch-all");
  await first.click();
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(un.block_count));
  await page.getByRole("radio", { name: "Document structure" }).click();
  await expect(page.getByText("Unassigned blocks")).toHaveCount(0);
});

test("E6 model panel", async ({ page, request }) => {
  await page.goto("/scope");
  await waitForTree(page);
  const models = await (await request.get("/api/scope/models")).json();
  for (const t of ["cleanup", "grouping", "vision", "verifier", "embeddings"]) {
    const m = models.models[t];
    await expect(page.getByTestId(`model-${t}`)).toContainText(m ? `${m.provider}/${m.model}` : "not set");
  }
  await expect(page.getByTestId("hardware")).toContainText("GB RAM");
  const def = models.suggestions.default_tier as string;
  await expect(page.getByTestId("default-tier")).toContainText(def);
  await expect(page.locator(`[data-tier="${def}"]`)).toHaveAttribute("aria-checked", "true");
  if ((models.suggestions.pull_commands[def] ?? []).length) await expect(page.getByTestId("pull-commands")).toBeVisible();
  await expect(page.getByTestId("apply-tier")).toBeEnabled();
});

test("E7 reload restores selection, view and split", async ({ page, request }) => {
  await clearSelection(request);
  await page.goto("/scope?view=structure");
  await waitForTree(page);
  const groups = await getGroups(request);
  const parent = groups[0].groups.structure.find((g) => g.parent_id === null && groups[0].groups.structure.some((c) => c.parent_id === g.id))!;
  const ids = new Set(parent.block_ids);
  for (const c of groups[0].groups.structure) if (c.parent_id === parent.id) c.block_ids.forEach((b) => ids.add(b));
  await row(page, parent.id).click();
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(ids.size));
  await page.keyboard.press("s");
  await expect(page.getByRole("radio", { name: /per document/ })).toHaveAttribute("aria-checked", "true");
  await waitSettled(page);
  await expect.poll(async () => (await (await request.get("/api/scope/selection")).json()).selection.article_split).toBe("per_document");

  await page.reload();
  await waitForTree(page);
  await expect(page).toHaveURL(/view=structure/);
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(ids.size));
  await expect(row(page, parent.id)).toHaveAttribute("data-check", "checked");
  await expect(page.getByRole("radio", { name: /per document/ })).toHaveAttribute("aria-checked", "true");

  // Without ?view the server-persisted view is restored.
  await putOp(request, { op: "set_view", view: "structure" });
  await page.goto("/scope");
  await expect(page.getByRole("tree", { name: "Document structure" })).toBeVisible();
});

test("E8 subtree select with Space", async ({ page, request }) => {
  await clearSelection(request);
  await page.goto("/scope?view=structure");
  await waitForTree(page);
  const s = (await getGroups(request))[0].groups.structure;
  const parent = s.find((g) => g.parent_id === null && s.some((c) => c.parent_id === g.id))!;
  const kids = s.filter((c) => c.parent_id === parent.id);
  await row(page, kids[0].id).focus();
  await page.keyboard.press("Space");
  await expect(row(page, kids[0].id)).toHaveAttribute("data-check", "checked");
  await expect(row(page, parent.id)).toHaveAttribute("data-check", "mixed");
  await row(page, parent.id).focus();
  await page.keyboard.press("Space");
  await expect(row(page, parent.id)).toHaveAttribute("data-check", "checked");
  for (const k of kids) await expect(row(page, k.id)).toHaveAttribute("data-check", "checked");
  await page.keyboard.press("Space");
  await expect(row(page, parent.id)).toHaveAttribute("data-check", "unchecked");
  for (const k of kids) await expect(row(page, k.id)).toHaveAttribute("data-check", "unchecked");
  await expect(page.getByTestId("sum-blocks")).toHaveText("0");
});

test("E9 sources panel, scanned badge and OCR warning", async ({ page, request }) => {
  await page.goto("/scope");
  await waitForTree(page);
  const sources = (await (await request.get("/api/sources")).json()) as {
    slug: string;
    filename: string;
    kind: string;
    pages: number;
    ocr_warning: string | null;
    nodes: { node: string; state: string }[];
  }[];
  expect(sources.length).toBe(3);
  for (const s of sources) {
    const r = page.locator(`[data-testid=source-row][data-slug="${s.slug}"]`);
    await expect(r).toContainText(s.filename);
    await expect(r).toContainText(`${s.pages} page`);
    // The confirm job of E3 may leave `clean` stale after later selection changes: mirror the rule.
    const open = s.nodes.find((n) => n.state !== "fresh");
    await expect(r.getByTestId("source-chip")).toHaveText(open ? `Processing ${open.node}` : "Ready");
    if (s.kind === "scanned_pdf") await expect(r.getByTestId("scanned-badge")).toBeVisible();
    if (s.ocr_warning) await expect(r.getByTestId("ocr-warning")).toContainText(s.ocr_warning);
  }
  await page.route("**/api/sources", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const res = await route.fetch();
    const body = (await res.json()) as { ocr_warning: string | null; nodes: { node: string; state: string }[] }[];
    for (const b of body) b.nodes = b.nodes.map((n) => ({ ...n, state: "fresh" }));
    body[0].ocr_warning = "3 page(s) without a text layer";
    await route.fulfill({ response: res, json: body });
  });
  await page.reload();
  await expect(page.getByTestId("ocr-warning").first()).toContainText("OCR: 3 page(s) without a text layer");
  for (const chip of await page.getByTestId("source-chip").all()) await expect(chip).toHaveText("Ready");
});

test("E10 jobs are polled only while running", async ({ page }) => {
  let polls = 0;
  await page.route(/\/api\/jobs\?.*status=/, async (route) => {
    polls++;
    const running = polls <= 3;
    await route.fulfill({
      json: running
        ? [{ id: "j-fake", kind: "run", plan: {}, status: "running", progress: 0.4, units_done: 2, units_total: 5, node: "score2", doc: "clean", message: "scoring", created_at: "2026-01-01T00:00:00Z" }]
        : [],
    });
  });
  await page.route("**/api/jobs/j-fake", (route) => route.fulfill({ status: 404, json: { detail: "gone", code: "not_found" } }));
  await page.goto("/scope");
  await expect(page.locator("progress")).toBeVisible();
  await expect(page.locator("progress")).toBeHidden({ timeout: 10_000 });
  const settled = polls;
  expect(settled).toBeGreaterThanOrEqual(4);
  await page.waitForTimeout(3000);
  expect(polls).toBe(settled);
});
