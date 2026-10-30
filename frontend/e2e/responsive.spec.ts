// Fluid layout (design 13 section 9): the layout is a function of the window's width and height, checked at every
// target size and at two browser zooms. Zoom is emulated as the browser does it: the CSS viewport shrinks and the
// device pixel ratio grows (200 percent on a 1440x900 laptop is 720x450 CSS px at 2x; 150 percent on 1920x1080 is
// 1280x720 at 1.5x). Each size opens Scope, Verify (a text block with evidence, a page image and a figure in its
// article) and Export, and asserts: no horizontal page scroll; the step rail docked or the bottom sheet present;
// Scope's selection counts on screen; Verify's page strip above the text, the text's first lines between the strip and
// the action bar, the action bar in view, the text 45 to 90 characters wide; the evidence beside or below the text by
// width; Export in two columns on wide screens. A JSON line per screen records the measured layout.
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { BlockDetail, FigureRailItem, QueuePage } from "../src/api/schema";
import { api, waitForTree, waitJobsIdle } from "./helpers";

test.setTimeout(180_000);

interface Size {
  name: string;
  w: number;
  h: number;
  dpr: number;
}
const SIZES: Size[] = [
  { name: "720x450", w: 720, h: 450, dpr: 1 },
  { name: "1024x768", w: 1024, h: 768, dpr: 1 },
  { name: "1100x700", w: 1100, h: 700, dpr: 1 },
  { name: "1366x768", w: 1366, h: 768, dpr: 1 },
  { name: "1440x900", w: 1440, h: 900, dpr: 1 },
  { name: "1920x1080", w: 1920, h: 1080, dpr: 1 },
  { name: "2560x1440", w: 2560, h: 1440, dpr: 1 },
  { name: "1440x900 at 200 percent", w: 720, h: 450, dpr: 2 },
  { name: "1920x1080 at 150 percent", w: 1280, h: 720, dpr: 1.5 },
];

// the width thresholds of design 13 section 9.2, in CSS px (tailwind.config.js screens)
const WIDE = 1100; // the step rail docks on the left; Scope's summary sits beside the list
const EXPORT_TWO = 1280; // Export's gate and its overrides side by side
const SPLIT = 1340; // Verify's evidence beside the text
const SCOPE_THREE = 1800; // Scope's sources in their own column
const VAST = 2400; // Verify's whole page in its own column

/** A queued text block with evidence, a page image and a box, in an article with at least one attached figure. */
let target: string | null = null;
async function findTarget(request: APIRequestContext): Promise<string> {
  if (target) return target;
  const a = api(request);
  const q = await a.get<QueuePage>("/api/verify/queue?limit=2000");
  const items = [...q.items.filter((i) => i.doc_id === "figures"), ...q.items.filter((i) => i.doc_id !== "figures")];
  for (const it of items.slice(0, 160)) {
    if (it.type === "figure") continue;
    const d = await a.get<BlockDetail>(`/api/verify/blocks/${it.block_id}`);
    if (!d.page.render_url || d.page.width <= 0 || (d.block.bbox ?? []).length !== 4) continue;
    if (!(d.why ?? []).length) continue;
    const art = d.article_ids?.[0];
    if (!art) continue;
    const rail = await a.get<FigureRailItem[]>(`/api/articles/${art}/figures`);
    if (!rail.length) continue;
    target = it.block_id;
    return target;
  }
  throw new Error("no queued text block with evidence, a page image and a figure in its article");
}

type Box = { x: number; y: number; width: number; height: number };
const box = async (page: Page, testId: string): Promise<Box> => {
  const b = (await page.getByTestId(testId).count()) ? await page.getByTestId(testId).first().boundingBox() : null;
  expect.soft(b, `${testId} has a box`).not.toBeNull();
  return b ?? { x: 0, y: 0, width: 0, height: 0 };
};

async function noPageScrollX(page: Page, what: string): Promise<void> {
  const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  expect.soft(m.sw, `${what}: no horizontal page scroll (scrollWidth ${m.sw}, clientWidth ${m.cw})`).toBeLessThanOrEqual(m.cw);
}

/** What is at the top-centre of an element: "visible" when the element itself is hit there. */
async function uncovered(page: Page, sel: string): Promise<string> {
  return page.evaluate((s) => {
    const el = document.querySelector<HTMLElement>(s);
    if (!el) return "missing";
    const r = el.getBoundingClientRect();
    if (r.bottom <= 0 || r.top >= window.innerHeight) return `off screen (top ${Math.round(r.top)})`;
    const y = Math.min(r.top + Math.min(r.height, 24) / 2, window.innerHeight - 1);
    const hit = document.elementFromPoint(r.left + Math.min(r.width, 200) / 2, y) as HTMLElement | null;
    return hit && el.contains(hit)
      ? "visible"
      : `covered by ${hit?.closest("[data-testid]")?.getAttribute("data-testid") ?? hit?.closest("[aria-label]")?.getAttribute("aria-label") ?? hit?.tagName}`;
  }, sel);
}

/** The step rail: docked on the left from WIDE, a bottom sheet below it. */
async function railPresent(page: Page, s: Size, what: string): Promise<void> {
  const rail = page.getByRole("complementary", { name: "Getting started" });
  await expect.soft(rail, `${what}: step rail present`).toBeVisible();
  await expect.soft(rail.getByRole("navigation", { name: "Screens" }).getByRole("link"), `${what}: the four steps`).toHaveCount(4);
  const b = (await rail.boundingBox())!;
  if (s.w >= WIDE) expect.soft(b.x, `${what}: rail docked on the left`).toBeLessThan(4);
  else expect.soft(Math.round(b.y + b.height), `${what}: bottom sheet at the bottom of the window`).toBeGreaterThanOrEqual(s.h - 1);
}

for (const s of SIZES) {
  test.describe(s.name, () => {
    test.use({ viewport: { width: s.w, height: s.h }, deviceScaleFactor: s.dpr });

    test(`R ${s.name}: Scope, Verify and Export fit the window`, async ({ page, request }) => {
      const log: Record<string, unknown> = { size: s.name };
      await waitJobsIdle(request);

      // ---- Scope
      await page.goto("/scope");
      await waitForTree(page);
      await expect(page.getByTestId("sum-blocks")).toBeAttached();
      await noPageScrollX(page, "scope");
      await railPresent(page, s, "scope");
      const docked = s.w < WIDE;
      const blocksId = docked ? "dock-blocks" : "sum-blocks";
      const queuedId = docked ? "dock-queued" : "sum-queued";
      for (const id of [blocksId, queuedId]) {
        await expect.soft(page.getByTestId(id), `scope: ${id} on screen`).toBeInViewport({ ratio: 1 });
        expect.soft(await uncovered(page, `[data-testid=${id}]`), `scope: ${id} not covered`).toBe("visible");
      }
      if (docked) {
        // the dock repeats the summary's numbers, never its own
        await expect.soft(page.getByTestId("dock-blocks"), "scope: dock repeats the blocks").toHaveText((await page.getByTestId("sum-blocks").textContent())!.trim());
        await expect.soft(page.getByTestId("dock-queued"), "scope: dock repeats the review").toHaveText((await page.getByTestId("sum-queued").textContent())!.trim());
      }
      const tree = await box(page, "group-tree");
      const summary = await box(page, "selection-summary");
      const sources = (await page.getByRole("group", { name: "Sources panel" }).boundingBox())!;
      log.scope = { tree: Math.round(tree.width), summaryX: Math.round(summary.x), sourcesW: Math.round(sources.width) };
      if (s.w >= WIDE) expect.soft(summary.x, "scope: the summary beside the list").toBeGreaterThanOrEqual(tree.x + tree.width - 1);
      else expect.soft(summary.y, "scope: one column, the summary after the list").toBeGreaterThanOrEqual(tree.y + tree.height - 1);
      if (s.w >= SCOPE_THREE) {
        expect.soft(sources.x + sources.width, "scope: sources in their own column").toBeLessThanOrEqual(tree.x + 1);
        expect.soft(Math.abs(sources.y - tree.y), "scope: sources and topics start together").toBeLessThan(120);
      } else expect.soft(tree.y, "scope: sources above the topics").toBeGreaterThanOrEqual(sources.y + sources.height - 1);
      await page.screenshot({ path: `test-results/responsive-${s.name.replace(/ /g, "-")}-scope.png` });

      // ---- Verify
      const id = await findTarget(request);
      expect(
        (await request.put("/api/verify/cursor", { data: { sort: "worst_first", view_threshold: null, doc_filter: null, current_block_id: id, request_id: `resp-${Date.now()}` } })).ok(),
      ).toBe(true);
      await page.goto("/verify");
      await expect(page.getByTestId("block-id")).toHaveText(id);
      await expect(page.getByTestId("page-strip").locator("img")).toHaveCount(1);
      await waitJobsIdle(request);
      await expect.soft(page.getByTestId("jobs-bar"), "verify: no job bar, the screen at rest").toHaveCount(0);
      // the strip sizes itself from the image box once the layout has settled
      await expect.poll(async () => (await box(page, "page-strip")).height).toBeGreaterThan(30);
      await noPageScrollX(page, "verify");
      await railPresent(page, s, "verify");

      const approve = page.getByTestId("act-approve");
      await expect.soft(approve, "verify: Approve fully on screen").toBeInViewport({ ratio: 1 });
      const bar = (await page.getByRole("toolbar", { name: "Review actions" }).boundingBox())!;
      const strip = await box(page, "page-strip");
      const text = await box(page, "block-text");
      await expect.soft(page.getByTestId("page-strip"), "verify: page strip on screen").toBeInViewport();
      expect.soft(strip.y + strip.height, "verify: the page strip above the text").toBeLessThanOrEqual(text.y + 1);
      const lh = await page.getByTestId("block-text").evaluate((e) => parseFloat(getComputedStyle(e).lineHeight));
      const need = Math.min(text.height, 2 * lh);
      expect.soft(text.y + need, `verify: the text's first two lines above the action bar (text top ${Math.round(text.y)}, bar top ${Math.round(bar.y)})`).toBeLessThanOrEqual(bar.y + 1);
      expect.soft(text.y, "verify: text below the top of the window").toBeGreaterThanOrEqual(0);
      expect.soft(await uncovered(page, "[data-testid=block-text]"), "verify: text not covered").toBe("visible");
      expect.soft(await uncovered(page, "[data-testid=page-strip] > div"), "verify: strip not covered").toBe("visible");
      expect.soft(bar.y + bar.height, "verify: action bar inside the window").toBeLessThanOrEqual(s.h + 1);
      // the measure of the manual's text, in characters of its own face
      const ch = await page.getByTestId("block-text").evaluate((e) => {
        const p = document.createElement("span");
        p.style.cssText = "display:inline-block;width:1ch;height:0";
        e.appendChild(p);
        const w = p.getBoundingClientRect().width;
        p.remove();
        return e.getBoundingClientRect().width / w;
      });
      expect.soft(ch, `verify: text column ${ch.toFixed(1)} characters`).toBeGreaterThanOrEqual(45);
      expect.soft(ch, `verify: text column ${ch.toFixed(1)} characters`).toBeLessThanOrEqual(90);

      const evidence = await box(page, "evidence");
      if (s.w >= SPLIT) {
        expect.soft(evidence.x, "verify: evidence beside the text").toBeGreaterThanOrEqual(text.x + text.width - 1);
        expect.soft(evidence.y, "verify: evidence starts beside the text, not under it").toBeLessThan(text.y + text.height);
      } else expect.soft(evidence.y, "verify: evidence below the text").toBeGreaterThanOrEqual(text.y + text.height - 1);
      if (s.w >= VAST) {
        const col = page.getByTestId("page-column");
        await expect.soft(col, "verify: the whole page in its own column").toBeVisible();
        await expect.soft(col.getByRole("region", { name: "Source page" }), "verify: the page column holds the source page").toBeVisible();
        const c = (await col.boundingBox())!;
        expect.soft(c.x, "verify: page column right of the evidence").toBeGreaterThanOrEqual(evidence.x + evidence.width - 1);
        await expect.soft(col.getByRole("region", { name: "Source page" }), "verify: the whole page on screen").toBeInViewport();
      } else await expect.soft(page.getByTestId("page-column"), "verify: no page column below VAST").toHaveCount(0);
      const status = (await page.getByRole("region", { name: "Review status" }).boundingBox())!;
      const band = await box(page, "page-band");
      log.verify = {
        status: Math.round(status.height),
        band: Math.round(band.height),
        strip: Math.round(strip.height),
        textTop: Math.round(text.y),
        barTop: Math.round(bar.y),
        barH: Math.round(bar.height),
        ch: Math.round(ch),
        evidence: s.w >= SPLIT ? "beside" : "below",
      };
      await page.screenshot({ path: `test-results/responsive-${s.name.replace(/ /g, "-")}-verify.png` });
      // the evidence and the block's figures are reachable, and the action bar stays in view while they are read
      const fig = page.getByTestId("figure-rail").locator("[data-testid^='rail-item-']").first();
      await fig.scrollIntoViewIfNeeded();
      await expect.soft(fig, "verify: a figure in the rail").toBeInViewport();
      await expect.soft(approve, "verify: Approve still on screen beside the evidence").toBeInViewport({ ratio: 1 });
      await noPageScrollX(page, "verify, evidence scrolled into view");

      // ---- Export
      await page.goto("/export");
      await expect(page.getByTestId("export-locked").or(page.getByTestId("export-ready"))).toBeVisible();
      await noPageScrollX(page, "export");
      await railPresent(page, s, "export");
      const main = await box(page, "export-main");
      const screen = await box(page, "export-screen");
      const hasSide = (await page.getByTestId("export-side").count()) > 0;
      const side = hasSide ? await box(page, "export-side") : null;
      const right = Math.max(main.x + main.width, side ? side.x + side.width : 0);
      log.export = { screen: Math.round(screen.width), used: Math.round(right - screen.x), side: side ? Math.round(side.width) : 0 };
      const beside = s.w - (s.w >= WIDE ? (await page.getByRole("complementary", { name: "Getting started" }).boundingBox())!.width : 0);
      expect.soft(screen.width, "export: the screen spans the width beside the rail").toBeGreaterThanOrEqual(beside - 2);
      expect.soft(right - screen.x, "export: the columns use the width beside the rail").toBeGreaterThanOrEqual(screen.width * 0.85);
      if (side) {
        if (s.w >= EXPORT_TWO) {
          expect.soft(side.x, "export: the overrides beside the gate").toBeGreaterThanOrEqual(main.x + main.width - 1);
          expect.soft(Math.abs(side.y - main.y), "export: both columns start together").toBeLessThan(8);
        } else expect.soft(side.y, "export: one column").toBeGreaterThanOrEqual(main.y + main.height - 1);
      }
      await page.screenshot({ path: `test-results/responsive-${s.name.replace(/ /g, "-")}-export.png` });
      console.log(`LAYOUT ${JSON.stringify(log)}`);
    });
  });
}
