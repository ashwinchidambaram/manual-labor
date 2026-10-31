// Module 13 UX check: the craft redesign seen by a first-time user (design 13 sections 1, 2, 7, 8; PRODUCT.md
// principles 6 to 8). Written by a reviewer who did not build the screens. Every claim on screen is compared with the
// API (decisions, queue counts, flags, export status); expected values are computed here from API data, never
// imported from src/. Tests run in file order on one shared server: UC2 records the decisions and the flag that
// UC6b and UC8 look at. The reader's pass (UCR) only runs with UX_READER=1 and writes screenshots to UX_SHOTS.
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { BlockDetail, Cursor, ExportStatus, Flag, GuideState, QueueItem, QueuePage, ScopeSummary, SourceInfo } from "../src/api/schema";
import { plainDetail } from "../src/verify/labels";
import { api, resetSelection, waitForTree, waitJobsIdle } from "./helpers";

test.describe.configure({ mode: "default" });
test.setTimeout(240_000);

const rid = (): string => `uxc-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const key = (page: Page, k: string) => page.keyboard.press(k);
const currentCard = (page: Page) => page.locator("[data-testid^='card-'][aria-current='true']");
const setGuide = (request: APIRequestContext, seen: boolean) => api(request).put<GuideState>("/api/ui/guide", { seen });
const putCursor = (request: APIRequestContext, id: string | null) =>
  api(request).put("/api/verify/cursor", { sort: "worst_first", view_threshold: null, doc_filter: null, current_block_id: id, request_id: rid() });
const getQueue = (request: APIRequestContext, q = "") => api(request).get<QueuePage>(`/api/verify/queue?limit=2000${q}`);
const getDetail = (request: APIRequestContext, id: string) => api(request).get<BlockDetail>(`/api/verify/blocks/${id}`);
const getStatus = (request: APIRequestContext) => api(request).get<ExportStatus>("/api/export/status");
interface Row { id: number; kind: string; screen: string; target_id: string | null }
async function decisions(request: APIRequestContext): Promise<Row[]> {
  const t = await (await request.get("/api/decisions/export")).text();
  return t.split("\n").filter(Boolean).map((l) => JSON.parse(l) as Row);
}
const note = (what: string, text: string) => test.info().annotations.push({ type: what, description: text.replace(/\s+/g, " ").trim().slice(0, 1200) });
const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;
const activeDesc = (page: Page) =>
  page.evaluate(() => {
    const a = document.activeElement as HTMLElement | null;
    return a ? `${a.tagName} ${a.getAttribute("data-testid") ?? a.getAttribute("aria-label") ?? ""}` : "none";
  });

/** Shared between tests (file order): the flag UC2 raises. */
const shared: { flagTarget: string | null; flagCategory: string | null; flagLabel: string | null } = { flagTarget: null, flagCategory: null, flagLabel: null };

test.beforeAll(async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  await waitJobsIdle(ctx);
  await ctx.dispose();
});
test.beforeEach(async ({ request }) => {
  await waitJobsIdle(request);
  await setGuide(request, true);
});
test.afterAll(async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  await setGuide(ctx, true);
  await ctx.dispose();
});

/** The progress bar and its legend add up to in scope and equal the API counts. */
async function progressMatchesApi(page: Page, request: APIRequestContext, what: string): Promise<QueuePage> {
  // the screen refetches after each action: poll until the numbers settle on the server's
  let q = await getQueue(request);
  await expect
    .poll(
      async () => {
        q = await getQueue(request);
        const c = q.counts;
        const shown = await Promise.all(["cnt-done", "cnt-auto", "cnt-queued", "cnt-flagged", "cnt-scope"].map(async (t) => Number((await page.getByTestId(t).innerText()).replace(/\D/g, ""))));
        return JSON.stringify(shown) === JSON.stringify([c.approved + c.edited, c.auto_approved, c.queued, c.flagged_open, c.in_scope]);
      },
      { message: `${what}: legend numbers equal the API counts`, timeout: 20_000 },
    )
    .toBe(true);
  const c = q.counts;
  // the terms add up to in scope (the legend's four buckets plus rejected)
  expect(c.approved + c.edited + c.auto_approved + c.queued + c.flagged_open + c.rejected, `${what}: buckets add up to in scope`).toBe(c.in_scope);
  // "N of M checked by you": M is everything that is the person's to decide
  const mine = await page.getByTestId("cnt-done").locator("xpath=..").innerText();
  expect(mine, what).toContain(`of ${c.approved + c.edited + c.queued + c.flagged_open + c.rejected} checked by you`);
  // the bar's accessible description says the same numbers
  const bar = (await page.getByTestId("review-bar").getAttribute("aria-label")) ?? "";
  expect(bar, what).toContain(`${c.auto_approved} cleared by the checks`);
  expect(bar, what).toContain(`${c.queued} waiting for you`);
  expect(bar, what).toContain(`${c.in_scope} in scope`);
  // the reconcile line under it, verbatim from the server's terms
  await expect(page.getByTestId("reconcile-review"), what).toContainText(
    `In scope ${c.in_scope} = ${c.queued} to review + ${c.auto_approved} auto-approved + ${c.approved + c.edited} done + ${c.flagged_open} flagged + ${c.rejected} rejected`,
  );
  return q;
}

// ---------------------------------------------------------------------------------------------------------------
test("UC1 cold start at 1280x800: welcome names the manuals, counts match the queue, Start with step 1 lands in the list", async ({ page, request }) => {
  await resetSelection(request);
  await putCursor(request, null);
  await setGuide(request, false);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/scope");
  await waitForTree(page);
  const w = page.getByTestId("welcome");
  await expect(w).toBeVisible();
  await expect(w).toBeInViewport();
  const text = await w.innerText();
  note("welcome-text", text);
  const sources = await api(request).get<SourceInfo[]>("/api/sources");
  const summary = await api(request).get<ScopeSummary>("/api/scope/summary");
  const q = await getQueue(request);
  // the manuals: how many, and by name
  expect(text).toContain(sources.length === 1 ? "manual is read" : `${sources.length} manuals are read`);
  const pages = sources.reduce((n, s) => n + s.pages, 0);
  expect(text).toContain(plural(pages, "page"));
  const named = sources.filter((s) => text.includes(s.filename));
  note("welcome-names-manuals", `${named.length} of ${sources.length} filenames in the band: ${sources.map((s) => s.filename).join(", ")}`);
  expect.soft(named.length, "D6: the welcome band names the manuals").toBe(sources.length);
  // counts: blocks (what is in scope) and to review equal the API
  // review M13 P2-12: "found 364 blocks: 270 paragraphs, ... and 20 figures" (or "364 blocks, 20 of them figures")
  const found = /found (\d+) blocks?\b/.exec(text);
  expect(found, "welcome states the block count").not.toBeNull();
  expect(Number(found![1])).toBe(summary.blocks);
  note("in-scope", `welcome blocks ${found![1]}, scope summary blocks ${summary.blocks}, figures ${summary.figures}, queue in_scope ${q.counts.in_scope}`);
  expect(Number(found![1]), "welcome blocks = queue in scope").toBe(q.counts.in_scope);
  // the breakdown by type (when shown) adds up to the total and counts the figures once, as the API's block types say
  const types = new Map<string, number>();
  for (const d of await api(request).get<{ blocks: { type: string }[] }[]>("/api/scope/blocks"))
    for (const b of d.blocks) if (b.type !== "header" && b.type !== "footer") types.set(b.type, (types.get(b.type) ?? 0) + 1);
  note("in-scope-types", JSON.stringify(Object.fromEntries(types)));
  expect(text, "no claim that the total is text only").not.toMatch(/blocks? of text/);
  const parts = /found \d+ blocks?: ([^.]+)\./.exec(text);
  if (parts) {
    const nums = [...parts[1].matchAll(/(\d+) ([a-z ]+?)s?(?=,| and|$)/g)].map((m) => Number(m[1]));
    expect(nums.reduce((a, b) => a + b, 0), "the breakdown adds up to the total").toBe(summary.blocks);
    expect(parts[1]).toContain(plural(types.get("figure") ?? 0, "figure"));
  } else expect(text).toContain(`found ${plural(summary.blocks, "block")}, ${summary.figures} of them figure`);
  // the band names the manuals (owner decision D6)
  await expect(page.getByTestId("welcome-manuals")).toBeVisible();
  // the four steps
  const steps = w.getByRole("list", { name: "The four steps" }).getByRole("listitem");
  await expect(steps).toHaveCount(4);
  const st = await steps.allInnerTexts();
  expect(st[0]).toMatch(/Choose what goes in/);
  expect(st[1]).toContain(`Check ${plural(q.counts.queued, "block")} against the page`);
  expect(q.counts.queued, "to review on the welcome = summary review load").toBe(summary.review_load.queued);
  expect(st[2]).toMatch(/Fix anything you flag/);
  expect(st[3]).toMatch(/Export/);
  // the rail marks Scope as here
  await expect(page.getByTestId("step-short-scope")).toHaveText("here");
  await expect(page.locator("#step-state-scope")).toContainText("You are here");
  // one primary button by its visible label: focus moves into the group list
  await page.getByRole("button", { name: "Start with step 1" }).focus();
  await key(page, "Enter");
  await expect(w).toHaveCount(0);
  await expect.poll(async () => page.evaluate(() => !!document.activeElement?.closest("[data-zone='tree']")), { message: "focus is in the group list" }).toBe(true);
  note("focus-after-start", await activeDesc(page));
  await expect.poll(async () => (await api(request).get<GuideState>("/api/ui/guide")).seen).toBe(true);
  // and the next-step card on Scope says what to do here
  note("scope-next-step", await page.getByTestId("next-step-text").innerText());
});

test("UC6a Agent before any flag: three parts, designed empty states, Go to Verify works", async ({ page, request }) => {
  const flags = await api(request).get<Flag[]>("/api/flags");
  expect(flags.filter((f) => f.status === "open"), "fresh project: nothing flagged yet").toEqual([]);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/agent");
  await expect(page.getByTestId("agent-screen")).toBeVisible();
  await expect(page.getByTestId("agent-flags")).toBeVisible();
  await expect(page.getByTestId("agent-proposals")).toBeVisible();
  await expect(page.getByRole("heading", { name: "How your decisions compare with the scores" })).toBeVisible();
  const empty = page.getByTestId("agent-empty");
  await expect(empty).toBeVisible();
  note("agent-empty", await empty.innerText());
  note("agent-proposals-empty", await page.getByTestId("agent-proposals").innerText());
  note("agent-calibration", await page.getByTestId("calibration").innerText());
  await expect(page.getByTestId("agent-run")).toBeDisabled();
  await page.getByRole("link", { name: "Go to Verify" }).click();
  await expect(page).toHaveURL(/\/verify$/);
  await expect(currentCard(page)).toBeFocused();
});

test("UC2 confirm scope, read the next step, process 6 blocks keyboard-only; server, bar and focus agree after each", async ({ page, request }) => {
  await resetSelection(request);
  await putCursor(request, null);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/scope");
  await waitForTree(page);
  await page.getByRole("button", { name: /Confirm scope and go to Verify/ }).click();
  await expect(page).toHaveURL(/\/verify/);
  await expect(currentCard(page)).toBeFocused();
  const q0 = await getQueue(request);
  const firstId = q0.items[0].block_id;
  await expect(page.getByTestId("block-id")).toHaveText(firstId);
  expect(await currentCard(page).getAttribute("data-testid")).toBe(`card-${firstId}`);
  // the next-step card in the rail speaks about this block
  const next = page.getByTestId("next-step");
  await expect(next).toBeVisible();
  const nextText = await page.getByTestId("next-step-text").innerText();
  note("verify-next-step", `${nextText} | keys: ${await next.locator("dl").innerText().catch(() => "")}`);
  expect(nextText).toMatch(/page/);
  // keys learned from the action bar the user can see
  const bar = page.getByRole("toolbar", { name: "Review actions" });
  const keyOf = async (name: RegExp): Promise<string> => (await bar.getByRole("button", { name }).locator("kbd").innerText()).trim().toLowerCase();
  const K = { approve: await keyOf(/Approve/), edit: await keyOf(/^Edit/), flag: await keyOf(/^Flag/), skip: await keyOf(/^Skip/), back: await keyOf(/^Back/) };
  note("keys-from-toolbar", JSON.stringify(K));
  await progressMatchesApi(page, request, "start");

  const cur = async (): Promise<string> => (await page.getByTestId("block-id").innerText()).trim();
  const rowCount = async (id: string, kind: string): Promise<number> => (await decisions(request)).filter((r) => r.target_id === id && r.kind === kind).length;
  const afterEach = async (what: string, movedFrom: string | null): Promise<void> => {
    if (movedFrom) await expect(page.getByTestId("block-id"), `${what}: the screen moved on`).not.toHaveText(movedFrom);
    await expect(currentCard(page), `${what}: focus on a queue card (active: ${await activeDesc(page)})`).toBeFocused();
    expect(await page.evaluate(() => !!document.activeElement?.closest("[data-zone='queue']")), `${what}: focus inside the queue`).toBe(true);
    await progressMatchesApi(page, request, what);
  };
  const log: string[] = [];

  // 1, 2: approve
  for (const n of [1, 2]) {
    const id = await cur();
    const before = await rowCount(id, "approve");
    await key(page, K.approve);
    await expect.poll(() => rowCount(id, "approve"), { message: `approve ${id}` }).toBeGreaterThan(before);
    await expect.poll(async () => (await getDetail(request, id)).block.status).toBe("approved");
    await afterEach(`approve #${n} ${id}`, id);
    log.push(`approve ${id}`);
  }
  // 3: skip (stays queued, recorded)
  {
    const id = await cur();
    const before = await rowCount(id, "skip");
    await key(page, K.skip);
    await expect.poll(() => rowCount(id, "skip"), { message: `skip ${id}` }).toBeGreaterThan(before);
    expect((await getDetail(request, id)).block.status).toBe("queued");
    await afterEach(`skip ${id}`, id);
    log.push(`skip ${id}`);
  }
  // 4: edit, adding only a trailing space, saved with Ctrl/Cmd+Enter
  {
    let id = await cur();
    // a figure or a block whose cleanup failed cannot be edited this way: move on with Down until one can (noted)
    for (let i = 0; i < 10; i++) {
      const d = await getDetail(request, id);
      if (d.block.type !== "figure" && d.block.clean_text != null && d.block.faithfulness?.passed !== false) break;
      note("edit-moved", `${id} is not editable as text (${d.block.type}); ArrowDown`);
      await key(page, "ArrowDown");
      await expect(page.getByTestId("block-id")).not.toHaveText(id);
      id = await cur();
    }
    const d0 = await getDetail(request, id);
    const original = d0.block.clean_text ?? d0.block.raw_text;
    await key(page, K.edit);
    const ta = page.getByLabel("Edit block text");
    await expect(ta).toBeFocused();
    await expect(ta).toHaveValue(original);
    await key(page, "ControlOrMeta+End");
    await page.keyboard.type(" ");
    await key(page, "ControlOrMeta+Enter");
    await expect(page.getByTestId("edit-conflict"), "a trailing space is not a content change").toHaveCount(0);
    await expect.poll(async () => (await getDetail(request, id)).block.status, { message: `edit ${id}` }).toBe("edited");
    const d1 = await getDetail(request, id);
    expect((d1.block.clean_text ?? "").trimEnd(), "text unchanged except the trailing space").toBe(original.trimEnd());
    expect(await rowCount(id, "edit")).toBeGreaterThan(0);
    await afterEach(`edit ${id}`, id);
    log.push(`edit ${id}`);
  }
  // 5: flag with a category, chosen by the digit the dialog shows
  {
    const id = await cur();
    await key(page, K.flag);
    const dlg = page.getByRole("dialog", { name: "Flag block" });
    await expect(dlg).toBeVisible();
    await expect(dlg.getByRole("radiogroup")).toBeFocused();
    const first = dlg.getByRole("radio").first();
    const digit = (await first.locator("kbd").innerText()).trim();
    const label = (await first.innerText()).replace(digit, "").trim();
    await key(page, digit);
    await expect(first).toHaveAttribute("aria-checked", "true");
    await key(page, "Enter");
    await expect(dlg).toHaveCount(0);
    await expect
      .poll(async () => (await api(request).get<Flag[]>("/api/flags")).filter((f) => f.target_id === id && f.status === "open").length, { message: `flag ${id}` })
      .toBe(1);
    const f = (await api(request).get<Flag[]>("/api/flags")).find((x) => x.target_id === id)!;
    shared.flagTarget = id;
    shared.flagCategory = f.category;
    shared.flagLabel = label;
    expect(await rowCount(id, "flag")).toBeGreaterThan(0);
    await afterEach(`flag ${id} (${label})`, id);
    log.push(`flag ${id} ${f.category}`);
  }
  // 6: back
  {
    const id = await cur();
    const rowsBefore = (await decisions(request)).length;
    await key(page, K.back);
    await expect(page.getByTestId("block-id")).not.toHaveText(id);
    const back = await cur();
    const after = await decisions(request);
    note("back", `from ${id} to ${back}; decision rows ${rowsBefore} -> ${after.length}; last kinds ${after.slice(-2).map((r) => `${r.kind}:${r.target_id}`).join(", ")}`);
    const cursor = await api(request).get<Cursor>("/api/verify/cursor");
    expect(cursor.current_block_id, "the server cursor follows Back").toBe(back);
    await afterEach(`back to ${back}`, null);
    log.push(`back ${id} -> ${back}`);
  }
  note("uc2-log", log.join(" | "));
});

test("UC3 trust by showing on a scanned block: strip with the page image, every signal in API order, Passed without red, two readings", async ({ page, request }) => {
  const q = (await getQueue(request)).items.filter((i) => i.doc_id === "scanned" && i.type !== "figure");
  let pick: { item: QueueItem; d: BlockDetail } | null = null;
  for (const it of q.slice(0, 150)) {
    const d = await getDetail(request, it.block_id);
    const why = d.why ?? [];
    const held = why.some((w) => w.kind === "signal" && (w.name === "parser_agreement" || w.name === "textlayer_vs_ocr") && (w.value ?? 1) < 1);
    const passed = why.some((w) => w.kind === "signal" && w.value === 1);
    if (held && passed && (d.block.bbox ?? []).length === 4 && Object.keys(d.parser_texts ?? {}).length >= 2) {
      pick = { item: it, d };
      break;
    }
  }
  expect(pick, "a queued scanned block with two differing readings and at least one passed check").not.toBeNull();
  const { item, d } = pick!;
  await putCursor(request, item.block_id);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(item.block_id);
  // the page strip, above the text, with the page image loaded
  const strip = page.getByTestId("page-strip");
  await expect(strip).toBeVisible();
  await expect(strip).toBeInViewport();
  const img = strip.locator("img");
  await expect(img).toHaveAttribute("src", new RegExp(`/pages/${d.page.page}\\.png`));
  await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth > 0), { message: "page image loaded" }).toBe(true);
  const sb = (await strip.boundingBox())!;
  const tb = (await page.getByTestId("block-text").boundingBox())!;
  expect(sb.y + sb.height, "the strip sits above the extracted text").toBeLessThanOrEqual(tb.y + 1);
  await expect(page.getByTestId("block-text")).toBeInViewport();
  // every signal, in the server's order
  const signals = (d.why ?? []).filter((w) => w.kind === "signal");
  const items = page.getByLabel("Why this needs you, signals").locator(":scope > li");
  await expect(items).toHaveCount(signals.length);
  const texts = await items.allInnerTexts();
  note("why-list", texts.map((t, i) => `[${signals[i].name}=${signals[i].value}] ${t}`).join(" || "));
  signals.forEach((w, i) => {
    if (w.value !== null && w.value !== undefined && w.name !== "has_numeric_spec") expect(texts[i], `${w.name} at position ${i}`).toContain(`${w.value.toFixed(2)} of 1`);
    // the scorer's jargon translated at the point of use (design 09 section 14)
    if (w.detail) expect(texts[i], `${w.name} detail at position ${i}`).toContain(plainDetail(w.name, w.detail) ?? "");
  });
  // a passed check reads "Passed" and nothing in it is red
  const passedRows = page.getByLabel("Why this needs you, signals").locator(":scope > li[data-outcome='passed']");
  expect(await passedRows.count()).toBeGreaterThan(0);
  for (let i = 0; i < (await passedRows.count()); i++) {
    const r = passedRows.nth(i);
    await expect(r).toContainText("Passed");
    const reds = await r.evaluate((el) => {
      const out: string[] = [];
      for (const e of [el, ...Array.from(el.querySelectorAll<HTMLElement>("*"))]) {
        const cs = getComputedStyle(e);
        for (const c of [cs.color, cs.backgroundColor, cs.borderTopColor]) {
          const m = /rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/.exec(c);
          if (!m || (m[4] !== undefined && Number(m[4]) === 0)) continue;
          const [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])];
          if (r > 140 && r - g > 70 && r - b > 70) out.push(`${e.tagName} ${c}`);
        }
      }
      return out;
    });
    expect(reds, `passed row ${i} has no red`).toEqual([]);
  }
  const faith = page.getByTestId("check-faithfulness");
  if (d.block.faithfulness?.passed) {
    await expect(faith).toHaveAttribute("data-outcome", "passed");
    await expect(faith).toContainText("Passed");
  }
  // the two readings as labelled lines
  const cmp = page.getByTestId("parser-compare");
  await expect(cmp).toBeVisible();
  const labels = (await cmp.locator("dt:not(.col-span-2)").allInnerTexts()).map((s) => s.trim());
  const lines = await cmp.locator("dd").allInnerTexts();
  note("readings", labels.map((l, i) => `${l}: ${lines[i]}`).join(" | "));
  expect(labels.length).toBeGreaterThanOrEqual(2);
  expect(new Set(labels).size, "two different readers are named").toBeGreaterThanOrEqual(2);
  for (const l of labels) expect(l, "reader label is words, not a parser key").not.toMatch(/_|^(ocr_alt|pymupdf|docling)$/);
  // no verdict words and no model confidence anywhere in the app's own words
  const appText = await page.evaluate(() => {
    const root = document.body.cloneNode(true) as HTMLElement;
    root.querySelectorAll("[data-testid=block-text],[data-testid=parser-compare] dd,[data-testid=diff-view],textarea,.manual-text").forEach((n) => n.remove());
    return root.innerText;
  });
  const hits: string[] = [];
  for (const re of [/\bcorrect(ly)?\b/i, /\bwrong\b/i, /verified by the model/i, /model('s)? confidence/i, /confidence of the model/i, /\b\d{1,3}% (sure|confident|confidence)\b/i])
    for (const m of appText.matchAll(new RegExp(re.source, "gi"))) hits.push(`${m[0]} in "${appText.slice(Math.max(0, m.index! - 50), m.index! + 40).replace(/\s+/g, " ")}"`);
  note("verdict-words", hits.join(" || ") || "none");
  expect(hits, "no verdict words or model confidence on the screen").toEqual([]);
});

test("UC4 the whole page: Z shows it with the block outlined, Z returns; Up/Down browse and the header tracks the cursor", async ({ page, request }) => {
  const q = await getQueue(request);
  const pickIdx = Math.min(2, q.items.length - 1);
  await putCursor(request, q.items[pickIdx].block_id);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  const id = q.items[pickIdx].block_id;
  const header = page.locator("[data-zone='queue'] > p").first();
  await expect(header).toContainText(`Block ${pickIdx + 1} of ${q.total} in this list`);
  await expect(page.getByTestId("page-strip")).toBeVisible();
  await key(page, "z");
  await expect(page.getByTestId("page-strip")).toHaveCount(0);
  const pane = page.getByTestId("source-pane");
  await expect(pane).toBeVisible();
  const d = await getDetail(request, id);
  await expect(pane.locator("img")).toHaveAttribute("alt", `Page ${d.block.page} of ${d.block.doc_id}`);
  const rect = page.getByTestId(`rect-${id}`);
  await expect(rect).toHaveAttribute("data-current", "true");
  await rect.scrollIntoViewIfNeeded();
  await expect(rect).toBeVisible();
  const border = await rect.evaluate((e) => getComputedStyle(e).borderTopWidth);
  expect(parseFloat(border), "the current block is outlined").toBeGreaterThanOrEqual(2);
  await expect(page.getByText("back to the block")).toBeVisible();
  await expect(currentCard(page), "Z keeps focus on the card").toBeFocused();
  await key(page, "z");
  await expect(page.getByTestId("page-strip")).toBeVisible();
  // browse
  await key(page, "ArrowDown");
  await expect(page.getByTestId("block-id")).toHaveText(q.items[pickIdx + 1].block_id);
  await expect(header).toContainText(`Block ${pickIdx + 2} of ${q.total} in this list`);
  await expect(currentCard(page)).toBeFocused();
  await key(page, "ArrowDown");
  await expect(header).toContainText(`Block ${pickIdx + 3} of ${q.total} in this list`);
  await key(page, "ArrowUp");
  await key(page, "ArrowUp");
  await expect(page.getByTestId("block-id")).toHaveText(id);
  await expect(header).toContainText(`Block ${pickIdx + 1} of ${q.total} in this list`);
  // the action bar repeats the position
  const pos = await page.getByRole("toolbar", { name: "Review actions" }).innerText();
  note("toolbar-position", pos);
  expect((await api(request).get<Cursor>("/api/verify/cursor")).current_block_id, "browsing is saved").toBe(id);
});

test("UC5 narrow widths (720x900, 720x450): strip and text together, action bar reachable, step sheet, axe on four screens", async ({ page, request }) => {
  const q = await getQueue(request);
  await putCursor(request, q.items[0].block_id);
  const geometry: string[] = [];
  for (const vp of [
    { width: 720, height: 900 },
    { width: 720, height: 450 },
  ]) {
    const tag = `${vp.width}x${vp.height}`;
    await page.setViewportSize(vp);
    await page.goto("/verify");
    await expect(currentCard(page)).toBeFocused();
    const strip = page.getByTestId("page-strip");
    const text = page.getByTestId("block-text");
    await expect(strip).toBeVisible();
    const sb = await strip.boundingBox();
    const tb = await text.boundingBox();
    geometry.push(`${tag}: strip y=${Math.round(sb!.y)} h=${Math.round(sb!.height)}; text y=${Math.round(tb!.y)} h=${Math.round(tb!.height)}; doc scrollH=${await page.evaluate(() => document.documentElement.scrollHeight)}`);
    await expect.soft(strip, `${tag}: strip in view`).toBeInViewport();
    await expect.soft(text, `${tag}: text in view together with the strip`).toBeInViewport();
    // in view is not enough: nothing (the step sheet, the action bar) may sit on top of them
    const onTop = async (sel: string): Promise<string> =>
      page.evaluate((s) => {
        const el = document.querySelector<HTMLElement>(s);
        if (!el) return "missing";
        const r = el.getBoundingClientRect();
        const y = Math.min(r.top + Math.min(r.height, 40) / 2, window.innerHeight - 1);
        const hit = document.elementFromPoint(r.left + r.width / 2, y) as HTMLElement | null;
        return hit && el.contains(hit) ? "visible" : `covered by ${hit?.closest("[data-testid],[aria-label],[role]")?.getAttribute("data-testid") ?? hit?.closest("[aria-label]")?.getAttribute("aria-label") ?? hit?.tagName}`;
      }, sel);
    const stripTop = await onTop("[data-testid=page-strip] > div"); // the frame: the image itself ignores the pointer
    const textTop = await onTop("[data-testid=block-text]");
    geometry.push(`${tag}: strip ${stripTop}; text ${textTop}`);
    expect.soft(stripTop, `${tag}: the strip is not covered`).toBe("visible");
    expect.soft(textTop, `${tag}: the text is not covered`).toBe("visible");
    // action bar: every decision button is on screen and not covered
    const covered: string[] = [];
    for (const t of ["act-approve", "act-edit", "act-flag", "act-skip", "act-back"]) {
      const b = page.getByTestId(t);
      if (!(await b.isVisible())) {
        covered.push(`${t} hidden`);
        continue;
      }
      const box = (await b.boundingBox())!;
      const inView = box.y >= 0 && box.y + box.height <= vp.height;
      const hit = await page.evaluate(([x, y, id]) => !!(document.elementFromPoint(x as number, y as number) as HTMLElement | null)?.closest(`[data-testid='${id}']`), [box.x + box.width / 2, box.y + box.height / 2, t] as const);
      if (!inView || !hit) covered.push(`${t} y=${Math.round(box.y)} inView=${inView} hit=${hit}`);
    }
    expect.soft(covered, `${tag}: action bar reachable`).toEqual([]);
    // the bottom step sheet shows the four steps
    const sheet = page.getByRole("complementary", { name: "Getting started" });
    await expect(sheet).toBeVisible();
    const shb = (await sheet.boundingBox())!;
    expect(Math.round(shb.y + shb.height), `${tag}: sheet pinned to the bottom`).toBe(vp.height);
    const links = sheet.getByRole("navigation", { name: "Screens" }).getByRole("link");
    await expect(links).toHaveCount(4);
    for (let i = 0; i < 4; i++) await expect(links.nth(i)).toBeInViewport();
    geometry.push(`${tag}: sheet y=${Math.round(shb.y)} h=${Math.round(shb.height)}; covered=${covered.join(",") || "none"}`);
    // the queue collapsed to its header (design 13 section 2.5.4)
    const header = page.locator("[data-zone='queue'] > p").first();
    await expect(header).toContainText("Block 1 of");
  }
  note("geometry", geometry.join(" | "));
  // axe at the narrow width on all four screens
  await page.setViewportSize({ width: 720, height: 900 });
  const bad: string[] = [];
  const contrast: string[] = [];
  const scan = async (label: string): Promise<void> => {
    const r = await new AxeBuilder({ page }).analyze();
    for (const v of r.violations) {
      if (v.impact !== "serious" && v.impact !== "critical") continue;
      const s = `${label}: ${v.id} (${v.impact}, ${v.nodes.length}) ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`;
      bad.push(s);
      if (v.id === "color-contrast") contrast.push(`${label}: ${v.nodes.slice(0, 4).map((n) => `${n.target.join(" ")} ${n.any[0]?.message ?? ""}`).join(" || ")}`);
    }
  };
  await page.goto("/scope");
  await waitForTree(page);
  await scan("scope");
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await scan("verify");
  await page.goto("/agent");
  await expect(page.getByTestId("agent-flags")).toBeVisible();
  await scan("agent");
  await page.goto("/export");
  await expect(page.getByTestId("export-screen")).toBeVisible();
  await scan("export");
  note("axe", bad.join(" || ") || "none");
  if (contrast.length) note("axe-contrast", contrast.join(" || "));
  expect(bad, bad.join("\n")).toEqual([]);
});

test("UC6b Agent lists the UC2 flag with a human title; Export is locked, grouped, every blocker opens Verify; rail sub-line matches", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const flags = (await api(request).get<Flag[]>("/api/flags")).filter((f) => f.status === "open");
  const target = shared.flagTarget ?? flags[0]?.target_id;
  expect(target, "UC2 raised a flag").toBeTruthy();
  const flag = flags.find((f) => f.target_id === target)!;
  const d = await getDetail(request, target!);
  const item = (await getQueue(request, "&view_threshold=1")).items.find((i) => i.block_id === target);
  await page.goto("/agent");
  const row = page.getByTestId("agent-flag").filter({ hasText: target! });
  await expect(row).toHaveCount(1);
  // titles load in the background: give them time before reading the row
  // review M13 P2-13: the title is built from the block's detail ("scanned.pdf, page 9, paragraph")
  await expect.soft(row, "design 13 2.5.5: the open flag shows a human title and page").toContainText(new RegExp(`(p\\.|page )${d.block.page}\\b`), { timeout: 10_000 });
  const rowText = await row.innerText();
  note("agent-flag-row", rowText);
  note("flag-target-in-title-source", `queue?view_threshold=1 lists the flagged block: ${!!item}; its section_title: ${item?.section_title ?? "n/a"}; block status ${d.block.status}`);
  // human title first (the section heading, else the document), then the category in words, then the id
  const firstLine = rowText.split("\n")[0];
  expect(firstLine, "the flag's first line is a title, not an id").not.toMatch(/^b-/);
  if (item?.section_title) expect.soft(firstLine).toContain(item.section_title);
  if (shared.flagLabel) expect(rowText).toContain(shared.flagLabel);
  expect(flag.category).toBe(shared.flagCategory ?? flag.category);
  await expect(page.getByTestId("agent-run")).toBeEnabled();
  await expect(page.getByTestId("agent-run")).toContainText(plural(flags.length, "flag"));
  // the rail's Export step, read from a screen that is not Export
  const st = await getStatus(request);
  const short = (await page.getByTestId("step-short-export").innerText()).trim();
  const long = (await page.locator("#step-state-export").innerText()).trim();
  note("export-step", `short "${short}" | long "${long}" | status queued=${st.queued} open_flags=${st.open_flags} blockers=${(st.blockers ?? []).length} unlocked=${st.unlocked}`);
  expect(st.unlocked).toBe(false);
  expect(short).toMatch(/^locked: /);
  const nums = [...short.matchAll(/\d+/g)].map((m) => Number(m[0]));
  expect(nums.length).toBe(1);
  // the gate's counts as every screen reads them (design 11 section 17): flags that hold the export, blocks to review
  const holdFlags = (st.flag_blockers ?? []).length;
  const toReview = st.counts?.to_review ?? st.queued;
  expect([holdFlags, toReview], `the sub-line's number is one of the gate's counts`).toContain(nums[0]);
  if (holdFlags > 0) expect(long).toContain(plural(holdFlags, "open flag"));
  if (toReview > 0) expect(long).toContain(`${toReview} to review`);
  // Export: locked, reasons with the gate's counts, blockers grouped by section
  await page.goto("/export");
  await expect(page.getByRole("heading", { name: "Export is locked" })).toBeVisible();
  if (holdFlags > 0) await expect(page.getByTestId("reason-flags")).toContainText(plural(holdFlags, "open flag"));
  if (toReview > 0) await expect(page.getByTestId("reason-queued")).toContainText(plural(toReview, "block"));
  const list = page.getByTestId("blocker-list");
  await expect(list).toBeVisible();
  const groups = list.locator(":scope > li");
  const nG = await groups.count();
  const seen: string[] = [];
  const groupNotes: string[] = [];
  for (let g = 0; g < nG; g++) {
    const gi = groups.nth(g);
    const head = (await gi.locator("p").first().innerText()).trim();
    const ids = (await gi.getByTestId("blocker-link").allInnerTexts()).map((s) => s.trim());
    groupNotes.push(`${head} [${ids.join(" ")}]`);
    expect(head, `group ${g} has a human title`).not.toMatch(/^(Blocks|b-)/);
    // review M13 P2-14: a list cut off at the server's limit counts "N of these M", never a section total
    const cutOff = /first \d+ listed/.test(await page.getByTestId("blocker-count").innerText());
    expect(head, `group ${g} count`).toContain(cutOff ? `${ids.length} of these ${(st.blockers ?? []).length}` : plural(ids.length, "block"));
    seen.push(...ids);
  }
  note("blocker-groups", groupNotes.join(" || "));
  note("blocker-count", await page.getByTestId("blocker-count").innerText());
  expect(seen, "every blocker listed once, in the server's order").toEqual(st.blockers ?? []);
  // each blocker opens Verify on that block
  const opened: string[] = [];
  for (const id of st.blockers ?? []) {
    await page.goto("/export");
    await page.getByTestId("blocker-link").filter({ hasText: new RegExp(`^${id}$`) }).click();
    await expect(page).toHaveURL(/\/verify$/);
    await expect(page.getByTestId("block-id"), `blocker ${id}`).toHaveText(id);
    await expect(page.getByTestId(`card-${id}`)).toHaveAttribute("aria-current", "true");
    expect((await api(request).get<Cursor>("/api/verify/cursor")).current_block_id).toBe(id);
    opened.push(id);
  }
  expect(opened.length).toBe((st.blockers ?? []).length);
});

test("UC7 Help and tooltips: ? opens the Guide at this step, Esc restores focus; three tooltips by Tab; Esc on a tooltip closes only it", async ({ page, request }) => {
  const q = await getQueue(request);
  await putCursor(request, q.items[0].block_id);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  const cardId = await currentCard(page).getAttribute("data-testid");
  await key(page, "?");
  const dlg = page.getByRole("dialog", { name: "Help" });
  await expect(dlg).toBeVisible();
  await expect(dlg.getByRole("tab", { name: "Guide" })).toHaveAttribute("aria-selected", "true");
  const step = dlg.locator("[data-guide-step='verify']");
  await expect(step, "the guide opens at the Verify step").toBeInViewport();
  await expect(dlg.locator("[data-guide-step='scope'] h3")).not.toBeInViewport();
  note("help-guide-verify", await step.innerText());
  await key(page, "Escape");
  await expect(dlg).toHaveCount(0);
  await expect(page.getByTestId(cardId!)).toBeFocused();
  // Tab through the screen: the first three controls with a tooltip
  const tip = page.getByRole("tooltip");
  const found: string[] = [];
  for (let i = 0; i < 80 && found.length < 3; i++) {
    await key(page, "Tab");
    if (await tip.isVisible().catch(() => false)) {
      const who = await activeDesc(page);
      const t = (await tip.innerText()).trim();
      if (!found.some((f) => f.startsWith(who))) found.push(`${who} => ${t}`);
      expect(t.length, `${who}: tooltip has text`).toBeGreaterThan(10);
    }
  }
  note("tooltips", found.join(" || "));
  expect(found.length, "three controls show a tooltip on keyboard focus").toBe(3);
  // Esc on the open tooltip closes only the tooltip
  if (!(await tip.isVisible())) {
    await page.getByTestId("act-approve").focus();
    await key(page, "Shift");
    await page.getByTestId("act-approve").focus();
  }
  const focusedBefore = await activeDesc(page);
  await expect(tip).toBeVisible();
  await key(page, "Escape");
  await expect(tip).toHaveCount(0);
  await expect(page).toHaveURL(/\/verify$/);
  expect(await activeDesc(page), "focus stays where it was").toBe(focusedBefore);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // a hover tooltip open behind Help does not take Help's Esc, and Help's Esc does not leave the screen
  await currentCard(page).focus();
  await page.getByTestId("act-approve").hover();
  await expect(tip).toBeVisible({ timeout: 3000 });
  await key(page, "?");
  await expect(dlg).toBeVisible();
  await key(page, "Escape");
  await expect(dlg, "one Esc closes Help even with a hover tooltip open").toHaveCount(0);
  await expect(page).toHaveURL(/\/verify$/);
  await expect(currentCard(page)).toBeFocused();
});

test("UC8 copy scan on every screen: no exclamation marks, em dashes, bare numbers or unexplained jargon", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const offenders: string[] = [];
  const jargonNotes: string[] = [];
  const scan = async (label: string, mainPath: boolean): Promise<void> => {
    const res = await page.evaluate(() => {
      const root = document.body.cloneNode(true) as HTMLElement;
      // the manual's words (block text, readings, previews, titles, ids) are data, not app copy
      root
        .querySelectorAll(
          "[data-testid=block-text],[data-testid=diff-view],[data-zone=source],textarea,[data-testid=row],[data-testid=doc-heading],[data-testid^=card-],[data-testid=blocker-link],[data-testid=provenance],.manual-text,[data-testid=parser-compare] dd,.font-mono",
        )
        .forEach((n) => n.remove());
      const t = root.innerText ?? root.textContent ?? "";
      const out: string[] = [];
      const jar: string[] = [];
      if (/!/.test(t)) out.push(`exclamation: ${(t.match(/.{0,30}!.{0,20}/) ?? [""])[0]}`);
      if (/—/.test(t)) out.push(`em dash: ${(t.match(/.{0,30}—.{0,20}/) ?? [""])[0]}`);
      for (const w of ["phash", "ocr_alt", "textlayer", "stale_doc", "combiner"]) {
        const i = t.toLowerCase().indexOf(w);
        if (i >= 0) jar.push(`${w}: "${t.slice(Math.max(0, i - 40), i + 40).replace(/\s+/g, " ")}"`);
      }
      for (const m of t.matchAll(/cohesion/gi)) {
        const ctx = t.slice(Math.max(0, m.index! - 120), m.index! + 120);
        if (!/subjects/i.test(ctx)) jar.push(`cohesion without "subjects": "${ctx.replace(/\s+/g, " ").slice(80, 180)}"`);
      }
      // the technical lines in mono that root removed: scan them separately, they are on screen too
      const mono = Array.from(document.querySelectorAll<HTMLElement>(".font-mono"))
        .filter((e) => e.offsetParent !== null && !e.closest("[data-testid^=card-],[data-testid=blocker-link],[data-testid=block-id],kbd"))
        .map((e) => e.innerText);
      for (const s of mono) for (const w of ["ocr_alt", "textlayer", "stale_doc", "phash", "combiner"]) if (s.includes(w)) jar.push(`${w} (scorer detail line): "${s.slice(0, 90)}"`);
      // bare numbers with nothing that names them
      document.querySelectorAll<HTMLElement>("body *").forEach((e) => {
        if (e.children.length || e.offsetParent === null) return;
        if (e.closest("[data-testid=block-text],[data-testid=diff-view],[data-zone=source],kbd,.manual-text,[data-testid=parser-compare],textarea,[aria-hidden=true]")) return;
        const s = (e.textContent ?? "").trim();
        if (!/^[+-]?\d+([.,]\d+)?%?$/.test(s)) return;
        const own = `${e.getAttribute("aria-label") ?? ""} ${e.getAttribute("title") ?? ""}`;
        let ctx = "";
        for (let p: HTMLElement | null = e.parentElement, k = 0; p && k < 2; p = p.parentElement, k++) ctx = p.textContent ?? "";
        const letters = ctx.replace(s, "").replace(/[^A-Za-z]/g, "").length;
        if (letters < 3 && !/[A-Za-z]{4,}/.test(own)) out.push(`bare number "${s}" in ${e.closest("[data-testid]")?.getAttribute("data-testid") ?? e.parentElement?.tagName}`);
      });
      return { out, jar };
    });
    for (const r of new Set(res.out)) offenders.push(`${label}: ${r}`);
    for (const j of new Set(res.jar)) (mainPath && !/scorer detail line/.test(j) ? offenders : jargonNotes).push(`${label}: ${j}`);
  };
  await setGuide(request, false);
  await page.goto("/scope");
  await waitForTree(page);
  await scan("scope with welcome", true);
  await page.getByRole("button", { name: "I have used this before" }).click();
  await scan("scope", true);
  // the Models panel, if collapsed, opened
  const q = await getQueue(request);
  const scanned = q.items.find((i) => i.doc_id === "scanned" && i.type !== "figure");
  for (const it of [q.items[0], scanned].filter(Boolean) as QueueItem[]) {
    await putCursor(request, it.block_id);
    await page.goto("/verify");
    await expect(currentCard(page)).toBeFocused();
    await expect(page.getByTestId("block-id")).toHaveText(it.block_id);
    await scan(`verify ${it.doc_id}`, true);
    await page.getByTestId("view-diff").click().catch(() => undefined);
    await scan(`verify diff ${it.doc_id}`, true);
  }
  await key(page, "f");
  await expect(page.getByRole("dialog", { name: "Flag block" })).toBeVisible();
  await scan("flag dialog", true);
  await key(page, "Escape");
  await page.goto("/agent");
  await expect(page.getByTestId("agent-flags")).toBeVisible();
  await scan("agent", true);
  await page.goto("/export");
  await expect(page.getByTestId("export-screen")).toBeVisible();
  await scan("export", true);
  await key(page, "?");
  const dlg = page.getByRole("dialog", { name: "Help" });
  await expect(dlg).toBeVisible();
  for (const tab of ["Guide", "Keyboard shortcuts", "Glossary"]) {
    await dlg.getByRole("tab", { name: tab }).click();
    await scan(`help ${tab}`, false);
  }
  await key(page, "Escape");
  note("jargon-notes", jargonNotes.join(" || ") || "none");
  expect(offenders, offenders.join("\n")).toEqual([]);
});

// ---------------------------------------------------------------------------------------------------------------
// Reader's pass: screenshots only, judged by a person. Opt-in so the UC suite stays a pass/fail check.
test("UCR reader's pass screenshots at 1440x900", async ({ page, request }) => {
  test.skip(!process.env.UX_READER, "set UX_READER=1 to take the reader's pass screenshots");
  const dir = process.env.UX_SHOTS ?? "e2e/artifacts/ux-craft";
  fs.mkdirSync(dir, { recursive: true });
  const shot = async (name: string, full = false): Promise<void> => {
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${dir}/${name}.png`, fullPage: full });
  };
  const texts: string[] = [];
  const grab = async (name: string): Promise<void> => {
    texts.push(`=== ${name}\n${await page.evaluate(() => document.body.innerText)}`);
  };
  await page.setViewportSize({ width: 1440, height: 900 });
  await resetSelection(request);
  await putCursor(request, null);
  await setGuide(request, false);
  await page.goto("/scope");
  await waitForTree(page);
  await shot("01-scope-first-run");
  await grab("scope-first-run");
  await shot("01b-scope-first-run-full", true);
  await page.getByRole("button", { name: "Start with step 1" }).click();
  await shot("02-scope-after-welcome");
  await grab("scope");
  await page.goto("/agent");
  await expect(page.getByTestId("agent-flags")).toBeVisible();
  await shot("03-agent-empty");
  await grab("agent-empty");
  await page.goto("/export");
  await expect(page.getByTestId("export-screen")).toBeVisible();
  await shot("04-export-locked-before-review");
  await shot("04b-export-locked-full", true);
  await grab("export");
  await page.goto("/scope");
  await waitForTree(page);
  await page.getByRole("button", { name: /Confirm scope and go to Verify/ }).click();
  await expect(currentCard(page)).toBeFocused();
  await expect(page.getByTestId("page-strip")).toBeVisible();
  await shot("05-verify-first-block");
  await grab("verify-first");
  await key(page, "z");
  await shot("06-verify-whole-page");
  await key(page, "z");
  await key(page, "t");
  await shot("07-verify-diff");
  await key(page, "t");
  await key(page, "e");
  await shot("08-verify-editing");
  await key(page, "Escape");
  await key(page, "f");
  await shot("09-flag-dialog");
  await key(page, "1");
  await key(page, "Enter");
  await expect(currentCard(page)).toBeFocused();
  // a scanned block with two readings
  const q = await getQueue(request);
  for (const it of q.items.filter((i) => i.doc_id === "scanned").slice(0, 60)) {
    const d = await getDetail(request, it.block_id);
    if ((d.why ?? []).some((w) => w.name === "parser_agreement" && (w.value ?? 1) < 1)) {
      await putCursor(request, it.block_id);
      break;
    }
  }
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await expect(page.getByTestId("page-strip")).toBeVisible();
  await shot("10-verify-scanned");
  await grab("verify-scanned");
  await page.locator("[data-testid=evidence]").evaluate((e) => e.scrollIntoView());
  await shot("10b-verify-scanned-evidence");
  await page.getByRole("region", { name: "Extracted text" }).evaluate((e) => (e.scrollTop = e.scrollHeight));
  await shot("10c-verify-scanned-evidence-end");
  await key(page, "?");
  await shot("11-help-guide");
  await page.getByRole("dialog", { name: "Help" }).getByRole("tab", { name: "Glossary" }).click();
  await shot("12-help-glossary");
  await key(page, "Escape");
  await page.goto("/agent");
  await expect(page.getByTestId("agent-flag").first()).toBeVisible();
  await shot("13-agent-one-flag");
  await grab("agent-flag");
  await page.goto("/export");
  await shot("14-export-locked-after-flag");
  await page.setViewportSize({ width: 720, height: 900 });
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await shot("15-verify-720x900");
  await page.setViewportSize({ width: 720, height: 450 });
  await shot("16-verify-720x450");
  await page.goto("/scope");
  await waitForTree(page);
  await shot("17-scope-720x450");
  fs.writeFileSync(`${dir}/screens.txt`, texts.join("\n\n"));
});
