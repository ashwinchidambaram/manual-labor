// 200 percent zoom on a 1440x900 laptop is a 720x450 viewport (review M13 P1-2 and P1-3): the page strip and the
// extracted text must be on screen together, uncovered by the step sheet or the action bar, before and after each
// decision. A decision must not scroll the page back to the queue (the card takes focus without scrolling).
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { BlockDetail, QueuePage } from "../src/api/schema";
import { waitJobsIdle } from "./helpers";

test.setTimeout(180_000);

const rid = (): string => `zoom-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const currentCard = (page: Page) => page.locator("[data-testid^='card-'][aria-current='true']");
const getQueue = async (request: APIRequestContext): Promise<QueuePage> => (await request.get("/api/verify/queue?limit=2000")).json();
const getDetail = async (request: APIRequestContext, id: string): Promise<BlockDetail> => (await request.get(`/api/verify/blocks/${id}`)).json();

/** What is at the top-centre of an element: "visible" when the element itself is hit there. */
async function uncovered(page: Page, sel: string): Promise<string> {
  return page.evaluate((s) => {
    const el = document.querySelector<HTMLElement>(s);
    if (!el) return "missing";
    const r = el.getBoundingClientRect();
    if (r.bottom <= 0 || r.top >= window.innerHeight) return `off screen (top ${Math.round(r.top)})`;
    const y = Math.min(r.top + Math.min(r.height, 24) / 2, window.innerHeight - 1);
    const hit = document.elementFromPoint(r.left + Math.min(r.width, 200) / 2, y) as HTMLElement | null;
    return hit && el.contains(hit) ? "visible" : `covered by ${hit?.closest("[data-testid],[aria-label]")?.getAttribute("data-testid") ?? hit?.closest("[aria-label]")?.getAttribute("aria-label") ?? hit?.tagName}`;
  }, sel);
}

test("Z1 720x450: page strip and text on screen together, uncovered, through two approves", async ({ page, request }) => {
  await waitJobsIdle(request);
  const q = await getQueue(request);
  // three text blocks in a row that each have a page image and a box: the start and the next two after approving
  const ok = async (i: number): Promise<boolean> => {
    const it = q.items[i];
    if (!it || it.type === "figure") return false;
    const d = await getDetail(request, it.block_id);
    return !!d.page.render_url && d.page.width > 0 && (d.block.bbox ?? []).length === 4;
  };
  let start = -1;
  for (let i = 0; i < Math.min(40, q.items.length - 2) && start < 0; i++) if ((await ok(i)) && (await ok(i + 1)) && (await ok(i + 2))) start = i;
  expect(start, "three text blocks with page images in a row").toBeGreaterThanOrEqual(0);
  const put = await request.put("/api/verify/cursor", {
    data: { sort: "worst_first", view_threshold: null, doc_filter: null, current_block_id: q.items[start].block_id, request_id: rid() },
  });
  expect(put.ok()).toBe(true);

  await page.setViewportSize({ width: 720, height: 450 });
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(q.items[start].block_id);
  await expect(currentCard(page)).toBeFocused();

  const both = async (what: string): Promise<void> => {
    const strip = page.getByTestId("page-strip");
    const text = page.getByTestId("block-text");
    await expect(strip, `${what}: strip shown`).toBeVisible();
    await expect(strip.locator("img"), `${what}: page image`).toHaveCount(1);
    await expect(strip, `${what}: strip in the viewport`).toBeInViewport();
    await expect(text, `${what}: text in the viewport`).toBeInViewport();
    expect(await uncovered(page, "[data-testid=page-strip] > div"), `${what}: strip not covered`).toBe("visible");
    expect(await uncovered(page, "[data-testid=block-text]"), `${what}: text not covered`).toBe("visible");
  };
  await both("start");
  for (const n of [1, 2]) {
    const id = (await page.getByTestId("block-id").innerText()).trim();
    const scrollBefore = await page.evaluate(() => window.scrollY);
    await page.keyboard.press("a");
    await expect(page.getByTestId("block-id"), `approve ${n}: moved on`).not.toHaveText(id);
    await expect(currentCard(page), `approve ${n}: focus on the current card`).toBeFocused();
    expect(await page.evaluate(() => window.scrollY), `approve ${n}: the page did not scroll`).toBe(scrollBefore);
    await both(`after approve ${n}`);
  }
  // the folded queue still says where you are, and the step sheet still shows the four steps
  await expect(page.locator("[data-zone='queue'] > p").first()).toContainText(/Block \d+ of \d+ in this list/);
  const sheet = page.getByRole("complementary", { name: "Getting started" });
  await expect(sheet.getByRole("navigation", { name: "Screens" }).getByRole("link")).toHaveCount(4);
  await page.screenshot({ path: "test-results/zoom-720x450.png" });
});
