// Independent UX check for module 8 (Scope), SPEC 7.1. One test per behaviour; each asserts the DOM and the server.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { clearSelection, getGroups, putOp, resetSelection, row, stat, waitForTree, waitSettled, type Group } from "./helpers";

const OUT = "e2e/artifacts/ux-scope";
mkdirSync(OUT, { recursive: true });
const shot = (page: Page, name: string) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
const report = (name: string, data: unknown) => writeFileSync(`${OUT}/${name}.json`, JSON.stringify(data, null, 2));

type Sel = { selection: { block_ids: string[]; active_view: string; article_split: string }; summary: Summary; coverage: Cov[] };
type Summary = { blocks: number; figures: number; pages: number; docs: number; articles: number; articles_per_topic: number; articles_per_document: number; review_load: { queued: number; numeric_queued: number; threshold: number } };
type Cov = { doc_id: string; structure: { group_id: string; fraction: number | null; subtree_fraction: number | null }[]; topics: { group_id: string; fraction: number | null }[] };
const getSel = async (page: Page): Promise<Sel> => (await page.request.get("/api/scope/selection")).json();
const getSummary = async (page: Page): Promise<Summary> => (await page.request.get("/api/scope/summary")).json();
const sorted = (a: string[]) => [...a].sort();

test.beforeAll(async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  expect((await ctx.post("/api/probe")).ok()).toBeTruthy();
  await ctx.dispose();
});
test.beforeEach(async ({ request }) => {
  await resetSelection(request);
});

/** True when the focused element shows an outline or a box-shadow ring (Tailwind ring). */
async function focusVisible(page: Page): Promise<{ ok: boolean; desc: string }> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return { ok: false, desc: "body" };
    const cs = getComputedStyle(el);
    const outline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
    const ring = cs.boxShadow !== "none" && /\d/.test(cs.boxShadow);
    const zone = el.closest("[data-zone]")?.getAttribute("data-zone") ?? "-";
    return { ok: outline || ring, desc: `${el.tagName.toLowerCase()}[${el.getAttribute("role") ?? ""}] zone=${zone} ${(el.textContent ?? "").trim().slice(0, 30)}` };
  });
}

test("1 sources list: parse status, OCR warning on scanned only", async ({ page }) => {
  await page.goto("/scope");
  await waitForTree(page);
  const src = (await (await page.request.get("/api/sources")).json()) as { slug: string; kind: string; ocr_warning: string | null; filename: string }[];
  const scanned = src.filter((s) => s.kind === "scanned_pdf");
  const clean = src.filter((s) => s.kind !== "scanned_pdf");
  expect(scanned.length).toBeGreaterThan(0);
  expect(clean.length).toBeGreaterThan(0);
  await expect(page.getByTestId("source-row")).toHaveCount(src.length);
  for (const s of src) {
    const r = page.locator(`[data-testid=source-row][data-slug="${s.slug}"]`);
    await expect(r.getByTestId("source-chip")).toHaveText(/Ready|Processing|Failed/);
  }
  for (const s of scanned) {
    const r = page.locator(`[data-testid=source-row][data-slug="${s.slug}"]`);
    await expect(r.getByTestId("scanned-badge")).toBeVisible();
    // Real API must supply a warning for the scanned doc, and the UI must show it.
    expect(s.ocr_warning, `server gave no ocr_warning for scanned ${s.slug}`).toBeTruthy();
    await expect(r.getByTestId("ocr-warning")).toContainText(s.ocr_warning!);
  }
  for (const s of clean) {
    const r = page.locator(`[data-testid=source-row][data-slug="${s.slug}"]`);
    expect(s.ocr_warning).toBeFalsy();
    await expect(r.getByTestId("ocr-warning")).toHaveCount(0);
    await expect(r.getByTestId("scanned-badge")).toHaveCount(0);
  }
  await shot(page, "01-sources");
});

test("2 toggle preserves selection; coverage shown in other view; back again", async ({ page }) => {
  await clearSelection(page.request);
  await page.goto("/scope");
  await waitForTree(page);
  const groups = await getGroups(page.request);
  const d = groups[0];
  const [a, b] = d.groups.topics.filter((t) => !t.is_unassigned);
  await row(page, a.id).click();
  await row(page, b.id).click();
  await waitSettled(page);
  await expect(row(page, a.id)).toHaveAttribute("data-check", "checked");
  await expect(row(page, b.id)).toHaveAttribute("data-check", "checked");
  const before = await getSel(page);
  expect(before.selection.block_ids.length).toBe(new Set([...a.block_ids, ...b.block_ids]).size);
  await shot(page, "02a-topic-view");

  await page.getByRole("radio", { name: "Document structure" }).click();
  await expect(page.getByRole("tree", { name: "Document structure" })).toBeVisible();
  await waitSettled(page);
  const mid = await getSel(page);
  expect(sorted(mid.selection.block_ids)).toEqual(sorted(before.selection.block_ids));
  expect(mid.selection.active_view).toBe("structure");
  // Structure rows covered by the selection show a chip > 0 equal to the server fraction.
  const cov = mid.coverage.flatMap((c) => c.structure).filter((c) => (c.subtree_fraction ?? 0) > 0);
  expect(cov.length).toBeGreaterThan(0);
  let shown = 0;
  for (const c of cov) {
    const chip = row(page, c.group_id).getByTestId("coverage-chip");
    if (!(await chip.count())) continue;
    const txt = await chip.innerText();
    const n = Number(/(\d+)%/.exec(txt)?.[1]);
    expect(n, txt).toBeGreaterThan(0);
    expect(n).toBe(Math.round(c.subtree_fraction! * 100));
    shown++;
  }
  expect(shown).toBeGreaterThan(0);
  // Rows with zero coverage must read 0%.
  const zero = mid.coverage.flatMap((c) => c.structure).find((c) => c.subtree_fraction === 0);
  if (zero && (await row(page, zero.group_id).count())) await expect(row(page, zero.group_id).getByTestId("coverage-chip")).toContainText("0%");
  await shot(page, "02b-structure-view");

  await page.getByRole("radio", { name: "Suggested topics" }).click();
  await waitSettled(page);
  await expect(row(page, a.id)).toHaveAttribute("data-check", "checked");
  await expect(row(page, b.id)).toHaveAttribute("data-check", "checked");
  const after = await getSel(page);
  expect(sorted(after.selection.block_ids)).toEqual(sorted(before.selection.block_ids));
  const checked = await page.locator("[data-testid=row][data-check=checked]").count();
  expect(checked).toBe(2);
  await shot(page, "02c-back-to-topics");
});

test("3 counts update live and equal the server after debounce", async ({ page }) => {
  await clearSelection(page.request);
  await page.goto("/scope");
  await waitForTree(page);
  await expect(page.getByTestId("sum-blocks")).toHaveText("0");
  const groups = await getGroups(page.request);
  const t = groups[0].groups.topics.filter((x) => !x.is_unassigned);
  // Slow the PUT so a pass can only come from the optimistic path, not a reload.
  await page.route("**/api/scope/selection", async (route) => {
    if (route.request().method() === "PUT") await new Promise((r) => setTimeout(r, 1200));
    await route.continue();
  });
  let navs = 0;
  page.on("framenavigated", () => navs++);
  const t0 = Date.now();
  await row(page, t[0].id).click();
  try {
    await expect(page.getByTestId("sum-blocks")).toHaveText(String(t[0].block_count), { timeout: 500 });
  } catch (e) {
    await page.waitForTimeout(2500);
    const diag = {
      rowCheck: await row(page, t[0].id).getAttribute("data-check"),
      sumBlocks: await page.getByTestId("sum-blocks").innerText(),
      serverBlocks: (await getSel(page)).selection.block_ids.length,
      toast: await page.getByTestId("toast").count(),
    };
    console.log("UX3 DIAG after missed optimistic update: " + JSON.stringify(diag));
    throw e;
  }
  const dt = Date.now() - t0;
  await waitSettled(page);
  const s1 = await getSummary(page);
  for (const [id, k] of [["sum-blocks", "blocks"], ["sum-figures", "figures"], ["sum-pages", "pages"], ["sum-articles", "articles"], ["sum-docs", "docs"]] as const)
    expect(await stat(page, id), id).toBe(s1[k]);
  expect(await stat(page, "sum-queued")).toBe(s1.review_load.queued);
  await shot(page, "03a-one-topic");
  // Deselect: counts drop live.
  await row(page, t[0].id).click();
  await expect(page.getByTestId("sum-blocks")).toHaveText("0", { timeout: 500 });
  await waitSettled(page);
  expect((await getSummary(page)).blocks).toBe(0);
  expect(navs).toBe(0);
  console.log(`UX3 optimistic count latency ~${dt} ms (server PUT delayed 1200 ms)`);
});

test("4 low-cohesion marker", async ({ page }) => {
  const groups = await getGroups(page.request);
  const natural = groups.flatMap((d) => d.groups.topics.filter((t) => !t.is_unassigned && t.cohesion != null && t.cohesion < d.groups.params.low_cohesion));
  let injected = false;
  if (!natural.length) {
    injected = true;
    await page.route("**/api/scope/groups", async (route) => {
      const res = await route.fetch();
      const docs = (await res.json()) as { groups: { topics: { is_unassigned: boolean; cohesion: number | null }[] } }[];
      const t = docs[0].groups.topics.find((x) => !x.is_unassigned)!;
      t.cohesion = 0.12;
      await route.fulfill({ response: res, json: docs });
    });
  }
  console.log(`UX4 natural low-cohesion topics in seeded project: ${natural.length}; injected=${injected}`);
  await page.goto("/scope");
  await waitForTree(page);
  const n = natural.length || 1;
  await expect(page.getByTestId("low-cohesion")).toHaveCount(n);
  const badge = page.getByTestId("low-cohesion").first();
  await expect(badge).toBeVisible();
  // Visible and not Unassigned; non-low topics have no badge.
  const lowRows = page.locator("[data-testid=row]:has([data-testid=low-cohesion])");
  await expect(lowRows).toHaveCount(n);
  await expect(lowRows.filter({ hasText: "Catch-all" })).toHaveCount(0);
  expect(await page.getByTestId("row").count()).toBeGreaterThan(n);
  await shot(page, "04-low-cohesion");
});

test("5 unassigned catch-all row with block count", async ({ page }) => {
  await page.goto("/scope");
  await waitForTree(page);
  const groups = await getGroups(page.request);
  for (const d of groups) {
    const un = d.groups.topics.find((t) => t.is_unassigned)!;
    expect(un).toBeTruthy();
    const r = row(page, un.id);
    await expect(r).toContainText("Unassigned blocks");
    await expect(r).toContainText("Catch-all");
    await expect(r.getByTestId("row-meta")).toContainText(new RegExp(`\\b${un.block_count} blocks?\\b`));
  }
  await shot(page, "05-unassigned");
});

test("6 split mode changes article count; persists after reload", async ({ page }) => {
  await page.goto("/scope");
  await waitForTree(page);
  await waitSettled(page);
  const s0 = await getSummary(page);
  expect(await stat(page, "sum-articles")).toBe(s0.articles_per_topic);
  await page.getByRole("radio", { name: /per document/ }).click();
  await expect(page.getByTestId("sum-articles")).toHaveText(String(s0.articles_per_document));
  await expect.poll(async () => (await getSel(page)).selection.article_split).toBe("per_document");
  const s1 = await getSummary(page);
  expect(s1.articles).toBe(s0.articles_per_document);
  expect(s1.articles).toBe(s1.docs);
  console.log(`UX6 articles per_topic=${s0.articles_per_topic} per_document=${s0.articles_per_document}`);
  expect(s0.articles_per_document).not.toBe(s0.articles_per_topic);
  await shot(page, "06a-per-document");
  await page.reload();
  await waitForTree(page);
  await expect(page.getByRole("radio", { name: /per document/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("sum-articles")).toHaveText(String(s0.articles_per_document));
  await page.getByRole("radio", { name: /per topic/ }).click();
  await expect(page.getByTestId("sum-articles")).toHaveText(String(s0.articles_per_topic));
  await expect.poll(async () => (await getSel(page)).selection.article_split).toBe("per_topic");
  await shot(page, "06b-per-topic");
});

test("7 model panel: per-task models, probe suggestion, apply control", async ({ page }) => {
  await page.goto("/scope");
  await waitForTree(page);
  const m = await (await page.request.get("/api/scope/models")).json();
  for (const t of ["cleanup", "grouping", "vision"]) {
    const ref = m.models[t];
    expect(ref, `no model configured for ${t}`).toBeTruthy();
    await expect(page.getByTestId(`model-${t}`)).toContainText(`${ref.provider}/${ref.model}`);
  }
  expect(m.probe, "no probe in /api/scope/models").toBeTruthy();
  await expect(page.getByTestId("hardware")).toContainText(`${m.probe.ram_gb} GB RAM`);
  await expect(page.getByTestId("default-tier")).toContainText(m.suggestions.default_tier);
  await expect(page.locator(`[data-tier="${m.suggestions.default_tier}"]`)).toHaveAttribute("aria-checked", "true");
  await expect(page.locator(`[data-tier="${m.suggestions.default_tier}"]`)).toContainText("suggested");
  const apply = page.getByTestId("apply-tier");
  await expect(apply).toBeEnabled();
  await expect(apply).toContainText(`Apply ${m.suggestions.default_tier}`);
  // Not clicked: applying rewrites project config and marks stages stale. No dry-run endpoint exists.
  await page.getByTestId("model-panel").scrollIntoViewIfNeeded();
  await shot(page, "07-model-panel");
});

test("8 review-load estimate equals queued selected blocks", async ({ page }) => {
  const blocks = (await (await page.request.get("/api/scope/blocks")).json()) as { doc_id: string; blocks: { id: string; status: string; numeric: boolean }[] }[];
  const all = blocks.flatMap((b) => b.blocks);
  const queuedAll = all.filter((b) => b.status === "queued").length;
  console.log(`UX8 blocks=${all.length} queued(all)=${queuedAll}`);
  await page.goto("/scope");
  await waitForTree(page);
  const groups = await getGroups(page.request);
  const check = async (label: string) => {
    await waitSettled(page);
    const sel = await getSel(page);
    const ids = new Set(sel.selection.block_ids);
    const sel_rows = all.filter((b) => ids.has(b.id));
    const q = sel_rows.filter((b) => b.status === "queued");
    const qn = q.filter((b) => b.numeric).length;
    expect(await stat(page, "sum-queued"), `${label} ui`).toBe(q.length);
    expect(await stat(page, "sum-numeric"), `${label} numeric ui`).toBe(qn);
    expect(sel.summary.review_load.queued, `${label} server`).toBe(q.length);
    return q.length;
  };
  await check("default-all");
  await page.keyboard.press("n");
  await page.keyboard.press("n"); // clearing needs a second press
  await expect(page.getByTestId("sum-blocks")).toHaveText("0");
  expect(await check("none")).toBe(0);
  let sawNonzero = queuedAll > 0;
  for (const t of groups.flatMap((d) => d.groups.topics)) {
    await row(page, t.id).click();
    if ((await check(`topic ${t.id}`)) > 0) sawNonzero = true;
    await row(page, t.id).click();
  }
  expect(sawNonzero, "no queued blocks anywhere: estimate untested beyond zero").toBeTruthy();
  await page.keyboard.press("a");
  await expect(page.getByTestId("sum-blocks")).not.toHaveText("0");
  await check("all");
  await shot(page, "08-review-load");
});

test("9 keyboard-only flow, focus visible at each step, ends on /verify", async ({ page }) => {
  await clearSelection(page.request);
  await page.goto("/scope");
  await waitForTree(page);
  const kb = page.keyboard;
  const steps: string[] = [];
  const missing: string[] = [];
  // Settle for 700 ms (re-renders), then record; the flow continues so later steps are still exercised.
  const mustSee = async (label: string) => {
    let f = await focusVisible(page);
    for (let i = 0; i < 14 && !f.ok; i++) {
      await page.waitForTimeout(50);
      f = await focusVisible(page);
    }
    steps.push(`${label}: ${f.desc} visible=${f.ok}`);
    if (!f.ok) missing.push(`"${label}" -> ${f.desc}`);
  };
  // The app autofocuses the tree on load. Walk Shift+Tab to the start of the page (focus leaves to the browser,
  // activeElement becomes body), then Tab forward into the tree; every stop must show a focus indicator.
  const back: string[] = [];
  for (let i = 0; i < 40; i++) {
    await kb.press("Shift+Tab");
    const f = await focusVisible(page);
    if (f.desc === "body") break;
    back.push(f.desc);
    expect(f.ok, `no focus indicator going backwards on ${f.desc}`).toBeTruthy();
  }
  const stops: string[] = [];
  let inTree = false;
  for (let i = 0; i < 40 && !inTree; i++) {
    await kb.press("Tab");
    await mustSee(`tab${i}`);
    const z = await page.evaluate(() => document.activeElement?.closest("[data-zone]")?.getAttribute("data-zone") ?? "-");
    stops.push(z);
    inTree = z === "tree";
  }
  expect(inTree, `never reached the tree via Tab; stops=${stops}`).toBeTruthy();
  await shot(page, "09a-tab-into-tree");
  const groups = await getGroups(page.request);
  const topics = groups[0].groups.topics;
  // Cursor starts on row 0 (Unassigned). j moves, k moves back.
  const cur = () => page.evaluate(() => (document.activeElement as HTMLElement).getAttribute("data-group-id"));
  const first = await cur();
  await kb.press("j");
  const second = await cur();
  expect(second).not.toBe(first);
  await mustSee("j");
  await kb.press("k");
  expect(await cur()).toBe(first);
  await mustSee("k");
  await kb.press("j");
  await kb.press("Space");
  await mustSee("space");
  await expect(row(page, second!)).toHaveAttribute("data-check", "checked");
  await expect.poll(async () => (await getSel(page)).selection.block_ids.length).toBe(topics.find((t) => t.id === second)!.block_count);
  await kb.press("t");
  await expect(page).toHaveURL(/view=structure/);
  await expect.poll(async () => (await getSel(page)).selection.active_view).toBe("structure");
  await mustSee("t");
  await shot(page, "09b-structure-after-t");
  await kb.press("s");
  await expect.poll(async () => (await getSel(page)).selection.article_split).toBe("per_document");
  await mustSee("s");
  await kb.press("m");
  expect(await page.evaluate(() => !!document.activeElement?.closest("[data-zone=models]"))).toBeTruthy();
  await mustSee("m (model panel)");
  await shot(page, "09c-model-panel-focus");
  await kb.press("Escape");
  expect(await page.evaluate(() => !!document.activeElement?.closest("[data-zone=tree]"))).toBeTruthy();
  await mustSee("escape (tree)");
  await kb.press("g");
  await expect(page).toHaveURL(/\/verify$/);
  const jobs = (await (await page.request.get("/api/jobs")).json()) as { kind: string }[];
  expect(jobs.length).toBeGreaterThan(0);
  await shot(page, "09d-verify");
  report("09-keyboard-steps", { back, stops, steps, missing });
  expect(missing, `focus indicator missing after: ${missing.join("; ")}`).toEqual([]);
});

test("10 subtree select selects every descendant (GroupsFile)", async ({ page }) => {
  await clearSelection(page.request);
  await page.goto("/scope?view=structure");
  await waitForTree(page);
  const groups = await getGroups(page.request);
  let best: { doc: number; g: Group; ids: Set<string>; n: number } | null = null;
  groups.forEach((d, di) => {
    const s = d.groups.structure;
    const desc = (id: string): Group[] => s.filter((c) => c.parent_id === id).flatMap((c) => [c, ...desc(c.id)]);
    for (const g of s) {
      const ds = desc(g.id);
      if (!ds.length) continue;
      const ids = new Set([...g.block_ids, ...ds.flatMap((x) => x.block_ids)]);
      if (!best || ds.length > best.n) best = { doc: di, g, ids, n: ds.length };
    }
  });
  expect(best, "no parent structure group").toBeTruthy();
  const b = best!;
  await page.getByRole("tree", { name: "Document structure" }).waitFor();
  await row(page, b.g.id).focus();
  await page.keyboard.press("Space");
  await waitSettled(page);
  await expect(row(page, b.g.id)).toHaveAttribute("data-check", "checked");
  const sel = await getSel(page);
  expect(sorted(sel.selection.block_ids)).toEqual(sorted([...b.ids]));
  expect(b.ids.size).toBeGreaterThan(b.g.block_ids.length > 0 ? 0 : -1);
  console.log(`UX10 parent ${b.g.id}: own=${b.g.block_ids.length} subtree=${b.ids.size} descendants=${b.n}`);
  await shot(page, "10-subtree");
  await page.keyboard.press("Space");
  await expect.poll(async () => (await getSel(page)).selection.block_ids.length).toBe(0);
});

test("11 reload restores selection and view", async ({ page }) => {
  await clearSelection(page.request);
  await page.goto("/scope");
  await waitForTree(page);
  const groups = await getGroups(page.request);
  const [a, b] = groups[0].groups.topics.filter((t) => !t.is_unassigned);
  await row(page, a.id).click();
  await row(page, b.id).click();
  await page.getByRole("radio", { name: "Document structure" }).click();
  await waitSettled(page);
  const before = await getSel(page);
  const blocks = await stat(page, "sum-blocks");
  await page.goto("/scope"); // no ?view: server-persisted view must win
  await waitForTree(page);
  await expect(page.getByRole("tree", { name: "Document structure" })).toBeVisible();
  expect(await stat(page, "sum-blocks")).toBe(blocks);
  const after = await getSel(page);
  expect(sorted(after.selection.block_ids)).toEqual(sorted(before.selection.block_ids));
  expect(after.selection.active_view).toBe("structure");
  await page.getByRole("radio", { name: "Suggested topics" }).click();
  await expect(row(page, a.id)).toHaveAttribute("data-check", "checked");
  await expect(row(page, b.id)).toHaveAttribute("data-check", "checked");
  await shot(page, "11-reload");
});

test("12 job progress shown; UI interactive while a job runs", async ({ page }) => {
  // (a) simulated running job: progress is displayed and a PUT stays fast.
  let until = 0;
  await page.route(/\/api\/jobs\?.*status=/, async (route) => {
    await route.fulfill({
      json: Date.now() < until ? [{ id: "j-sim", kind: "run", plan: {}, status: "running", progress: 0.4, units_done: 2, units_total: 5, node: "score2", doc: "clean", message: "scoring", created_at: "2026-01-01T00:00:00Z" }] : [],
    });
  });
  await page.route("**/api/jobs/j-sim", (r) => r.fulfill({ status: 404, json: { detail: "gone", code: "not_found" } }));
  until = Date.now() + 8000;
  await clearSelection(page.request);
  await page.goto("/scope");
  await waitForTree(page);
  await expect(page.getByTestId("jobs-bar")).toBeVisible();
  await expect(page.locator("progress")).toHaveAttribute("value", "0.4");
  // review M13 P2-11: progress reads "2 of 5 steps", never "2/5"
  await expect(page.getByTestId("job-row")).toContainText("2 of 5 steps");
  const groups = await getGroups(page.request);
  const t = groups[0].groups.topics.find((x) => !x.is_unassigned)!;
  const resp = page.waitForResponse((r) => r.url().includes("/api/scope/selection") && r.request().method() === "PUT");
  const t0 = Date.now();
  await row(page, t.id).click();
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(t.block_count), { timeout: 500 });
  await resp;
  const simMs = Date.now() - t0;
  await shot(page, "12a-simulated-job");
  console.log(`UX12 simulated job: click->server PUT done ${simMs} ms`);
  expect(simMs).toBeLessThan(500 + 150);
  until = 0;

  // (b) real job on the server: PUT latency while it runs.
  const start = await page.request.post("/api/jobs", { data: { to: "score2", force: ["score2"] } });
  const startBody = await start.text();
  console.log(`UX12 real job start: ${start.status()} ${startBody.slice(0, 160)}`);
  expect(start.status()).toBeLessThan(300);
  const job = JSON.parse(startBody) as { id: string };
  let ran = 0;
  const lat: number[] = [];
  for (let i = 0; i < 30; i++) {
    const st = (await (await page.request.get(`/api/jobs/${job.id}`)).json()) as { status: string };
    if (st.status !== "running" && st.status !== "queued" && st.status !== "pending") break;
    ran++;
    const s = Date.now();
    await putOp(page.request, { op: i % 2 ? "deselect_group" : "select_group", group_id: t.id, doc_id: groups[0].doc_id });
    lat.push(Date.now() - s);
  }
  console.log(`UX12 real job: PUTs during run=${ran} latencies=${lat.join(",")}`);
  report("12-real-job", { ran, lat });
  if (ran > 0) expect(Math.max(...lat)).toBeLessThan(500);
  // Wait for the job to finish so later tests see a settled project.
  for (let i = 0; i < 120; i++) {
    const st = (await (await page.request.get(`/api/jobs/${job.id}`)).json()) as { status: string };
    if (!["running", "queued", "pending"].includes(st.status)) break;
    await page.waitForTimeout(1000);
  }
});

test("13 accessibility: tree roles/aria and axe", async ({ page }) => {
  await page.goto("/scope?view=structure");
  await waitForTree(page);
  const tree = page.getByRole("tree", { name: "Document structure" });
  await expect(tree).toHaveAttribute("aria-multiselectable", "true");
  const items = tree.getByRole("treeitem");
  const n = await items.count();
  expect(n).toBeGreaterThan(0);
  for (let i = 0; i < n; i++) {
    const it = items.nth(i);
    await expect(it).toHaveAttribute("aria-selected", /true|false/);
    await expect(it).toHaveAttribute("aria-level", /^\d+$/);
  }
  await expect(page.locator("[role=treeitem][aria-expanded]").first()).toBeVisible();
  const violations: unknown[] = [];
  const bad: string[] = [];
  const run = async (label: string) => {
    const r = await new AxeBuilder({ page }).analyze();
    for (const v of r.violations) {
      violations.push({ view: label, id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length, targets: v.nodes.slice(0, 3).map((x) => x.target.join(" ")) });
      if (v.id !== "color-contrast" && (v.impact === "serious" || v.impact === "critical")) bad.push(`${label}:${v.id}(${v.impact})`);
    }
  };
  await run("structure");
  await shot(page, "13a-structure-a11y");
  await page.getByRole("radio", { name: "Suggested topics" }).click();
  await expect(page.getByRole("listbox", { name: "Suggested topics" })).toBeVisible();
  for (const o of await page.getByRole("option").all()) await expect(o).toHaveAttribute("aria-selected", /true|false/);
  await run("topics");
  await shot(page, "13b-topics-a11y");
  report("13-axe", violations);
  console.log("UX13 axe violations: " + JSON.stringify(violations));
  expect(bad, `serious axe violations: ${bad}`).toEqual([]);
});

test("14 responsiveness numbers", async ({ page }) => {
  const t0 = Date.now();
  await page.goto("/scope", { waitUntil: "commit" });
  await expect(page.getByTestId("row").first()).toBeVisible();
  await expect(page.getByTestId("sum-blocks")).toBeVisible();
  await expect(page.getByTestId("model-panel")).toBeVisible();
  const tti = Date.now() - t0;
  const nav = await page.evaluate(() => {
    const e = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming;
    return { dcl: Math.round(e.domContentLoadedEventEnd), load: Math.round(e.loadEventEnd) };
  });
  const groups = await getGroups(page.request);
  const t = groups[0].groups.topics.find((x) => !x.is_unassigned)!;
  await clearSelection(page.request);
  await page.reload();
  await waitForTree(page);
  const s = Date.now();
  const resp = page.waitForResponse((r) => r.url().includes("/api/scope/selection") && r.request().method() === "PUT");
  await row(page, t.id).click();
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(t.block_count));
  const ui = Date.now() - s;
  await resp;
  const rt = Date.now() - s;
  await waitSettled(page);
  const settled = Date.now() - s;
  const nums = { tti_ms: tti, ...nav, optimistic_ui_ms: ui, put_done_ms: rt, chips_settled_ms: settled, rows: await page.getByTestId("row").count() };
  console.log("UX14 " + JSON.stringify(nums));
  report("14-perf", nums);
  expect(tti).toBeLessThan(3000);
  expect(settled).toBeLessThan(3000);
  await shot(page, "14-perf");
});
