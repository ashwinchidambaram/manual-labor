// Module 9 (Verify) end to end against the seeded mock project (design 09 section 6.3). Tests run in order; all
// server assertions are deltas against what the test saw before it acted.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { diffSegments } from "../src/verify/diffSegments";
import type { BlockDetail, Cursor, DocFigure, FigureRailItem, PageBlock, QueuePage } from "../src/api/schema";
import { api, resetSelection, waitJobsIdle } from "./helpers";

test.describe.configure({ mode: "serial" });

const rid = (): string => `ve-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const getQueue = async (request: APIRequestContext, query = ""): Promise<QueuePage> =>
  api(request).get<QueuePage>(`/api/verify/queue?limit=2000${query}`);
const getDetail = (request: APIRequestContext, id: string): Promise<BlockDetail> => api(request).get<BlockDetail>(`/api/verify/blocks/${id}`);
const getCursor = (request: APIRequestContext): Promise<Cursor> => api(request).get<Cursor>("/api/verify/cursor");
async function putCursor(request: APIRequestContext, current: string | null, extra: Partial<Cursor> = {}): Promise<void> {
  await api(request).put("/api/verify/cursor", {
    sort: "worst_first",
    view_threshold: null,
    doc_filter: null,
    current_block_id: current,
    request_id: rid(),
    ...extra,
  });
}
const card = (page: Page, id: string) => page.getByTestId(`card-${id}`);
const key = (page: Page, k: string) => page.keyboard.press(k);

interface ActionRow {
  id: number;
  kind: string;
  screen: string;
}
async function actionRows(request: APIRequestContext): Promise<ActionRow[]> {
  const r = await request.get("/api/decisions/export");
  return (await r.text())
    .split("\n")
    .filter(Boolean)
    .map((l) => JSON.parse(l) as ActionRow);
}

test.beforeAll(async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  await resetSelection(ctx);
  const r = await ctx.post("/api/scope/confirm", { data: {} });
  expect(r.ok(), await r.text()).toBeTruthy();
  await waitJobsIdle(ctx);
  const q = await getQueue(ctx);
  const problems: string[] = [];
  if (q.total < 30) problems.push(`queue total ${q.total} < 30`);
  if (!q.items.some((i) => i.has_numeric_spec && i.status === "queued")) problems.push("no queued numeric block");
  const withAuto = await getQueue(ctx, "&view_threshold=1");
  if (!withAuto.items.some((i) => i.status === "auto_approved" && (i.confidence ?? 1) < 1)) problems.push("no auto-approved block with confidence < 1");
  const figs = await api(ctx).get<DocFigure[]>("/api/docs/figures/figures");
  const arts = new Set(figs.flatMap((f) => (f.attachments ?? []).map((a) => a.article_id)));
  if (arts.size < 2) problems.push("figures doc has fewer than 2 articles");
  expect(problems, `VE preconditions: ${problems.join("; ")}`).toEqual([]);
  await ctx.dispose();
});

test.beforeEach(async ({ request }) => {
  await waitJobsIdle(request);
});

test("VE1 twenty blocks keyboard-only (gate)", async ({ page, request }) => {
  const Q = (await getQueue(request)).items;
  await putCursor(request, Q[0].block_id);
  type Role = "A" | "EDIT_OK" | "EDIT_409" | "FLAG1" | "FLAG5" | "SKIP" | "AKA";
  const roles: Role[] = ["A", "A", "EDIT_OK", "A", "FLAG1", "A", "SKIP", "A", "EDIT_409", "A", "AKA", "A", "FLAG5", "A", "A", "A", "A", "A", "A", "A"];
  const details = await Promise.all(Q.slice(0, 20).map((i) => getDetail(request, i.block_id)));
  const eligible = (role: Role, d: BlockDetail): boolean =>
    role === "EDIT_OK" ? d.block.type !== "figure" && d.block.faithfulness?.passed !== false : role === "EDIT_409" ? d.block.type !== "figure" : true;
  for (let i = 0; i < 20; i++) {
    if (eligible(roles[i], details[i])) continue;
    const j = roles.findIndex((r, k) => k > i && r === "A" && eligible(roles[i], details[k]));
    expect(j, `no swap partner for slot ${i} (${roles[i]})`).toBeGreaterThan(-1);
    [roles[i], roles[j]] = [roles[j], roles[i]];
  }
  console.log("VE1 plan", roles.map((r, i) => `${i}:${r}:${Q[i].block_id}`).join(" "));

  const before = (await getQueue(request)).counts;
  const maxId = Math.max(0, ...(await actionRows(request)).map((r) => r.id));
  await page.goto("/verify");
  await expect(card(page, Q[0].block_id)).toBeFocused();

  const nextFocused = async (i: number): Promise<void> => expect(card(page, Q[i + 1].block_id)).toBeFocused();
  const edit = async (i: number, suffix: string, conflict: boolean): Promise<void> => {
    await key(page, "e");
    const ta = page.getByLabel("Edit block text");
    await expect(ta).toBeFocused();
    await key(page, "ControlOrMeta+End");
    await page.keyboard.type(suffix);
    await key(page, "ControlOrMeta+Enter");
    if (conflict) {
      await expect(page.getByTestId("edit-conflict")).toBeVisible();
      await expect(page.getByTestId("numeric-changes")).toBeVisible();
      await expect(page.getByRole("button", { name: "Confirm content change" })).toBeFocused();
      await key(page, "Enter");
    }
    await nextFocused(i);
  };
  for (let i = 0; i < 20; i++) {
    switch (roles[i]) {
      case "A":
        await key(page, "a");
        await nextFocused(i);
        break;
      case "EDIT_OK":
        await edit(i, " ", false);
        break;
      case "EDIT_409":
        await edit(i, " 999", true);
        break;
      case "FLAG1":
        await key(page, "f");
        await expect(page.getByRole("radiogroup")).toBeFocused();
        await key(page, "1");
        await key(page, "Tab");
        await expect(page.getByLabel("Note (optional)")).toBeFocused();
        await page.keyboard.type("digit unclear");
        await key(page, "ControlOrMeta+Enter");
        await nextFocused(i);
        break;
      case "FLAG5":
        await key(page, "f");
        await expect(page.getByRole("radiogroup")).toBeFocused();
        await key(page, "5");
        await key(page, "Enter");
        await nextFocused(i);
        break;
      case "SKIP":
        await key(page, "j");
        await nextFocused(i);
        break;
      case "AKA":
        await key(page, "a");
        await nextFocused(i);
        await key(page, "k");
        await expect(card(page, Q[i].block_id)).toBeFocused();
        await expect(card(page, Q[i].block_id)).toHaveAttribute("data-pinned", "true");
        await key(page, "a");
        await nextFocused(i);
        break;
    }
  }
  await expect(page.getByTestId("save-state")).toHaveText("Saved");
  await expect(card(page, Q[20].block_id)).toBeFocused();

  const rows = (await actionRows(request)).filter((r) => r.id > maxId && r.screen === "verify");
  const count = (k: string): number => rows.filter((r) => r.kind === k).length;
  const kinds = { approve: count("approve"), edit: count("edit"), flag: count("flag"), skip: count("skip"), back: count("back") };
  console.log("VE1 server-side decision counts", JSON.stringify(kinds));
  expect(kinds).toEqual({ approve: 16, edit: 2, flag: 2, skip: 1, back: 1 });
  const after = (await getQueue(request)).counts;
  expect({
    approved: (after.approved ?? 0) - (before.approved ?? 0),
    edited: (after.edited ?? 0) - (before.edited ?? 0),
    flagged_open: (after.flagged_open ?? 0) - (before.flagged_open ?? 0),
    skipped: (after.skipped ?? 0) - (before.skipped ?? 0),
  }).toEqual({ approved: 15, edited: 2, flagged_open: 2, skipped: 1 });
  const cur = await getCursor(request);
  expect(cur.current_block_id).toBe(Q[20].block_id);
  expect(cur.trail?.[(cur.trail?.length ?? 1) - 1]).toBe(Q[19].block_id);
  const skipped = roles.indexOf("SKIP");
  await expect(card(page, Q[skipped].block_id)).toBeVisible();
  const e409 = await getDetail(request, Q[roles.indexOf("EDIT_409")].block_id);
  expect(e409.block.status).toBe("edited");
  expect(e409.history?.[e409.history.length - 1]?.faith_passed).toBe(false);
  const eOk = await getDetail(request, Q[roles.indexOf("EDIT_OK")].block_id);
  expect(eOk.history?.[eOk.history.length - 1]?.faith_passed).toBe(true);
  const f1 = (await api(request).get<{ target_id: string; category: string; note: string | null }[]>("/api/flags")).find((f) => f.target_id === Q[roles.indexOf("FLAG1")].block_id);
  expect(f1?.category).toBe("wrong_text");
  expect(f1?.note).toBe("digit unclear");
});

test("VE2 diff view renders exactly the DiffOp table (gate)", async ({ page, request }) => {
  const Q = (await getQueue(request)).items.filter((i) => i.type !== "figure");
  let pick: BlockDetail | null = null;
  for (const it of Q.slice(0, 120)) {
    const d = await getDetail(request, it.block_id);
    const ops = d.block.faithfulness?.diff ?? [];
    if (!ops.some((o) => o.op !== "equal")) continue;
    if (!pick || (d.block.raw_text.includes("lubri") && !pick.block.raw_text.includes("lubri"))) pick = d;
    if (pick.block.raw_text.includes("lubri")) break;
  }
  expect(pick, "a queued block with a non-equal diff op").not.toBeNull();
  const d = pick!;
  await putCursor(request, d.block.id);
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(d.block.id);
  await key(page, "t");
  await expect(page.getByTestId("view-diff")).toHaveAttribute("aria-pressed", "true");
  const segs = diffSegments(d.block.faithfulness!.diff);
  expect(segs.length).toBeGreaterThan(0);
  for (const s of segs) {
    const name = s.kind === "equal" ? "equal" : `${s.kind}-${s.ok ? "ok" : "bad"}`;
    const loc = page.locator(`[data-testid=diff-view] [data-op-index="${s.opIndex}"][data-seg="${name}"]`);
    await expect(loc.filter({ hasText: /./ }).first()).toBeVisible();
    const texts = await loc.evaluateAll((els) => els.map((e) => e.textContent));
    expect(texts, `op ${s.opIndex} ${name}`).toContain(s.display);
  }
  if (d.block.raw_text.includes("lubri-\ncation")) {
    const ok = page.locator("[data-seg='del-ok']").filter({ hasText: "-↵" });
    await expect(ok.first()).toBeVisible();
  }
  await page.screenshot({ path: "e2e/artifacts/verify-diff.png", fullPage: true });
});

async function articleBlocks(request: APIRequestContext): Promise<Map<string, string>> {
  // article id -> a queued block whose FIRST article is that article
  const out = new Map<string, string>();
  const Q = (await getQueue(request)).items.filter((i) => i.doc_id === "figures" && i.type !== "figure");
  for (const it of Q.slice(0, 80)) {
    const d = await getDetail(request, it.block_id);
    const a = d.article_ids?.[0];
    if (a && !out.has(a)) out.set(a, it.block_id);
  }
  return out;
}

test("VE3 figure re-attach via the keyboard picker persists, then detach (gate)", async ({ page, request }) => {
  const byArticle = await articleBlocks(request);
  const figs = await api(request).get<DocFigure[]>("/api/docs/figures/figures");
  let target: { b: string; block: string; f: DocFigure } | null = null;
  for (const [b, block] of byArticle)
    for (const f of figs) {
      if ((f.attachments ?? []).some((a) => a.article_id === b)) continue;
      if (!(f.attachments ?? []).length) continue;
      target = { b, block, f };
      break;
    }
  expect(target, "an article with a queued block and a figure not attached to it").not.toBeNull();
  const { b, block, f } = target!;
  const prev = (f.attachments ?? []).map((a) => a.article_id);
  await putCursor(request, block);
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(block);
  await expect(page.getByTestId("rail-attach").first()).toBeVisible();
  await key(page, "g");
  await expect(page.getByTestId("rail-attach").first()).toBeFocused();
  await key(page, "Enter");
  await expect(page.getByTestId("figure-picker")).toBeVisible();
  await page.keyboard.type(f.figure_id);
  await key(page, "ArrowDown");
  await page.screenshot({ path: "e2e/artifacts/verify-picker.png" });
  await key(page, "Enter");
  const item = page.getByTestId(`rail-item-${f.figure_id}`).first();
  await expect(item).toBeVisible();
  await expect(item.getByTestId("rail-rule")).toHaveText("human");
  await expect(item.getByTestId("rail-pending")).toBeVisible();
  await waitJobsIdle(request);
  await page.reload();
  await expect(page.getByTestId("block-id")).toHaveText(block);
  const again = page.getByTestId("figure-rail").getByTestId(`rail-item-${f.figure_id}`).first();
  await expect(again.getByTestId("rail-rule")).toHaveText("human");
  const railB = await api(request).get<FigureRailItem[]>(`/api/articles/${b}/figures`);
  expect(railB.find((x) => x.figure_id === f.figure_id)?.attachment?.rule).toBe("human");
  for (const a of prev) {
    const r = await api(request).get<FigureRailItem[]>(`/api/articles/${a}/figures`);
    expect(r.map((x) => x.figure_id), `previous article ${a}`).not.toContain(f.figure_id);
  }
  // detach with x
  await again.focus();
  await key(page, "x");
  await expect(page.getByTestId(`rail-item-${f.figure_id}`).first().getByTestId("rail-pending")).toBeVisible();
  await waitJobsIdle(request);
  await page.reload();
  await expect(page.getByTestId("block-id")).toHaveText(block);
  await expect(page.getByTestId("figure-rail").getByTestId(`rail-item-${f.figure_id}`)).toHaveCount(0);
  const railAfter = await api(request).get<FigureRailItem[]>(`/api/articles/${b}/figures`);
  expect(railAfter.map((x) => x.figure_id)).not.toContain(f.figure_id);
});

test("VE4 threshold slider is a view filter only", async ({ page, request }) => {
  const T = (await api(request).get<{ config: { threshold: number } }>("/api/project")).config.threshold;
  const all = await getQueue(request, "&view_threshold=1");
  const autos = all.items.filter((i) => i.status === "auto_approved" && (i.confidence ?? 1) < 1);
  const a1 = autos.reduce((m, i) => ((i.confidence ?? 1) < (m.confidence ?? 1) ? i : m), autos[0]);
  const c = a1.confidence ?? 0;
  await putCursor(request, (await getQueue(request)).items[0].block_id);
  await page.goto("/verify");
  await expect(page.getByTestId("view-copy")).toHaveText(/Only blocks under/);
  await expect(card(page, a1.block_id)).toHaveCount(0);
  let guard = 0;
  for (;;) {
    await key(page, "]");
    const txt = (await page.getByTestId("view-copy").innerText()).trim();
    const m = /below (\d\.\d+)/.exec(txt);
    if (m && Number(m[1]) > c) break;
    expect(++guard, `slider never passed ${c}: ${txt}`).toBeLessThan(10);
  }
  await expect(page.getByTestId("view-copy")).toHaveText(/^Showing \d/);
  const copy = (await page.getByTestId("view-copy").innerText()).trim();
  expect(copy).toMatch(/^Showing \d+\+? auto-approved blocks? below/);
  const n = Number(/Showing (\d+)/.exec(copy)![1]);
  expect(n).toBeGreaterThanOrEqual(1);
  const view = Number(/below (\d\.\d+)/.exec(copy)![1]);
  await expect.poll(async () => (await getCursor(request)).view_threshold).toBeCloseTo(view, 2);
  const withView = await getQueue(request, `&view_threshold=${view}`);
  const idx = withView.items.findIndex((i) => i.block_id === a1.block_id);
  expect(idx).toBeGreaterThan(-1);
  await expect(page.getByTestId("queue")).toBeVisible();
  await expect(page.getByTestId("cnt-queued")).toHaveText(String(withView.counts.pending - n));
  await page.getByTestId("queue").evaluate((el, top) => (el.scrollTop = top), idx * 64);
  await expect(card(page, a1.block_id)).toBeVisible();
  expect((await getDetail(request, a1.block_id)).block.status).toBe("auto_approved");
  // back to the project threshold removes it
  await key(page, "Escape");
  let down = 0;
  while (!/Only blocks under/.test(await page.getByTestId("view-copy").innerText())) {
    await key(page, "[");
    expect(++down).toBeLessThan(12);
  }
  await expect(page.getByTestId("view-copy")).toHaveText(new RegExp(`Only blocks under the ${T.toFixed(2)}`));
  await expect(card(page, a1.block_id)).toHaveCount(0);
  await expect.poll(async () => (await getCursor(request)).view_threshold).toBeNull();
  expect((await getDetail(request, a1.block_id)).block.status).toBe("auto_approved");
});

test("VE5 reload resumes at the same block", async ({ page, request }) => {
  const Q = (await getQueue(request)).items;
  await putCursor(request, Q[0].block_id);
  await page.goto("/verify");
  await expect(card(page, Q[0].block_id)).toBeFocused();
  await key(page, "a");
  await key(page, "a");
  await expect(card(page, Q[2].block_id)).toBeFocused();
  await expect(page.getByTestId("save-state")).toHaveText("Saved");
  await expect.poll(async () => (await getCursor(request)).current_block_id).toBe(Q[2].block_id);
  const sortBefore = await page.getByLabel("Sort").inputValue();
  await page.reload();
  await expect(card(page, Q[2].block_id)).toBeFocused();
  await expect(page.getByTestId("block-id")).toHaveText(Q[2].block_id);
  expect(await page.getByLabel("Sort").inputValue()).toBe(sortBefore);
  await expect(page.getByTestId("view-copy")).toHaveText(/Only blocks under/);
});

test("VE6 click-to-jump and the keyboard variant", async ({ page, request }) => {
  const Q = (await getQueue(request)).items.filter((i) => i.type === "paragraph");
  const cur = Q[0];
  const rects = (await api(request).get<PageBlock[]>(`/api/docs/${cur.doc_id}/pages/${cur.page}/blocks`)).filter((r) => r.type !== "header" && r.type !== "footer");
  const hf = (await api(request).get<PageBlock[]>(`/api/docs/${cur.doc_id}/pages/${cur.page}/blocks`)).find((r) => r.type === "header" || r.type === "footer");
  const order = rects.map((r) => r.block_id);
  const i0 = order.indexOf(cur.block_id);
  expect(i0, "current block on its page").toBeGreaterThan(-1);
  const other = order[i0 === 0 ? 1 : 0];
  await putCursor(request, cur.block_id);
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(cur.block_id);
  await expect(page.getByTestId(`rect-${cur.block_id}`)).toHaveAttribute("data-current", "true");
  await page.getByTestId(`rect-${other}`).click();
  await expect(page.getByTestId("block-id")).toHaveText(other);
  await expect(card(page, other)).toHaveAttribute("aria-selected", "true");
  await expect.poll(async () => (await getCursor(request)).current_block_id).toBe(other);
  if (hf) await expect(page.getByTestId(`rect-${hf.block_id}`)).toBeDisabled();
  // keyboard: s, ArrowRight, Enter
  const j = order.indexOf(other);
  const next = order[Math.min(order.length - 1, j + 1)];
  await key(page, "s");
  await expect(page.getByTestId(`rect-${other}`)).toBeFocused();
  await key(page, "ArrowRight");
  await expect(page.getByTestId(`rect-${next}`)).toBeFocused();
  await key(page, "Enter");
  await expect(page.getByTestId("block-id")).toHaveText(next);
  await expect.poll(async () => (await getCursor(request)).current_block_id).toBe(next);
});

test("VE7 numeric approve sets numbers_verified", async ({ page, request }) => {
  const q = (await getQueue(request)).items.find((i) => i.has_numeric_spec && i.status === "queued");
  expect(q).toBeTruthy();
  const id = q!.block_id;
  await putCursor(request, id);
  await page.goto("/verify");
  await expect(card(page, id)).toBeFocused();
  await expect(page.getByTestId("why-rule")).toBeVisible();
  await key(page, "a");
  await expect(page.getByTestId("save-state")).toHaveText("Saved");
  await expect.poll(async () => (await getDetail(request, id)).block.status).toBe("approved");
  const d = await getDetail(request, id);
  expect(d.block.numbers_verified).toBe(true);
  expect(d.history?.[d.history.length - 1]?.numbers_verified).toBe(true);
});

async function focusVisible(page: Page): Promise<{ ok: boolean; desc: string }> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return { ok: false, desc: "body" };
    const cs = getComputedStyle(el);
    const outline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
    const ring = cs.boxShadow !== "none" && /\d/.test(cs.boxShadow);
    return { ok: outline || ring, desc: `${el.tagName.toLowerCase()}[${el.getAttribute("role") ?? ""}] ${el.getAttribute("data-testid") ?? ""} ${(el.textContent ?? "").trim().slice(0, 30)}` };
  });
}

test("VE8 accessibility and visible focus", async ({ page, request }) => {
  const Q = (await getQueue(request)).items;
  await putCursor(request, Q[0].block_id);
  await page.goto("/verify");
  await expect(card(page, Q[0].block_id)).toBeFocused();
  await expect(page.getByRole("listbox", { name: "Review queue" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Source page" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Extracted text" })).toBeVisible();
  const serious = async (): Promise<string[]> => {
    const r = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
    return r.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`);
  };
  expect(await serious()).toEqual([]);
  const bad: string[] = [];
  const tabbed = new Set<string>();
  for (let i = 0; i < 60; i++) {
    await key(page, "Tab");
    const f = await focusVisible(page);
    if (f.desc === "body") break; // tabbed out of the page
    if (!f.ok) bad.push(f.desc);
    tabbed.add(f.desc);
  }
  expect(tabbed.size, "Tab reaches several controls across the panes").toBeGreaterThan(8);
  expect(bad, `focused elements without a visible focus style: ${bad.join(" ; ")}`).toEqual([]);
  await card(page, Q[0].block_id).focus();
  await key(page, "f");
  await expect(page.getByRole("dialog", { name: "Flag block" })).toBeVisible();
  expect(await serious()).toEqual([]);
  await key(page, "Escape");
  await expect(page.getByRole("dialog", { name: "Flag block" })).toHaveCount(0);
  await expect(card(page, Q[0].block_id)).toBeFocused();
});

test("VE9 scanned document", async ({ page, request }) => {
  const Q = (await getQueue(request)).items.filter((i) => i.doc_id === "scanned" && i.type === "paragraph");
  expect(Q.length, "scanned fixture in the seeded project").toBeGreaterThanOrEqual(2);
  const a = Q[0];
  await putCursor(request, a.block_id);
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(a.block_id);
  const img = page.locator("img[alt^='Page ']");
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth > 0)).toBe(true);
  const why = page.getByRole("region", { name: "Why this needs you" });
  await expect(why).toContainText(/ocr|OCR/);
  await expect(why).toContainText(/ocr vs ocr_alt|min \d/);
  await key(page, "a");
  await expect.poll(async () => (await getDetail(request, a.block_id)).block.status).toBe("approved");
  // an edit on another scanned block works too (trailing space passes the faithfulness check)
  let b: string | null = null;
  for (const it of Q.slice(1, 30)) {
    const d = await getDetail(request, it.block_id);
    if (d.block.faithfulness?.passed !== false && it.status === "queued") {
      b = it.block_id;
      break;
    }
  }
  expect(b).not.toBeNull();
  await putCursor(request, b);
  await page.reload();
  await expect(page.getByTestId("block-id")).toHaveText(b!);
  await key(page, "e");
  await expect(page.getByLabel("Edit block text")).toBeFocused();
  await key(page, "ControlOrMeta+End");
  await page.keyboard.type(" ");
  await key(page, "ControlOrMeta+Enter");
  await expect.poll(async () => (await getDetail(request, b!)).block.status).toBe("edited");
});

test("VE10 documents still preparing", async ({ page, request }) => {
  const Q = (await getQueue(request)).items;
  await putCursor(request, Q[0].block_id);
  await page.route("**/api/verify/queue*", async (route) => {
    const resp = await route.fetch();
    const json = (await resp.json()) as QueuePage;
    json.docs = json.docs.map((d, i) => (i === 0 ? { ...d, state: "pending", waiting_for: "score" } : d));
    await route.fulfill({ response: resp, json });
  });
  await page.goto("/verify");
  await expect(page.getByTestId("doc-chip").first()).toContainText("preparing");
  await expect(page.getByTestId("queue-footer")).toContainText("still preparing");
  await expect(card(page, Q[0].block_id)).toBeFocused();
  await key(page, "ArrowDown");
  await expect(card(page, Q[1].block_id)).toBeFocused();
  await expect(page.getByTestId("block-id")).toHaveText(Q[1].block_id);
  await page.unroute("**/api/verify/queue*");
});

test("VE11 a confirmed edit contains exactly the text the server flagged (locked textarea)", async ({ page, request }) => {
  const Q = (await getQueue(request)).items.filter((i) => i.type !== "figure" && i.status === "queued");
  const target = Q[0].block_id;
  await putCursor(request, target);
  await page.goto("/verify");
  await expect(card(page, target)).toBeFocused();
  await key(page, "e");
  const ta = page.getByLabel("Edit block text");
  await expect(ta).toBeFocused();
  await key(page, "ControlOrMeta+End");
  await page.keyboard.type(" 999");
  await key(page, "ControlOrMeta+Enter");
  await expect(page.getByTestId("edit-conflict")).toBeVisible();
  await expect(ta).toHaveAttribute("readonly", "");
  const locked = await ta.inputValue();
  expect(locked).toMatch(/ 999$/);
  // text the reviewer never saw in the diff must not be typeable while the panel is open
  await ta.click({ force: true });
  await page.keyboard.type(" EXTRA 12345");
  expect(await ta.inputValue()).toBe(locked);
  await page.getByRole("button", { name: "Confirm content change" }).click();
  await expect(page.getByTestId("edit-conflict")).toHaveCount(0);
  const d = await getDetail(request, target);
  expect(d.block.status).toBe("edited");
  expect(d.block.clean_text).toBe(locked);
  expect(d.block.clean_text).not.toContain("EXTRA");
  // the edited block carries the content-change marker when it is shown again
  await page.getByTestId("queue").focus();
  await key(page, "k");
  await expect(page.getByTestId("block-id")).toHaveText(target);
  await expect(page.getByTestId("content-change-marker")).toBeVisible();
});

test("VE12 a figure attached, then the screen left while the job runs, shows in the rail on return (no reload)", async ({ page, request }) => {
  const byArticle = await articleBlocks(request);
  const figs = await api(request).get<DocFigure[]>("/api/docs/figures/figures");
  let target: { b: string; block: string; f: DocFigure } | null = null;
  for (const [b, block] of byArticle)
    for (const f of figs) {
      if ((f.attachments ?? []).some((a) => a.article_id === b)) continue;
      if (!(f.attachments ?? []).length) continue;
      target = { b, block, f };
      break;
    }
  expect(target, "an article with a queued block and a figure not attached to it").not.toBeNull();
  const { b, block, f } = target!;
  await putCursor(request, block);
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(block);
  await expect(page.getByTestId("rail-attach").first()).toBeVisible();
  await key(page, "g");
  await key(page, "Enter");
  await expect(page.getByTestId("figure-picker")).toBeVisible();
  await page.keyboard.type(f.figure_id);
  await key(page, "ArrowDown");
  await key(page, "Enter");
  await expect(page.getByTestId(`rail-item-${f.figure_id}`).first()).toBeVisible();
  // leave Verify at once: the rail unmounts while the attach job is still running
  await page.getByRole("navigation", { name: "Screens" }).getByRole("link", { name: "Scope" }).click();
  await expect(page.getByTestId("figure-rail")).toHaveCount(0);
  await waitJobsIdle(request);
  await expect
    .poll(async () => (await api(request).get<FigureRailItem[]>(`/api/articles/${b}/figures`)).find((x) => x.figure_id === f.figure_id)?.attachment?.rule)
    .toBe("human");
  await page.getByRole("navigation", { name: "Screens" }).getByRole("link", { name: "Verify" }).click();
  const item = page.getByTestId("figure-rail").getByTestId(`rail-item-${f.figure_id}`).first();
  await expect(item).toBeVisible();
  await expect(item.getByTestId("rail-rule")).toHaveText("human");
  await expect(item.getByTestId("rail-pending")).toHaveCount(0);
  // clean up: detach again so later runs start from the seeded attachments
  await item.focus();
  await key(page, "x");
  await waitJobsIdle(request);
});
