// 200 percent zoom on a 1440x900 laptop is a 720x450 viewport (review M13 P1-2 and P1-3): the page strip and the
// extracted text must be on screen together, uncovered by the step sheet or the action bar, before and after each
// decision. A decision must not scroll the page back to the queue (the card takes focus without scrolling).
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { BlockDetail, Flag, JobInfo, QueuePage, ReviewActionOut } from "../src/api/schema";
import { api, waitJobsIdle } from "./helpers";

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
  // Z1 measures the screen at rest. A job that starts after the idle check above (CI: a previous test's detach landing
  // late) adds the job bar above Verify, which moves the text down under the sticky action bar at this size ("covered
  // by act-approve"). Wait for that state to be over explicitly rather than measuring a layout in motion.
  await waitJobsIdle(request);
  await expect(page.getByTestId("jobs-bar"), "no job bar: the screen at rest").toHaveCount(0);

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

// Review 2 M1 (2026-10-30): the case Z1 leaves out. With a job running the job bar sits above Verify, and a flagged block
// opened from the Agent screen adds the flag notice: on a short window both fold to one line, the page strip gives the
// bar's height back, and the strip and the text are still on screen together, uncovered.
let z2Flag: string | null = null;
test.afterEach(async ({ request }) => {
  if (!z2Flag) return;
  const a = api(request);
  for (const f of (await a.get<Flag[]>("/api/flags")).filter((x) => x.id === z2Flag && x.status === "open"))
    await a.post(`/api/flags/${f.id}/resolve`, { resolution: "e2e cleanup", request_id: `z2-res-${Date.now()}` });
  z2Flag = null;
});

test("Z2 720x450 with a job running and a flagged block opened from Agent: strip and text uncovered", async ({ page, request }) => {
  await waitJobsIdle(request);
  const a = api(request);
  const q = await getQueue(request);
  // a text block with a page image and a box, away from the top of the queue
  let target: QueuePage["items"][number] | null = null;
  for (let i = 2; i < Math.min(40, q.items.length) && !target; i++) {
    const it = q.items[i];
    if (it.type === "figure") continue;
    const d = await getDetail(request, it.block_id);
    if (d.page.render_url && d.page.width > 0 && (d.block.bbox ?? []).length === 4) target = it;
  }
  expect(target, "a text block with a page image").not.toBeNull();
  const id = target!.block_id;
  const out = await a.post<ReviewActionOut>("/api/verify/actions", {
    kind: "flag",
    block_id: id,
    flag: { category: "wrong_text", note: "e2e Z2: the torque value on this line looks wrong against the page" },
    request_id: rid(),
  });
  z2Flag = out.flag?.id ?? null;
  expect(z2Flag).toBeTruthy();

  // a running job with a long step sentence, served to this page only: a real job would end before the layout is read
  const job: JobInfo = {
    id: "job-z2",
    kind: "run",
    plan: { to: "score2", allow_reparse: false },
    status: "running",
    progress: 0.42,
    units_done: 7,
    units_total: 12,
    node: "clean",
    doc: target!.doc_id,
    step_done: 41,
    step_total: 187,
    step_unit: "block",
    message: null,
    created_at: new Date().toISOString(),
  };
  await page.route(/\/api\/jobs\?/, (route) => (route.request().method() === "GET" ? route.fulfill({ json: [job] }) : route.continue()));

  await page.setViewportSize({ width: 720, height: 450 });
  await page.goto("/agent");
  const card = page.getByTestId("agent-flag").filter({ hasText: id });
  const link = card.getByRole("link", { name: `Open ${id} in Verify` });
  await expect(link).toBeVisible();
  // the reviewer has scrolled the Agent screen (a long flag list): Verify must still open at its top, with the strip on
  // screen (design 13 section 9.3; the full e2e run once landed mid-page because the window kept the Agent scroll)
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  expect(await page.evaluate(() => window.scrollY), "the Agent screen is scrolled").toBeGreaterThan(0);
  await link.evaluate((a: HTMLElement) => a.click());
  await expect(page).toHaveURL(/\/verify$/);
  await expect(page.getByTestId("block-id")).toHaveText(id);
  expect(await page.evaluate(() => window.scrollY), "Verify opens at its top").toBe(0);

  const bar = page.getByTestId("jobs-bar");
  const notice = page.getByTestId("verify-flag");
  await expect(bar).toBeVisible();
  await expect(notice).toBeVisible();
  const strip = page.getByTestId("page-strip");
  const text = page.getByTestId("block-text");
  await expect(strip).toBeVisible();
  await expect(strip.locator("img")).toHaveCount(1);
  await expect(strip).toBeInViewport();
  await expect(text).toBeInViewport();
  expect(await uncovered(page, "[data-testid=page-strip] > div"), "strip not covered").toBe("visible");
  expect(await uncovered(page, "[data-testid=block-text]"), "text not covered").toBe("visible");
  // the strip starts below the sticky bar, and the text above the sticky action bar
  const barBottom = (await bar.boundingBox())!.y + (await bar.boundingBox())!.height;
  expect((await strip.boundingBox())!.y).toBeGreaterThanOrEqual(barBottom - 1);
  const action = (await page.getByTestId("act-approve").boundingBox())!;
  expect((await text.boundingBox())!.y).toBeLessThan(action.y);

  await expect(bar.getByTestId("job-step")).toHaveAttribute("title", /^Step 8 of 12: Cleaning up the text of .+, 41 of 187 blocks$/);
  await expect(notice).toBeVisible();
  await expect(notice.getByTestId("verify-flag-summary")).toContainText("Flagged: Wrong text");
  // each band is one line on this window, and the rest of the flag is one button away
  expect((await bar.boundingBox())!.height, "the job bar is one line").toBeLessThanOrEqual(44);
  expect((await notice.boundingBox())!.height, "the flag notice is one line").toBeLessThanOrEqual(40);
  const details = notice.getByRole("button", { name: "Details" });
  await expect(details).toHaveAttribute("aria-expanded", "false");

  // the details open on request and fold again
  await details.click();
  await expect(notice.getByRole("button", { name: "Fewer details" })).toHaveAttribute("aria-expanded", "true");
  await expect(notice).toContainText("A flag locks the export until you approve or edit the block in Verify");
  await notice.getByRole("button", { name: "Fewer details" }).click();
  await page.screenshot({ path: "test-results/zoom-720x450-job-flag.png" });
  await page.unroute(/\/api\/jobs\?/);
});
