// Module 9 independent UX check (SPEC 7.2 + module 9 gate). Written by a reviewer who did not build the screen.
// Every behaviour is asserted against the server (page.request / request) as well as the DOM. The expected values
// (diff segments, chip order, geometry, latencies) are computed here from the API data, never imported from src/.
import AxeBuilder from "@axe-core/playwright";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { BlockDetail, Cursor, DiffOp, DocFigure, FigureRailItem, JobInfo, PageBlock, QueueItem, QueuePage } from "../src/api/schema";
import { api, resetSelection, waitJobsIdle } from "./helpers";

test.describe.configure({ mode: "default" });
test.setTimeout(240_000);

const SHOT = "e2e/artifacts/ux-verify";
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOT}/${name}.png` });
const rid = (): string => `ux-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const BASE = "http://127.0.0.1:5173";
const key = (page: Page, k: string) => page.keyboard.press(k);
const card = (page: Page, id: string) => page.getByTestId(`card-${id}`);

const getQueue = (request: APIRequestContext, query = ""): Promise<QueuePage> => api(request).get<QueuePage>(`/api/verify/queue?limit=2000${query}`);
const getDetail = (request: APIRequestContext, id: string): Promise<BlockDetail> => api(request).get<BlockDetail>(`/api/verify/blocks/${id}`);
const getCursor = (request: APIRequestContext): Promise<Cursor> => api(request).get<Cursor>("/api/verify/cursor");
async function putCursor(request: APIRequestContext, current: string | null, extra: Partial<Cursor> = {}): Promise<void> {
  await api(request).put("/api/verify/cursor", { sort: "worst_first", view_threshold: null, doc_filter: null, current_block_id: current, request_id: rid(), ...extra });
}
interface Row { id: number; kind: string; screen: string; target_id: string | null }
async function rows(request: APIRequestContext): Promise<Row[]> {
  const t = await (await request.get("/api/decisions/export")).text();
  return t.split("\n").filter(Boolean).map((l) => JSON.parse(l) as Row);
}
const maxRow = async (request: APIRequestContext): Promise<number> => Math.max(0, ...(await rows(request)).map((r) => r.id));
interface FlagRow { id: string; target_id: string; category: string; note: string | null; status: string }
const getFlags = (request: APIRequestContext): Promise<FlagRow[]> => api(request).get<FlagRow[]>("/api/flags");

/** First queued item (in API order) whose detail satisfies the predicate. */
async function findQueued(request: APIRequestContext, pred: (d: BlockDetail, i: QueueItem) => boolean, opts: { query?: string; scan?: number; skip?: Set<string> } = {}): Promise<{ item: QueueItem; detail: BlockDetail }> {
  const q = (await getQueue(request, opts.query ?? "")).items;
  for (const it of q.slice(0, opts.scan ?? 250)) {
    if (opts.skip?.has(it.block_id)) continue;
    const d = await getDetail(request, it.block_id);
    if (pred(d, it)) return { item: it, detail: d };
  }
  throw new Error("no queued block matched the predicate");
}
const editable = (d: BlockDetail): boolean => d.block.type !== "figure" && d.block.faithfulness?.passed !== false && d.block.clean_text != null;
const last = <T,>(a: T[] | undefined): T | undefined => (a && a.length ? a[a.length - 1] : undefined);
const sig = (d: BlockDetail, name: string) => d.block.signals?.find((s) => s.name === name);

// ---------------------------------------------------------------------------------------------------------------
// focus helpers
interface FocusInfo { inQueue: boolean; ring: boolean; desc: string; ringDesc: string; body: boolean }
async function focusInfo(page: Page): Promise<FocusInfo> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return { inQueue: false, ring: false, desc: "body", ringDesc: "", body: true };
    const cs = getComputedStyle(el);
    const ow = parseFloat(cs.outlineWidth) || 0;
    const outline = cs.outlineStyle !== "none" && ow >= 2 && !/, 0\)$/.test(cs.outlineColor);
    let spread = 0;
    const re = /(rgba?\([^)]*\)|#[0-9a-f]+)\s+(-?[\d.]+)px\s+(-?[\d.]+)px\s+(-?[\d.]+)px\s+(-?[\d.]+)px/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(cs.boxShadow))) if (!/, 0\)$/.test(m[1])) spread = Math.max(spread, parseFloat(m[5]));
    return {
      inQueue: !!el.closest('[data-zone="queue"]'),
      ring: outline || spread >= 2,
      desc: `${el.tagName.toLowerCase()}[${el.getAttribute("role") ?? ""}] ${el.getAttribute("data-testid") ?? el.getAttribute("aria-label") ?? ""} ${(el.textContent ?? "").trim().slice(0, 24)}`,
      ringDesc: `outline=${cs.outlineStyle} ${ow}px shadow=${cs.boxShadow.slice(0, 90)}`,
      body: false,
    };
  });
}

/** Timing probe: keydown, focus and POST /api/verify/actions timestamps, all from performance.now() in the page. */
async function installProbe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as { __p: { keys: number[]; focus: { t: number; id: string }[]; posts: { t0: number; t1: number }[]; mouse: number } };
    w.__p = { keys: [], focus: [], posts: [], mouse: 0 };
    addEventListener("keydown", () => w.__p.keys.push(performance.now()), true);
    // real pointer input only: a keyboard-activated button also dispatches a synthetic click with detail 0
    for (const t of ["mousedown", "mouseup", "pointerdown", "pointerup"]) addEventListener(t, () => (w.__p.mouse += 1), true);
    addEventListener("click", (e) => { if ((e as MouseEvent).detail > 0) w.__p.mouse += 1; }, true);
    addEventListener("focusin", (e) => { const id = (e.target as HTMLElement | null)?.dataset?.testid; if (id) w.__p.focus.push({ t: performance.now(), id }); }, true);
    const of = window.fetch.bind(window);
    window.fetch = async (...a: Parameters<typeof fetch>) => {
      const inp = a[0];
      const url = typeof inp === "string" ? inp : inp instanceof Request ? inp.url : String(inp);
      const method = (a[1]?.method ?? (inp instanceof Request ? inp.method : "GET")).toUpperCase();
      const act = method === "POST" && /\/api\/verify\/actions/.test(url);
      const t0 = performance.now();
      try { return await of(...a); } finally { if (act) w.__p.posts.push({ t0, t1: performance.now() }); }
    };
  });
}
interface Probe { keys: number[]; focus: { t: number; id: string }[]; posts: { t0: number; t1: number }[]; mouse: number }
const readProbe = (page: Page): Promise<Probe> => page.evaluate(() => (window as unknown as { __p: Probe }).__p);
const stats = (xs: number[]): { n: number; mean: number; p95: number; max: number } => {
  const s = [...xs].sort((a, b) => a - b);
  return { n: s.length, mean: Math.round(s.reduce((a, b) => a + b, 0) / Math.max(1, s.length)), p95: Math.round(s[Math.min(s.length - 1, Math.floor(s.length * 0.95))] ?? 0), max: Math.round(s[s.length - 1] ?? 0) };
};

// ---------------------------------------------------------------------------------------------------------------
// server-side project dir (for the two tests that must change files on disk: stale approval, unscored doc)
function projectDir(): string {
  const ps = execSync("ps -axo command=").toString().split("\n");
  for (const l of ps) {
    const m = /labor serve (\S+) .*--port 8765(\s|$)/.exec(l);
    if (m) return m[1];
  }
  throw new Error("cannot locate the project dir of the :8765 server");
}

// ---------------------------------------------------------------------------------------------------------------
// expected chips / diff segments, derived from the SPEC/design rules (not from src/)
const LABEL: Record<string, string> = {
  parser_agreement: "parsers disagree", textlayer_vs_ocr: "text layer ≠ OCR", ocr_min: "weak OCR word", ocr_mean: "low OCR",
  reading_order_risk: "reading order", table_consistency: "table shape", garbage_ratio: "garbled text", faithfulness: "cleanup changed content",
  figure_method: "figure crop", figure_resolution: "low-res figure", figure_attach_rule: "weak figure match", llm_verifier: "verifier disagrees", has_numeric_spec: "numeric spec",
};
interface Seg { kind: "equal" | "ins" | "del" | "move"; ok: boolean; text: string; display: string; numeric: string[]; opIndex: number }
const vis = (s: string): string => s.replace(/ /g, "␣").replace(/\n/g, "↵").replace(/\t/g, "→").replace(/ /g, "⍽");
function expectedSegs(ops: DiffOp[]): Seg[] {
  const out: Seg[] = [];
  ops.forEach((o, i) => {
    const push = (kind: Seg["kind"], text: string): void => {
      if (!text) return;
      out.push({ kind, ok: o.allowed, text, display: kind === "equal" ? text : vis(text), numeric: text.match(/\d+(?:[.,]\d+)*/g) ?? [], opIndex: i });
    };
    if (o.op === "equal") push("equal", o.clean);
    else if (o.op === "delete") push("del", o.raw);
    else if (o.op === "insert") push("ins", o.clean);
    else if (o.op === "replace") { push("del", o.raw); push("ins", o.clean); }
    else push("move", o.clean || o.raw);
  });
  return out;
}
const segName = (s: Seg): string => (s.kind === "equal" ? "equal" : `${s.kind}-${s.ok ? "ok" : "bad"}`);
/** Source of the diff per the design: edited -> latest human_edit_diff; else faithfulness.diff. */
function diffSource(d: BlockDetail): DiffOp[] | null {
  if (d.block.status === "edited") {
    const h = [...(d.history ?? [])].reverse().find((x) => x.human_edit_diff);
    if (h?.human_edit_diff) return h.human_edit_diff;
  }
  return d.block.faithfulness?.diff ?? null;
}

// ---------------------------------------------------------------------------------------------------------------
test.beforeAll(async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  await resetSelection(ctx);
  const r = await ctx.post("/api/scope/confirm", { data: {} });
  expect(r.ok(), await r.text()).toBeTruthy();
  await waitJobsIdle(ctx);
  const q = await getQueue(ctx);
  expect(q.total, "queue large enough for a 20-block run plus other tests").toBeGreaterThanOrEqual(120);
  await ctx.dispose();
});
test.beforeEach(async ({ request }) => {
  await waitJobsIdle(request);
  await putCursor(request, null);
});

// ===============================================================================================================
test("T1 status strip counts equal the API; sort control reorders the queue", async ({ page, request }) => {
  const q = await getQueue(request);
  await page.goto("/verify");
  await expect(page.getByTestId("cnt-queued")).toHaveText(String(q.counts.pending));
  await expect(page.getByTestId("cnt-auto")).toHaveText(String(q.counts.auto_approved));
  await expect(page.getByTestId("cnt-flagged")).toHaveText(String(q.counts.flagged_open));
  expect(q.counts.pending).toBe(q.total);
  expect(q.counts.pending, "queued count is a real number > 0").toBeGreaterThan(0);
  await shot(page, "01-status-strip");

  // API order sanity, computed independently
  const worst = (await getQueue(request, "&sort=worst_first")).items;
  const conf = worst.map((i) => i.confidence ?? 2);
  expect(conf, "worst-first = confidence ascending").toEqual([...conf].sort((a, b) => a - b));
  const byPage = (await getQueue(request, "&sort=by_page")).items;
  for (let i = 1; i < byPage.length; i++)
    if (byPage[i].doc_id === byPage[i - 1].doc_id) expect(byPage[i].page, `by_page order at ${i}`).toBeGreaterThanOrEqual(byPage[i - 1].page);
  const figs = (await getQueue(request, "&sort=figures_only")).items;
  expect(figs.length).toBeGreaterThan(0);
  expect(figs.every((i) => i.type === "figure")).toBe(true);
  expect(worst[0].block_id, "sorts differ so the check is meaningful").not.toBe(byPage[0].block_id);

  const firstCards = async (n: number): Promise<string[]> =>
    page.locator('[data-testid^="card-"]:not([data-pinned="true"])').evaluateAll((els, k) => els.map((e) => ({ t: e.getBoundingClientRect().top, id: (e as HTMLElement).dataset.testid!.slice(5) })).sort((a, b) => a.t - b.t).slice(0, k).map((x) => x.id), n);
  for (const sort of ["by_page", "figures_only", "worst_first"] as const) {
    await page.getByLabel("Sort").selectOption(sort);
    const expected = (await getQueue(request, `&sort=${sort}`)).items;
    const n = Math.min(6, expected.length);
    await expect.poll(async () => (await firstCards(n)).join(","), { timeout: 10_000, message: `first ${n} cards for sort=${sort}` }).toBe(expected.slice(0, n).map((i) => i.block_id).join(","));
    await expect.poll(async () => (await getCursor(request)).sort).toBe(sort);
    if (sort === "figures_only") await expect(page.locator('[data-testid^="card-"]:not([data-pinned="true"])')).toHaveCount(expected.length);
    await shot(page, `01-sort-${sort}`);
  }
});

// ===============================================================================================================
test("T2 threshold slider only adds a view; no status changes on the server", async ({ page, request }) => {
  const T = (await api(request).get<{ config: { threshold: number } }>("/api/project")).config.threshold;
  const all = await getQueue(request, "&view_threshold=1");
  const statusMap = new Map(all.items.map((i) => [i.block_id, i.status]));
  const autos = all.items.filter((i) => i.status === "auto_approved");
  expect(autos.length).toBeGreaterThan(5);
  const before = (await getQueue(request)).counts;
  await page.goto("/verify");
  const slider = page.getByLabel("Also review auto-approved blocks below");
  expect(Number(await slider.getAttribute("min"))).toBeCloseTo(T, 2);
  expect(Number(await slider.getAttribute("max"))).toBe(1);
  await expect(page.getByTestId("view-copy")).toHaveText(new RegExp(`^Only blocks under the ${T.toFixed(2)} threshold$`));

  const X = Math.min(1, +(T + 0.1).toFixed(2));
  await slider.fill(String(X));
  const expectedN = autos.filter((i) => (i.confidence ?? 1) < X).length;
  expect(expectedN, "choose X so that something is added").toBeGreaterThan(0);
  await expect(page.getByTestId("view-copy")).toHaveText(new RegExp(`^Showing ${expectedN} auto-approved blocks? below ${X.toFixed(2)}$`));
  await expect.poll(async () => (await getCursor(request)).view_threshold).toBeCloseTo(X, 2);
  await shot(page, "02-slider-view");
  const view = await getQueue(request, `&view_threshold=${X}`);
  expect(view.items.filter((i) => i.status === "auto_approved").length).toBe(expectedN);
  await expect(page.getByTestId("cnt-queued")).toHaveText(String(view.counts.pending - expectedN));
  await expect(page.getByTestId("cnt-auto")).toHaveText(String(before.auto_approved));

  // One of the added blocks is reachable as a card (scroll the virtual list to it)
  const added = view.items.findIndex((i) => i.status === "auto_approved");
  await page.getByTestId("queue").evaluate((el, top) => (el.scrollTop = top), Math.max(0, added * 64 - 100));
  await expect(card(page, view.items[added].block_id)).toBeVisible();

  // NO status changed: all blocks re-read, and 5 sampled blocks via the detail endpoint
  const after = await getQueue(request, "&view_threshold=1");
  for (const i of after.items) expect(i.status, i.block_id).toBe(statusMap.get(i.block_id));
  expect(after.counts.auto_approved).toBe(before.auto_approved);
  for (const a of autos.slice(0, 5)) expect((await getDetail(request, a.block_id)).block.status).toBe("auto_approved");

  await slider.fill(String(T));
  await expect(page.getByTestId("view-copy")).toHaveText(/^Only blocks under the/);
  await expect.poll(async () => (await getCursor(request)).view_threshold).toBeNull();
  for (const a of autos.slice(0, 5)) expect((await getDetail(request, a.block_id)).block.status).toBe("auto_approved");
});

// ===============================================================================================================
test("T3 queue card content and chip order", async ({ page, request }) => {
  const q = (await getQueue(request)).items;
  const all = await getQueue(request, "&view_threshold=1");
  const numericAuto = all.items.filter((i) => i.has_numeric_spec && i.status === "auto_approved");
  expect(numericAuto, "numeric blocks are never auto-approved (rule, not score)").toEqual([]);
  expect(q.some((i) => i.has_numeric_spec && (i.confidence ?? 0) >= 0.85), "a high-confidence numeric block is still queued").toBe(true);
  await putCursor(request, q[0].block_id);
  await page.goto("/verify");
  await expect(card(page, q[0].block_id)).toBeFocused();
  // check the first 8 cards + the first non-numeric card + a high-confidence numeric card
  const sample = [...q.slice(0, 8)];
  const nonNum = q.find((i) => !i.has_numeric_spec);
  if (nonNum && !sample.includes(nonNum)) sample.push(nonNum);
  let checkedNumeric = 0;
  for (const it of sample) {
    const d = await getDetail(request, it.block_id);
    const idx = q.findIndex((x) => x.block_id === it.block_id);
    await page.getByTestId("queue").evaluate((el, top) => (el.scrollTop = top), Math.max(0, idx * 64 - 64));
    const c = card(page, it.block_id);
    await expect(c).toBeVisible();
    const txt = await c.innerText();
    expect(txt).toContain(it.block_id);
    expect(txt).toContain(`p.${it.page}`);
    expect(txt).toContain(it.type);
    expect(txt).toContain(it.confidence == null ? "n/a" : it.confidence.toFixed(2));
    const chips = await c.locator("span.rounded").allInnerTexts();
    const failing = (d.why ?? []).filter((w) => w.kind === "signal" && (w.value ?? 0) < 1 && w.name !== "has_numeric_spec");
    const crit = failing.filter((w) => w.critical).sort((a, b) => (a.value ?? 0) - (b.value ?? 0)).map((w) => LABEL[w.name]);
    const soft = failing.filter((w) => !w.critical).map((w) => LABEL[w.name]);
    const iNum = chips.indexOf("numeric spec");
    if (it.has_numeric_spec) { checkedNumeric++; expect(iNum, `numeric rule chip on ${it.block_id}: ${chips.join("|")}`).toBeGreaterThan(-1); }
    else expect(iNum).toBe(-1);
    const critIdx = chips.map((t, i) => (crit.includes(t) ? i : -1)).filter((i) => i >= 0);
    const softIdx = chips.map((t, i) => (soft.includes(t) ? i : -1)).filter((i) => i >= 0);
    const slots = it.has_numeric_spec ? 2 : 3;
    expect.soft(critIdx.length, `critical chips shown on ${it.block_id} (${chips.join("|")})`).toBe(Math.min(slots, crit.length > 0 ? crit.length : 0));
    // chips are ordered: critical failures, then the numeric rule, then soft ones
    const order = [...critIdx, ...(iNum >= 0 ? [iNum] : []), ...softIdx];
    expect.soft(order, `chip order on ${it.block_id}: ${chips.join("|")}`).toEqual([...order].sort((a, b) => a - b));
    // critical chips keep the API order (value ascending)
    expect.soft(critIdx.map((i) => chips[i]), `critical chip order on ${it.block_id}`).toEqual(crit.slice(0, critIdx.length));
  }
  expect(checkedNumeric).toBeGreaterThan(0);
  await shot(page, "03-queue-cards");
});

// ===============================================================================================================
test("T4 source pane: outline geometry, disagreement highlights, click to jump", async ({ page, request }) => {
  // a) born-digital block: overlay rect == bbox/page size within 2%, and page image has ink under the bbox
  const born = await findQueued(request, (d) => d.block.doc_id === "clean" && d.block.type === "paragraph" && !!d.block.bbox);
  const d = born.detail;
  await putCursor(request, d.block.id);
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(d.block.id);
  const img = page.locator("img[alt^='Page ']");
  await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth > 0)).toBe(true);
  const rect = page.getByTestId(`rect-${d.block.id}`);
  await expect(rect).toHaveAttribute("data-current", "true");
  const geo = await page.evaluate(({ id }) => {
    const im = document.querySelector("img[alt^='Page ']") as HTMLImageElement;
    const r = document.querySelector(`[data-testid="rect-${id}"]`) as HTMLElement;
    const a = im.getBoundingClientRect(), b = r.getBoundingClientRect();
    return { iw: a.width, ih: a.height, x: b.left - a.left, y: b.top - a.top, w: b.width, h: b.height, nw: im.naturalWidth, nh: im.naturalHeight, border: getComputedStyle(r).borderTopWidth };
  }, { id: d.block.id });
  const [x0, y0, x1, y1] = d.block.bbox!;
  const P = d.page;
  const tol = 0.02;
  expect(Math.abs(geo.x / geo.iw - x0 / P.width), "left").toBeLessThan(tol);
  expect(Math.abs(geo.y / geo.ih - y0 / P.height), "top").toBeLessThan(tol);
  expect(Math.abs(geo.w / geo.iw - (x1 - x0) / P.width), "width").toBeLessThan(tol);
  expect(Math.abs(geo.h / geo.ih - (y1 - y0) / P.height), "height").toBeLessThan(tol);
  expect(Math.abs(geo.nw / geo.nh - P.width / P.height), "page image aspect equals PageRef aspect").toBeLessThan(0.01);
  expect(parseFloat(geo.border), "current block is outlined (2px)").toBeGreaterThanOrEqual(2);
  const ink = await page.evaluate(({ bb, pw, ph }) => {
    const im = document.querySelector("img[alt^='Page ']") as HTMLImageElement;
    const c = document.createElement("canvas");
    c.width = im.naturalWidth; c.height = im.naturalHeight;
    const g = c.getContext("2d")!; g.drawImage(im, 0, 0);
    const sx = im.naturalWidth / pw, sy = im.naturalHeight / ph;
    const frac = (x0: number, y0: number, x1: number, y1: number): number => {
      const w = Math.max(1, Math.round((x1 - x0) * sx)), h = Math.max(1, Math.round((y1 - y0) * sy));
      const px = g.getImageData(Math.round(x0 * sx), Math.round(y0 * sy), w, h).data;
      let dark = 0;
      for (let i = 0; i < px.length; i += 4) if (px[i] + px[i + 1] + px[i + 2] < 384) dark++;
      return dark / (px.length / 4);
    };
    return { inside: frac(bb[0], bb[1], bb[2], bb[3]) };
  }, { bb: d.block.bbox!, pw: P.width, ph: P.height });
  expect(ink.inside, "the page image has ink where the outline sits").toBeGreaterThan(0.005);
  await shot(page, "04-source-outline");

  // b) disagreement: signal parser_agreement < 1 -> highlights; == 1 -> none
  const dis = await findQueued(request, (x) => (sig(x, "parser_agreement")?.value ?? 1) < 1 && !!x.block.ocr_words?.length && !!x.block.bbox && x.block.doc_id === "scanned");
  await putCursor(request, dis.detail.block.id);
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(dis.detail.block.id);
  expect(new Set(Object.values(dis.detail.block.raw_text_by_parser ?? {})).size, "parsers' raw text really differs").toBeGreaterThan(1);
  const words = page.getByTestId("disagree-word");
  await expect.poll(() => words.count(), { message: "disagreeing tokens are highlighted on the page" }).toBeGreaterThan(0);
  const inside = await page.evaluate((id) => {
    const r = (document.querySelector(`[data-testid="rect-${id}"]`) as HTMLElement).getBoundingClientRect();
    return Array.from(document.querySelectorAll('[data-testid="disagree-word"]')).map((e) => { const b = e.getBoundingClientRect(); return b.left >= r.left - 3 && b.right <= r.right + 3 && b.top >= r.top - 3 && b.bottom <= r.bottom + 3; });
  }, dis.detail.block.id);
  expect(inside.every(Boolean), "every highlighted word lies inside the block outline").toBe(true);
  await expect(page.getByTestId("parser-compare")).toBeVisible();
  await shot(page, "04-source-disagree");
  const agree = await findQueued(request, (x) => (sig(x, "parser_agreement")?.value ?? 0) === 1 && (sig(x, "textlayer_vs_ocr")?.value ?? 1) === 1 && !!x.block.bbox && x.block.type === "paragraph");
  await putCursor(request, agree.detail.block.id);
  await page.reload();
  await expect(page.getByTestId("block-id")).toHaveText(agree.detail.block.id);
  await expect(page.getByTestId(`rect-${agree.detail.block.id}`)).toHaveAttribute("data-current", "true");
  await expect(page.getByTestId("disagree-word")).toHaveCount(0);
  await expect(page.getByTestId("disagree-block")).toHaveCount(0);
  await expect(page.getByTestId("parser-compare")).toHaveCount(0);

  // c) click another block's overlay: the queue jumps to it
  const rects = (await api(request).get<PageBlock[]>(`/api/docs/${d.block.doc_id}/pages/${d.block.page}/blocks`)).filter((r) => r.type !== "header" && r.type !== "footer" && r.block_id !== d.block.id);
  expect(rects.length).toBeGreaterThan(1);
  const other = rects[0].block_id;
  await putCursor(request, d.block.id);
  await page.reload();
  await expect(page.getByTestId("block-id")).toHaveText(d.block.id);
  await page.getByTestId(`rect-${other}`).click();
  await expect(page.getByTestId("block-id")).toHaveText(other);
  await expect(card(page, other)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId(`rect-${other}`)).toHaveAttribute("data-current", "true");
  await expect(page.getByTestId(`rect-${d.block.id}`)).not.toHaveAttribute("data-current", "true");
  await expect.poll(async () => (await getCursor(request)).current_block_id).toBe(other);
  await shot(page, "04-source-click-jump");
});

// ===============================================================================================================
test("T5 extracted pane: Text/Diff toggle with t, exact diff segments, why list", async ({ page, request }) => {
  // a) a queued block with replace ops
  const a = await findQueued(request, (d) => d.block.type !== "figure" && (d.block.faithfulness?.diff ?? []).some((o) => o.op === "replace" || o.op === "delete") && d.block.clean_text != null);
  // b) an edited block that adds / changes numbers (violation ops), made through the API so it has a human_edit_diff
  const n = await findQueued(request, (d) => editable(d) && d.block.has_numeric_spec && /\d/.test(d.block.clean_text ?? ""), { skip: new Set([a.item.block_id]) });
  const txt = n.detail.block.clean_text!;
  const changed = txt.replace(/\d/, (m) => String((Number(m) + 1) % 10));
  const r = await request.post("/api/verify/actions", { data: { kind: "edit", block_id: n.item.block_id, text: changed, confirm_content_change: true, request_id: rid() } });
  expect(r.ok(), await r.text()).toBeTruthy();
  const edited = await getDetail(request, n.item.block_id);
  expect(edited.block.status).toBe("edited");
  const src = diffSource(edited)!;
  expect(src.some((o) => !o.allowed), "edit vs raw has a content-changing op").toBe(true);

  for (const [label, d] of [["queued", a.detail], ["edited", edited]] as const) {
    const ops = diffSource(d)!;
    // invariants on the API data
    expect(ops.map((o) => o.raw).join("")).toBe(d.block.raw_text);
    await putCursor(request, d.block.id);
    await page.goto("/verify");
    await expect(page.getByTestId("block-id")).toHaveText(d.block.id);
    await expect(page.getByTestId("view-text")).toHaveAttribute("aria-pressed", "true");
    // numbers emphasised in Text view
    const shown = d.block.clean_text ?? d.block.raw_text;
    const marks = await page.getByTestId("block-text").locator("mark.num").allInnerTexts();
    expect(marks, `${label}: numeric emphasis in Text view`).toEqual(shown.match(/\d+(?:[.,]\d+)*/g) ?? []);
    await key(page, "t");
    await expect(page.getByTestId("view-diff")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("view-text")).toHaveAttribute("aria-pressed", "false");
    const segs = expectedSegs(ops);
    const dom = await page.locator("[data-testid=diff-view] [data-op-index]").evaluateAll((els) =>
      els.map((e) => {
        const cs = getComputedStyle(e);
        return { tag: e.tagName, op: Number((e as HTMLElement).dataset.opIndex), seg: (e as HTMLElement).dataset.seg ?? "", text: e.textContent ?? "", title: e.getAttribute("title"), aria: e.getAttribute("aria-label"), deco: cs.textDecorationLine, weight: Number(cs.fontWeight), color: cs.color, marks: Array.from(e.querySelectorAll("mark.num")).map((m) => m.textContent ?? "") };
      }),
    );
    expect(dom.length, `${label}: segment count`).toBe(segs.length);
    segs.forEach((s, i) => {
      const e = dom[i];
      const nm = segName(s);
      expect(e.op, `${label} seg ${i} op index`).toBe(s.opIndex);
      expect(e.seg, `${label} seg ${i} class`).toBe(nm);
      expect(e.text, `${label} seg ${i} text`).toBe(s.display);
      expect(e.tag, `${label} seg ${i} element`).toBe(s.kind === "del" ? "DEL" : s.kind === "ins" ? "INS" : "SPAN");
      expect(e.marks, `${label} seg ${i} numeric emphasis`).toEqual(s.numeric);
      const [rr, gg, bb] = e.color.match(/\d+/g)!.map(Number);
      if (s.kind === "del") expect(e.deco).toContain("line-through");
      if (s.kind === "ins") expect(e.deco).toContain("underline");
      if (s.kind === "equal") expect(e.deco).toBe("none");
      if ((s.kind === "del" || s.kind === "ins") && !s.ok) {
        expect(e.weight, `${label} seg ${i} violation is bold`).toBeGreaterThanOrEqual(700);
        expect(rr - Math.max(gg, bb), `${label} seg ${i} violation is red (${e.color})`).toBeGreaterThan(80);
        expect(e.title).toBe(s.kind === "del" ? "removed" : "added");
      }
      if ((s.kind === "del" || s.kind === "ins") && s.ok) expect(Math.max(rr, gg, bb) - Math.min(rr, gg, bb), `${label} seg ${i} allowed op is grey`).toBeLessThan(40);
      if (s.kind === "move") expect(e.title).toBe("moved (reading order)");
      if (s.kind === "del" || s.kind === "ins")
        expect.soft(e.aria ?? "", `${label} seg ${i}: del/ins carry a removed:/added: aria-label (design 4; "deleted"/"inserted" wording accepted)`).toMatch(s.kind === "del" ? /^(removed|deleted): / : /^(added|inserted): /);
    });
    await expect(page.getByTestId("diff-legend")).toBeVisible();
    await shot(page, `05-diff-${label}`);
    await key(page, "t");
    await expect(page.getByTestId("view-text")).toHaveAttribute("aria-pressed", "true");

    // Why this needs you: every signal, in API order, with its detail verbatim
    const signals = (d.why ?? []).filter((w) => w.kind === "signal");
    const items = page.getByLabel("Why this needs you, signals").getByRole("listitem");
    await expect(items).toHaveCount(signals.length);
    for (let i = 0; i < signals.length; i++) {
      const w = signals[i];
      const t = await items.nth(i).innerText();
      if (w.name === "has_numeric_spec") expect(t).toContain("Rule: always reviewed");
      else {
        expect(t, `${w.name} label`).toContain(LABEL[w.name]);
        expect(t, `${w.name} value`).toContain(w.value == null ? "n/a" : w.value.toFixed(2));
        expect(t.includes("critical"), `${w.name} critical badge`).toBe(w.critical);
      }
      if (w.detail) expect(t.replace(/\s+/g, " "), `${w.name} detail verbatim`).toContain(w.detail.replace(/\s+/g, " "));
    }
    // criticals come first (design: server order critical first)
    const flags = signals.map((w) => w.critical);
    expect(flags.join(), "critical signals listed first").toBe([...flags].sort((x, y) => Number(y) - Number(x)).join());
  }
});

// ===============================================================================================================
test("T6 twenty blocks, keyboard only, own sequence", async ({ page, request }) => {
  await installProbe(page);
  const Q = (await getQueue(request)).items;
  type Role = "A" | "E_OK" | "E_409" | "F2" | "F3" | "F4" | "SKIP" | "A_K";
  const roles: Role[] = ["A", "A", "F2", "A", "A", "E_OK", "A", "A", "SKIP", "A", "E_409", "A", "F3", "A", "A_K", "E_OK", "A", "F4", "A", "A"];
  const details = await Promise.all(Q.slice(0, 24).map((i) => getDetail(request, i.block_id)));
  const ok = (r: Role, d: BlockDetail): boolean => (r === "E_OK" ? editable(d) : r === "E_409" ? d.block.type !== "figure" && d.block.clean_text != null : r.startsWith("F") ? d.block.type !== "figure" : true);
  for (let i = 0; i < 20; i++) {
    if (ok(roles[i], details[i])) continue;
    const j = roles.findIndex((r, k) => k > i && r === "A" && ok(roles[i], details[k]));
    expect(j, `swap partner for slot ${i}`).toBeGreaterThan(-1);
    [roles[i], roles[j]] = [roles[j], roles[i]];
  }
  console.log("T6 plan", roles.map((r, i) => `${i}:${r}:${Q[i].block_id}`).join(" "));
  await putCursor(request, Q[0].block_id);
  const before = (await getQueue(request)).counts;
  const maxId = await maxRow(request);
  const flagsBefore = (await getFlags(request)).length;
  await page.goto("/verify");
  await expect(card(page, Q[0].block_id)).toBeFocused();

  const steps: string[] = [];
  const check = async (what: string, nextId: string): Promise<void> => {
    await expect(card(page, nextId), what).toBeFocused();
    await expect(page.getByTestId("block-id"), what).toHaveText(nextId);
    const f = await focusInfo(page);
    steps.push(`${what}: ${f.desc} ring=${f.ring}`);
    expect(f.inQueue, `${what}: activeElement inside the queue (${f.desc})`).toBe(true);
    expect(f.ring, `${what}: visible focus ring (${f.ringDesc})`).toBe(true);
  };
  const ringNow = async (what: string): Promise<void> => {
    const f = await focusInfo(page);
    expect(f.body, `${what}: focus is not lost to body`).toBe(false);
    expect(f.ring, `${what}: focus ring on ${f.desc} (${f.ringDesc})`).toBe(true);
  };
  await ringNow("initial");
  const append = async (suffix: string, conflict: boolean, what: string): Promise<void> => {
    await key(page, "e");
    await expect(page.getByLabel("Edit block text")).toBeFocused();
    await ringNow(`${what} textarea`);
    await key(page, "ControlOrMeta+End");
    await page.keyboard.type(suffix);
    await key(page, "ControlOrMeta+Enter");
    if (conflict) {
      await expect(page.getByTestId("edit-conflict")).toBeVisible();
      await expect(page.getByTestId("numeric-changes")).toBeVisible();
      await expect(page.getByRole("button", { name: "Confirm content change" })).toBeFocused();
      await ringNow(`${what} confirm button`);
      await shot(page, "06-edit-conflict");
      await key(page, "Enter");
    }
  };
  const flag = async (digit: string, note: string | null, what: string): Promise<void> => {
    await key(page, "f");
    await expect(page.getByRole("dialog", { name: "Flag block" })).toBeVisible();
    await expect(page.getByRole("radiogroup")).toBeFocused();
    await ringNow(`${what} radiogroup`);
    await key(page, digit);
    if (note) { await key(page, "Tab"); await expect(page.getByLabel("Note (optional)")).toBeFocused(); await page.keyboard.type(note); await key(page, "ControlOrMeta+Enter"); }
    else await key(page, "Enter");
  };
  for (let i = 0; i < 20; i++) {
    const what = `#${i} ${roles[i]} ${Q[i].block_id}`;
    switch (roles[i]) {
      case "A": await key(page, "a"); break;
      case "E_OK": await append(" ", false, what); break;
      case "E_409": await append(" 999", true, what); break;
      case "F2": await flag("2", "figure missing near step 3", what); break;
      case "F3": await flag("3", null, what); break;
      case "F4": await flag("4", "box clipped", what); break;
      case "SKIP": await key(page, "j"); break;
      case "A_K":
        await key(page, "a");
        await check(`${what} approve`, Q[i + 1].block_id);
        await key(page, "k");
        await check(`${what} back`, Q[i].block_id);
        await expect(card(page, Q[i].block_id)).toHaveAttribute("data-pinned", "true");
        await key(page, "a");
        break;
    }
    await check(what, Q[i + 1].block_id);
  }
  await expect(page.getByTestId("save-state")).toHaveText("Saved");
  const p = await readProbe(page);
  expect(p.mouse, "no pointer events were produced").toBe(0);
  await shot(page, "06-after-20");

  // server side
  const rs = (await rows(request)).filter((r) => r.id > maxId && r.screen === "verify");
  const count = (k: string): number => rs.filter((r) => r.kind === k).length;
  console.log("T6 steps", steps.length, "rows", JSON.stringify({ approve: count("approve"), edit: count("edit"), flag: count("flag"), skip: count("skip"), back: count("back") }));
  expect({ approve: count("approve"), edit: count("edit"), flag: count("flag"), skip: count("skip"), back: count("back") }).toEqual({ approve: 14, edit: 3, flag: 3, skip: 1, back: 1 });
  const flagsAfter = await getFlags(request);
  expect(flagsAfter.length - flagsBefore).toBe(3);
  for (let i = 0; i < 20; i++) {
    const id = Q[i].block_id;
    const d = await getDetail(request, id);
    const mine = rs.filter((r) => r.target_id === id).map((r) => r.kind);
    switch (roles[i]) {
      case "A": expect(d.block.status, id).toBe("approved"); expect(mine).toEqual(["approve"]); break;
      case "A_K": expect(d.block.status).toBe("approved"); expect(mine.filter((k) => k === "approve"), "approved twice (re-approve after back)").toEqual(["approve", "approve"]); break;
      case "E_OK": expect(d.block.status).toBe("edited"); expect(last(d.history)?.faith_passed).toBe(true); break;
      case "E_409": expect(d.block.status).toBe("edited"); expect(last(d.history)?.faith_passed).toBe(false); expect(d.block.clean_text ?? d.block.raw_text).toContain("999"); break;
      case "SKIP": expect(d.block.status).toBe("queued"); expect(mine).toEqual(["skip"]); break;
      case "F2": case "F3": case "F4": {
        const cat = ({ F2: "missing_figure", F3: "wrong_grouping", F4: "bad_crop" } as Record<string, string>)[roles[i]];
        const f = flagsAfter.find((x) => x.target_id === id || (d.block.figure_id && x.target_id === d.block.figure_id));
        expect(f?.category, `flag on ${id}`).toBe(cat);
        expect(f?.status).toBe("open");
        expect(f?.note ?? null).toBe(({ F2: "figure missing near step 3", F3: null, F4: "box clipped" } as Record<string, string | null>)[roles[i]]);
        expect(d.block.status).toBe("flagged");
      }
    }
  }
  const after = (await getQueue(request)).counts;
  expect({ pending: before.pending - after.pending, approved: after.approved - before.approved, edited: after.edited - before.edited, flagged: after.flagged_open - before.flagged_open, skipped: after.skipped - before.skipped }).toEqual({ pending: 19, approved: 13, edited: 3, flagged: 3, skipped: 1 });
  const cur = await getCursor(request);
  expect(cur.current_block_id).toBe(Q[20].block_id);
  expect(last(cur.trail)).toBe(Q[19].block_id);
  await expect(card(page, Q[roles.indexOf("SKIP")].block_id)).toBeVisible();
  expect((await getQueue(request)).counts.pending).toBe(after.pending);
});

// ===============================================================================================================
test("T7 edit mode: letters are text, Esc cancels, Ctrl/Cmd+Enter saves", async ({ page, request }) => {
  const first = await findQueued(request, editable);
  const second = await findQueued(request, editable, { skip: new Set([first.item.block_id]) });
  await putCursor(request, first.item.block_id);
  await page.goto("/verify");
  await expect(card(page, first.item.block_id)).toBeFocused();
  const maxId = await maxRow(request);
  const cursorBefore = await getCursor(request);
  await key(page, "e");
  const ta = page.getByLabel("Edit block text");
  await expect(ta).toBeFocused();
  const original = await ta.inputValue();
  expect(original).toBe(first.detail.block.clean_text);
  await key(page, "ControlOrMeta+End");
  const typed = "ajkfetsg/[]12345?x";
  await page.keyboard.type(typed);
  await expect(ta).toHaveValue(original + typed);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByTestId("block-id")).toHaveText(first.item.block_id);
  await expect(page.getByTestId("view-text")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Sort")).toHaveValue("worst_first");
  expect(await maxRow(request), "typing letters created no decision").toBe(maxId);
  await shot(page, "07-edit-mode-typing");
  await key(page, "Escape");
  await expect(ta).toHaveCount(0);
  await expect(card(page, first.item.block_id)).toBeFocused();
  expect(await maxRow(request), "Esc created no decision").toBe(maxId);
  const d1 = await getDetail(request, first.item.block_id);
  expect(d1.block.status).toBe("queued");
  expect(d1.block.clean_text).toBe(first.detail.block.clean_text);
  expect((await getCursor(request)).current_block_id).toBe(cursorBefore.current_block_id ?? first.item.block_id);
  // reopening starts from the unmodified text (draft discarded)
  await key(page, "e");
  await expect(page.getByLabel("Edit block text")).toHaveValue(original);
  // Control+Enter saves
  await key(page, "ControlOrMeta+End");
  await page.keyboard.type(" ");
  await key(page, "Control+Enter");
  await expect(page.getByLabel("Edit block text")).toHaveCount(0);
  await expect.poll(async () => (await getDetail(request, first.item.block_id)).block.status).toBe("edited");
  expect((await rows(request)).filter((r) => r.id > maxId && r.kind === "edit" && r.target_id === first.item.block_id)).toHaveLength(1);
  const nxt = (await getCursor(request)).current_block_id!;
  await expect(card(page, nxt)).toBeFocused();
  // Meta+Enter saves too
  await putCursor(request, second.item.block_id);
  await page.reload();
  await expect(card(page, second.item.block_id)).toBeFocused();
  await key(page, "e");
  await expect(page.getByLabel("Edit block text")).toBeFocused();
  await key(page, "ControlOrMeta+End");
  await page.keyboard.type(" ");
  await key(page, "Meta+Enter");
  await expect.poll(async () => (await getDetail(request, second.item.block_id)).block.status, { message: "Meta+Enter saves" }).toBe("edited");
  // plain Enter in the textarea is a newline, not a save
  const third = await findQueued(request, editable);
  await putCursor(request, third.item.block_id);
  await page.reload();
  await expect(card(page, third.item.block_id)).toBeFocused();
  await key(page, "e");
  await expect(page.getByLabel("Edit block text")).toBeFocused();
  await key(page, "Enter");
  await expect(page.getByLabel("Edit block text")).toBeVisible();
  expect((await getDetail(request, third.item.block_id)).block.status).toBe("queued");
  await key(page, "Escape");
});

// ===============================================================================================================
test("T8 flag dialog: chips 1-5, note, Enter submits, Esc cancels", async ({ page, request }) => {
  const a = await findQueued(request, (d) => d.block.type !== "figure");
  const b = await findQueued(request, (d) => d.block.type !== "figure", { skip: new Set([a.item.block_id]) });
  await putCursor(request, a.item.block_id);
  await page.goto("/verify");
  await expect(card(page, a.item.block_id)).toBeFocused();
  const maxId = await maxRow(request);
  const flagsBefore = (await getFlags(request)).length;
  await key(page, "f");
  const dlg = page.getByRole("dialog", { name: "Flag block" });
  await expect(dlg).toBeVisible();
  await expect(dlg).toHaveAttribute("aria-modal", "true");
  await expect(page.getByRole("radiogroup")).toBeFocused();
  await expect(dlg.getByRole("radio")).toHaveCount(5);
  const cats = ["wrong_text", "missing_figure", "wrong_grouping", "bad_crop", "table_structure"];
  const labels = ["Wrong text", "Missing figure", "Wrong grouping", "Bad crop", "Table structure"];
  for (let n = 1; n <= 5; n++) {
    await key(page, String(n));
    for (let k = 1; k <= 5; k++) await expect(page.getByTestId(`flag-cat-${cats[k - 1]}`)).toHaveAttribute("aria-checked", k === n ? "true" : "false");
    await expect(page.getByTestId(`flag-cat-${cats[n - 1]}`)).toContainText(labels[n - 1]);
  }
  expect(page.url(), "digits 1-5 did not navigate screens").toContain("/verify");
  await shot(page, "08-flag-dialog");
  // Enter with no category: message, no flag
  await key(page, "Escape");
  await expect(dlg).toHaveCount(0);
  await expect(card(page, a.item.block_id)).toBeFocused();
  expect(await maxRow(request), "Esc cancels without a decision").toBe(maxId);
  expect((await getFlags(request)).length).toBe(flagsBefore);
  await key(page, "f");
  await key(page, "Enter");
  await expect(page.getByTestId("flag-msg")).toContainText(/Choose a category/i);
  expect((await getFlags(request)).length).toBe(flagsBefore);
  // focus trap
  for (let i = 0; i < 9; i++) { await key(page, "Tab"); expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]')), `Tab ${i} stays in dialog`).toBe(true); }
  // pick 4, note, Enter in the note does NOT submit, Shift+Tab back to the chips and Enter submits
  await page.getByRole("radiogroup").focus();
  await key(page, "4");
  await key(page, "Tab");
  await expect(page.getByLabel("Note (optional)")).toBeFocused();
  await page.keyboard.type("crop is cut off at the right");
  await key(page, "Enter");
  await expect(dlg).toBeVisible();
  expect((await getFlags(request)).length).toBe(flagsBefore);
  await key(page, "Shift+Tab");
  await expect(page.getByRole("radiogroup")).toBeFocused();
  await key(page, "Enter");
  await expect(dlg).toHaveCount(0);
  await expect.poll(async () => (await getFlags(request)).length).toBe(flagsBefore + 1);
  const f = (await getFlags(request)).find((x) => x.target_id === a.item.block_id)!;
  expect(f.category).toBe("bad_crop");
  expect(f.note).toBe("crop is cut off at the right");
  expect(f.status).toBe("open");
  expect((await getDetail(request, a.item.block_id)).block.status).toBe("flagged");
  expect((await getQueue(request)).counts.flagged_open).toBeGreaterThan(0);
  const nextId = (await getCursor(request)).current_block_id!;
  await expect(card(page, nextId)).toBeFocused();
  // each category reaches the server (second block, category 5 with Ctrl/Cmd+Enter, no note)
  await putCursor(request, b.item.block_id);
  await page.reload();
  await expect(card(page, b.item.block_id)).toBeFocused();
  await key(page, "f");
  await expect(page.getByRole("radiogroup")).toBeFocused();
  await key(page, "5");
  await key(page, "ControlOrMeta+Enter");
  await expect.poll(async () => (await getFlags(request)).find((x) => x.target_id === b.item.block_id)?.category).toBe("table_structure");
  // figure block: bad_crop targets the figure
  const fig = (await getQueue(request)).items.find((i) => i.type === "figure");
  if (fig) {
    const fd = await getDetail(request, fig.block_id);
    await putCursor(request, fig.block_id);
    await page.reload();
    await expect(card(page, fig.block_id)).toBeFocused();
    await key(page, "f");
    await expect(page.getByRole("radiogroup")).toBeFocused();
    await key(page, "4");
    await key(page, "Enter");
    await expect.poll(async () => (await getFlags(request)).find((x) => x.target_id === fd.block.figure_id)?.category, { message: "flag on a figure block targets the figure id (design O6)" }).toBe("bad_crop");
  }
});

// ===============================================================================================================
test("T9 numeric approve sets numbers_verified; non-numeric leaves it false", async ({ page, request }) => {
  const num = await findQueued(request, (d) => d.block.has_numeric_spec && d.block.type !== "figure" && !d.block.numbers_verified);
  const non = await findQueued(request, (d) => !d.block.has_numeric_spec && d.block.type !== "figure");
  await putCursor(request, num.item.block_id);
  await page.goto("/verify");
  await expect(card(page, num.item.block_id)).toBeFocused();
  await expect(page.getByTestId("why-rule")).toBeVisible();
  await key(page, "a");
  await expect(page.getByTestId("save-state")).toHaveText("Saved");
  const dn = await getDetail(request, num.item.block_id);
  expect(dn.block.status).toBe("approved");
  expect(dn.block.numbers_verified).toBe(true);
  expect(last(dn.history)?.numbers_verified).toBe(true);
  await key(page, "k");
  await expect(page.getByTestId("block-id")).toHaveText(num.item.block_id);
  await expect(page.getByTestId("extracted-pane")).toContainText("numbers verified");
  await shot(page, "09-numbers-verified");
  await putCursor(request, non.item.block_id);
  await page.reload();
  await expect(card(page, non.item.block_id)).toBeFocused();
  await key(page, "a");
  await expect(page.getByTestId("save-state")).toHaveText("Saved");
  const dm = await getDetail(request, non.item.block_id);
  expect(dm.block.status).toBe("approved");
  expect(dm.block.numbers_verified).toBe(false);
  expect(last(dm.history)?.numbers_verified).toBe(false);
  await key(page, "k");
  await expect(page.getByTestId("block-id")).toHaveText(non.item.block_id);
  await expect(page.getByTestId("extracted-pane")).not.toContainText("numbers verified");
});

// ===============================================================================================================
test("T10 figure rail: fields, keyboard re-attach persists, detach, crop bbox job", async ({ page, request }) => {
  const figs = await api(request).get<DocFigure[]>("/api/docs/figures/figures");
  const Qf = (await getQueue(request)).items.filter((i) => i.doc_id === "figures" && i.type === "paragraph");
  const byArticle = new Map<string, string>();
  for (const it of Qf.slice(0, 40)) {
    const d = await getDetail(request, it.block_id);
    const a = d.article_ids?.[0];
    if (a && !byArticle.has(a)) {
      const rail = await api(request).get<FigureRailItem[]>(`/api/articles/${a}/figures`);
      if (rail.length > 0) byArticle.set(a, it.block_id);
    }
  }
  let pick: { B: string; block: string; F: DocFigure } | null = null;
  find: for (const [B, block] of byArticle)
    for (const F of figs)
      if (!(F.attachments ?? []).some((x) => x.article_id === B) && (F.attachments ?? []).length > 0) { pick = { B, block, F }; break find; }
  if (!pick) throw new Error("no (article, figure) pair for re-attach");
  const { B, block, F } = pick;
  const prevArticles = (F.attachments ?? []).map((x) => x.article_id);
  await putCursor(request, block);
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(block);

  // a) rail content equals the API per article
  const detail = await getDetail(request, block);
  for (const art of detail.article_ids ?? []) {
    const rail = await api(request).get<FigureRailItem[]>(`/api/articles/${art}/figures`);
    const sec = page.getByLabel(`Figures in ${art}`);
    await expect(sec.locator("[data-testid^=rail-item-]")).toHaveCount(rail.length);
    for (const it of rail) {
      const li = sec.getByTestId(`rail-item-${it.figure_id}`);
      await expect(li).toBeVisible();
      const t = await li.innerText();
      expect(t).toContain(it.figure_id);
      if (it.record.caption_original) expect(t.replace(/\s+/g, " ")).toContain(it.record.caption_original.slice(0, 20));
      expect(t).toContain(it.record.extraction);
      await expect(li.getByTestId("rail-rule")).toHaveText(it.attachment?.rule ?? "unattached");
      if (it.attachment?.confidence != null) expect(t).toContain(it.attachment.confidence.toFixed(2));
      const im = li.locator("img");
      await expect.poll(() => im.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth > 0)).toBe(true);
      expect(await im.getAttribute("src")).toContain(`v=${it.record.phash}`);
    }
  }
  await shot(page, "10-rail");

  // b) re-attach with the keyboard picker
  await key(page, "g");
  await expect(page.getByTestId("rail-attach").first()).toBeFocused();
  await key(page, "Enter");
  const picker = page.getByRole("dialog", { name: "Attach a figure" });
  await expect(picker).toBeVisible();
  await expect(picker.getByRole("listbox")).toBeVisible();
  await page.keyboard.type(F.figure_id);
  await key(page, "ArrowDown");
  await shot(page, "10-picker");
  await key(page, "Enter");
  const item = page.getByLabel(`Figures in ${B}`).getByTestId(`rail-item-${F.figure_id}`);
  await expect(item).toBeVisible();
  await expect(item.getByTestId("rail-rule")).toHaveText("human");
  await waitJobsIdle(request);
  await page.reload();
  await expect(page.getByTestId("block-id")).toHaveText(block);
  await expect(page.getByLabel(`Figures in ${B}`).getByTestId(`rail-item-${F.figure_id}`).getByTestId("rail-rule")).toHaveText("human");
  const railB = await api(request).get<FigureRailItem[]>(`/api/articles/${B}/figures`);
  expect(railB.find((x) => x.figure_id === F.figure_id)?.attachment?.rule).toBe("human");
  for (const a of prevArticles) expect((await api(request).get<FigureRailItem[]>(`/api/articles/${a}/figures`)).map((x) => x.figure_id), `detached from ${a}`).not.toContain(F.figure_id);

  // c) detach with x
  await page.getByLabel(`Figures in ${B}`).getByTestId(`rail-item-${F.figure_id}`).focus();
  await key(page, "x");
  await expect(page.getByLabel(`Figures in ${B}`).getByTestId(`rail-item-${F.figure_id}`).getByTestId("rail-pending")).toBeVisible();
  await waitJobsIdle(request);
  await page.reload();
  await expect(page.getByTestId("block-id")).toHaveText(block);
  await expect(page.getByLabel(`Figures in ${B}`).getByTestId(`rail-item-${F.figure_id}`)).toHaveCount(0);
  expect((await api(request).get<FigureRailItem[]>(`/api/articles/${B}/figures`)).map((x) => x.figure_id)).not.toContain(F.figure_id);

  // d) crop: form synced with the record, validation, save -> figures job -> rail refresh
  const G = (await api(request).get<FigureRailItem[]>(`/api/articles/${B}/figures`)).find((x) => x.record.bbox)!;
  const bb = G.record.bbox!;
  const jobsBefore = new Set((await api(request).get<JobInfo[]>("/api/jobs")).map((j) => j.id));
  await page.getByLabel(`Figures in ${B}`).getByTestId(`rail-item-${G.figure_id}`).focus();
  await key(page, "c");
  await expect(page.getByTestId("crop-editor")).toBeVisible();
  for (const [i, n] of ["x0", "y0", "x1", "y1"].entries()) expect(Number(await page.getByLabel(n, { exact: true }).inputValue())).toBeCloseTo(bb[i], 1);
  await expect(page.getByTestId("crop-box")).toBeVisible();
  await expect(page.locator("[data-testid^=crop-handle-]")).toHaveCount(4);
  await page.getByLabel("x0", { exact: true }).fill(String(bb[2] + 5));
  await expect(page.getByTestId("crop-error")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save crop" })).toBeDisabled();
  await page.getByLabel("x0", { exact: true }).fill(String(bb[0]));
  await expect(page.getByTestId("crop-error")).toHaveCount(0);
  const newY1 = bb[3] - 10;
  await page.getByLabel("y1", { exact: true }).fill(String(newY1));
  await shot(page, "10-crop");
  const put = page.waitForResponse((r) => /\/api\/figures\/.+\/bbox/.test(r.url()) && r.request().method() === "PUT");
  await page.getByLabel("y1", { exact: true }).press("Enter");
  const resp = await put;
  expect(resp.status()).toBe(202);
  expect((resp.request().postDataJSON() as { bbox: number[] }).bbox[3]).toBeCloseTo(newY1, 1);
  await expect.poll(async () => (await api(request).get<JobInfo[]>("/api/jobs")).filter((j) => !jobsBefore.has(j.id) && (j.plan?.force as string[] | undefined)?.includes("figures")).length, { message: "a figures job appears in /api/jobs" }).toBeGreaterThan(0);
  await waitJobsIdle(request);
  const updated = (await api(request).get<DocFigure[]>("/api/docs/figures/figures")).find((x) => x.figure_id === G.figure_id)!;
  expect(updated.record.bbox![3]).toBeCloseTo(newY1, 1);
  await expect(page.getByTestId("crop-editor")).toHaveCount(0);
  const thumb = page.getByLabel(`Figures in ${B}`).getByTestId(`rail-item-${G.figure_id}`).locator("img");
  await expect.poll(async () => await thumb.getAttribute("src"), { message: "rail refreshed: thumbnail cache-bust equals the record phash" }).toContain(`v=${updated.record.phash}`);
  await expect(page.getByLabel(`Figures in ${B}`).getByTestId(`rail-item-${G.figure_id}`).getByTestId("rail-pending")).toHaveCount(0);
  // restore the original crop so later tests see the seeded figure
  await api(request).put(`/api/figures/${G.figure_id}/bbox`, { bbox: bb, request_id: rid() });
  await waitJobsIdle(request);
});

// ===============================================================================================================
test("T11 autosave and resume (reload and a brand-new browser context)", async ({ page, request, browser }) => {
  const q = (await getQueue(request, "&sort=by_page")).items;
  await putCursor(request, q[0].block_id, { sort: "by_page" });
  const maxId = await maxRow(request);
  await page.goto("/verify");
  await expect(page.getByLabel("Sort")).toHaveValue("by_page");
  await expect(card(page, q[0].block_id)).toBeFocused();
  await key(page, "a");
  await expect(card(page, q[1].block_id)).toBeFocused();
  await key(page, "j");
  await expect(card(page, q[2].block_id)).toBeFocused();
  await key(page, "a");
  await expect(card(page, q[3].block_id)).toBeFocused();
  await expect(page.getByTestId("save-state")).toHaveText("Saved");
  // every action persisted the moment it was acked
  const rs = (await rows(request)).filter((r) => r.id > maxId && r.screen === "verify").map((r) => `${r.kind}:${r.target_id}`);
  expect(rs).toEqual([`approve:${q[0].block_id}`, `skip:${q[1].block_id}`, `approve:${q[2].block_id}`]);
  expect((await getCursor(request)).current_block_id).toBe(q[3].block_id);
  await page.reload();
  await expect(card(page, q[3].block_id)).toBeFocused();
  await expect(page.getByTestId("block-id")).toHaveText(q[3].block_id);
  await expect(page.getByLabel("Sort")).toHaveValue("by_page");
  // brand-new context: no cookies/localStorage, server state only
  const ctx = await browser.newContext({ baseURL: BASE });
  const p2 = await ctx.newPage();
  await p2.goto("/verify");
  await expect(p2.getByTestId(`card-${q[3].block_id}`)).toBeFocused();
  await expect(p2.getByTestId("block-id")).toHaveText(q[3].block_id);
  await expect(p2.getByLabel("Sort")).toHaveValue("by_page");
  await shot(p2, "11-resume-new-context");
  await ctx.close();
});

// ===============================================================================================================
test("T12 'changed since approval' chip when the clean text changes underneath an approval", async ({ page, request }) => {
  const X = await findQueued(request, (d) => d.block.doc_id === "clean" && d.block.type === "paragraph" && d.block.clean_text != null);
  const id = X.item.block_id;
  await putCursor(request, id);
  await page.goto("/verify");
  await expect(card(page, id)).toBeFocused();
  await key(page, "a");
  await expect(page.getByTestId("save-state")).toHaveText("Saved");
  expect((await getDetail(request, id)).block.status).toBe("approved");
  const cleanPath = path.join(projectDir(), "docs", "clean", "clean.json");
  const original = fs.readFileSync(cleanPath, "utf8");
  try {
    const j = JSON.parse(original) as { blocks: { block_id: string; clean_text: string }[] };
    const row = j.blocks.find((b) => b.block_id === id)!;
    row.clean_text = `${row.clean_text} (revised)`;
    fs.writeFileSync(cleanPath, JSON.stringify(j, null, 2));
    // server: status falls back to the machine status and the item says why
    const d = await getDetail(request, id);
    expect(d.block.status, "approval is invalidated").not.toBe("approved");
    expect(d.why?.[0]?.name).toBe("changed since approval");
    const item = (await getQueue(request)).items.find((i) => i.block_id === id)!;
    expect(item, "block is back in the queue").toBeTruthy();
    expect(item.reasons?.[0]).toBe("changed since approval");
    await putCursor(request, id);
    await page.reload();
    await expect(page.getByTestId("block-id")).toHaveText(id);
    await expect(card(page, id)).toContainText("changed since approval");
    await expect(page.getByTestId("stale-chip").first()).toContainText("changed since approval");
    await expect(page.getByTestId("why-stale")).toBeVisible();
    await expect(page.getByTestId("block-status")).not.toHaveText(/^Approved$/i);
    await shot(page, "12-changed-since-approval");
    // re-approving clears the chip and approves again
    await key(page, "a");
    await expect.poll(async () => (await getDetail(request, id)).block.status).toBe("approved");
  } finally {
    fs.writeFileSync(cleanPath, original);
  }
  // the approval now covers the revised text; restoring the original text invalidates it again (symmetry)
  const back = await getDetail(request, id);
  expect(back.block.status).not.toBe("approved");
  expect(back.why?.[0]?.name).toBe("changed since approval");
});

// ===============================================================================================================
test("T13 documents still scoring: scored docs usable, unscored marked pending, actions < 500 ms", async ({ page, request }) => {
  await installProbe(page);
  const dir = projectDir();
  const scores = path.join(dir, "docs", "figures", "scores.json");
  const hidden = `${scores}.hidden`;
  const before = await getQueue(request);
  expect(before.items.some((i) => i.doc_id === "figures")).toBe(true);
  const job = await api(request).post<JobInfo>("/api/jobs", { to: "score2", docs: ["scanned"], force: ["parse"], allow_reparse: true });
  fs.renameSync(scores, hidden); // an unscored doc (the mock pipeline never leaves one pending on its own)
  try {
    await expect.poll(async () => (await getQueue(request)).docs.find((d) => d.doc_id === "figures")?.state).toBe("pending");
    const q = await getQueue(request);
    expect(q.items.some((i) => i.doc_id === "figures"), "unscored doc has no cards").toBe(false);
    expect(q.items.length).toBeGreaterThan(20);
    await putCursor(request, q.items[0].block_id);
    await page.goto("/verify");
    await expect(card(page, q.items[0].block_id)).toBeFocused();
    await expect(page.getByTestId("doc-chip").filter({ hasText: "figures: preparing" })).toBeVisible();
    await expect(page.getByTestId("queue-footer")).toContainText("still preparing");
    const st = await api(request).get<JobInfo>(`/api/jobs/${job.id}`);
    expect(["queued", "running"], "the job is still running while we work").toContain(st.status);
    // scanned doc is being re-scored: its cards stay actionable and are marked
    const reScoring = (await getQueue(request)).docs.find((d) => d.doc_id === "scanned")?.stale;
    if (reScoring) {
      await expect(page.getByTestId("doc-chip").filter({ hasText: "scanned: re-scoring" })).toBeVisible();
      await expect(card(page, q.items[0].block_id)).toContainText("re-scoring");
    }
    await shot(page, "13-pending-doc");
    // interactivity: 6 approves, each acked and advanced < 500 ms while the job runs
    const lat: { focus: number; ack: number }[] = [];
    for (let i = 0; i < 6; i++) {
      const p0 = await readProbe(page);
      const k0 = p0.keys.length;
      await key(page, "a");
      await expect(card(page, q.items[i + 1].block_id)).toBeFocused();
      await expect(page.getByTestId("save-state")).toHaveText("Saved");
      const p = await readProbe(page);
      const t0 = p.keys[k0];
      const f = p.focus.find((x) => x.t >= t0 && x.id === `card-${q.items[i + 1].block_id}`)!;
      const post = p.posts.find((x) => x.t0 >= t0)!;
      lat.push({ focus: f.t - t0, ack: post.t1 - t0 });
    }
    console.log("T13 latencies ms", JSON.stringify(lat.map((l) => ({ focus: Math.round(l.focus), ack: Math.round(l.ack) }))));
    for (const l of lat) { expect(l.focus, "optimistic advance").toBeLessThan(500); expect.soft(l.ack, "server ack < 500 ms while a re-parse job runs").toBeLessThan(500); }
    const stillRunning = (await api(request).get<JobInfo>(`/api/jobs/${job.id}`)).status;
    expect(["queued", "running"], "actions completed during the job").toContain(stillRunning);
    await key(page, "ArrowDown");
    await expect(page.getByTestId("view-copy")).toBeVisible();
  } finally {
    fs.renameSync(hidden, scores);
    await waitJobsIdle(request, 150_000).catch(() => undefined);
  }
  test.info().annotations.push({ type: "note", description: "job + restore done" });
  // scores restored: the doc's blocks join the list on the 3 s refetch, chip disappears
  await expect.poll(async () => (await getQueue(request)).docs.find((d) => d.doc_id === "figures")?.state).toBe("ready");
  await expect(page.getByTestId("doc-chip").filter({ hasText: "figures: preparing" })).toHaveCount(0, { timeout: 15_000 });
  await waitJobsIdle(request, 180_000);
});

// ===============================================================================================================
test("T14 accessibility (axe), roles, focus rings, and responsiveness numbers", async ({ page, request, browser }) => {
  // pick a figures-doc block so the rail list renders
  const fb = await findQueued(request, (d) => d.block.doc_id === "figures" && d.block.type === "paragraph" && (d.figures ?? []).length > 0);
  const t0 = Date.now();
  await putCursor(request, fb.item.block_id);
  await installProbe(page);
  await page.goto("/verify");
  await expect(card(page, fb.item.block_id)).toBeFocused();
  await expect(page.getByTestId("block-id")).toHaveText(fb.item.block_id);
  const img = page.locator("img[alt^='Page ']");
  await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth > 0)).toBe(true);
  const tti = await page.evaluate(() => Math.round(performance.now()));
  const wall = Date.now() - t0;
  console.log(`T14 TTI (navigation start -> focused card + block + page image) = ${tti} ms (wall incl. API call ${wall} ms)`);

  const violations: string[] = [];
  const contrast: string[] = [];
  const minor: string[] = [];
  const scan = async (label: string): Promise<void> => {
    const r = await new AxeBuilder({ page }).analyze();
    for (const v of r.violations) {
      const s = `${label}: ${v.id} (${v.impact}) ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`;
      if (v.id === "color-contrast") contrast.push(`${label}: ${v.nodes.length} nodes`);
      else if (v.impact === "serious" || v.impact === "critical") violations.push(s);
      else minor.push(s);
    }
  };
  await scan("verify");
  // roles
  await expect(page.getByRole("listbox", { name: "Review queue" })).toBeVisible();
  expect(await page.getByRole("listbox", { name: "Review queue" }).getByRole("option").count()).toBeGreaterThan(3);
  await expect(page.getByRole("list", { name: "Figures in this article" }).first()).toBeVisible();
  expect(await page.getByRole("list", { name: "Figures in this article" }).first().getByRole("listitem").count()).toBeGreaterThan(0);
  await expect(page.getByLabel("Why this needs you, signals").getByRole("listitem").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Source page" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Extracted text" })).toBeVisible();
  await expect(page.getByRole("status").first()).toBeAttached();
  // Tab through everything: every stop has a >= 2px ring
  await card(page, fb.item.block_id).focus();
  const bad: string[] = [];
  const stops = new Set<string>();
  for (let i = 0; i < 90; i++) {
    await key(page, "Tab");
    const f = await focusInfo(page);
    if (f.body) break;
    stops.add(f.desc);
    if (!f.ring) bad.push(`${f.desc} -> ${f.ringDesc}`);
  }
  expect(stops.size, "Tab reaches many controls").toBeGreaterThan(10);
  expect(bad, `tab stops with no visible ring:\n${bad.join("\n")}`).toEqual([]);
  // dialogs
  await card(page, fb.item.block_id).focus();
  await key(page, "f");
  await expect(page.getByRole("dialog", { name: "Flag block" })).toBeVisible();
  await scan("flag-dialog");
  await key(page, "Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(card(page, fb.item.block_id)).toBeFocused();
  await key(page, "g");
  await key(page, "Enter");
  await expect(page.getByRole("dialog", { name: "Attach a figure" })).toBeVisible();
  await scan("picker");
  await key(page, "Escape");
  await key(page, "Escape");
  await card(page, fb.item.block_id).focus();
  await key(page, "e");
  await expect(page.getByLabel("Edit block text")).toBeFocused();
  await scan("edit-mode");
  await key(page, "Escape");
  await key(page, "t");
  await scan("diff-view");
  await key(page, "t");
  console.log("T14 axe: serious/critical (excl. color-contrast):", JSON.stringify(violations));
  console.log("T14 axe: color-contrast:", JSON.stringify(contrast));
  console.log("T14 axe: moderate/minor:", JSON.stringify(minor));
  expect(violations, "axe serious/critical violations").toEqual([]);

  // responsiveness: 20 approves, keypress -> next card focused, and keypress -> server ack
  const Q = (await getQueue(request)).items;
  await putCursor(request, Q[0].block_id);
  await page.goto("/verify");
  await expect(card(page, Q[0].block_id)).toBeFocused();
  for (let i = 0; i < 20; i++) {
    const k0 = (await readProbe(page)).keys.length;
    await key(page, "a");
    await expect(card(page, Q[i + 1].block_id)).toBeFocused();
    await expect(page.getByTestId("save-state")).toHaveText("Saved");
    const p = await readProbe(page);
    const t = p.keys[k0];
    const f = p.focus.find((x) => x.t >= t && x.id === `card-${Q[i + 1].block_id}`)!;
    const post = p.posts.find((x) => x.t0 >= t)!;
    (page as unknown as { __lat?: number[][] }).__lat ??= [[], []];
    (page as unknown as { __lat: number[][] }).__lat[0].push(f.t - t);
    (page as unknown as { __lat: number[][] }).__lat[1].push(post.t1 - t);
  }
  const lat = (page as unknown as { __lat: number[][] }).__lat;
  const fs_ = stats(lat[0]), as_ = stats(lat[1]);
  console.log(`T14 20 actions: keypress->next focused ${JSON.stringify(fs_)} ms; keypress->server ack ${JSON.stringify(as_)} ms`);
  fs.writeFileSync(`${SHOT}/perf.json`, JSON.stringify({ tti_ms: tti, focus: fs_, ack: as_, contrast, serious: violations, minor }, null, 2));
  expect(tti, "TTI").toBeLessThan(5000);
  expect(fs_.p95, "optimistic advance p95").toBeLessThan(500);
  expect(as_.p95, "server ack p95").toBeLessThan(500);
  void browser;
});
