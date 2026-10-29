// Module 8 review fixes (selection durability, stale fetch ordering, focus). Needs the shared e2e server.
import { expect, test } from "@playwright/test";
import { clearSelection, getGroups, resetSelection, row, waitForTree, waitSettled, type SelectionOut } from "./helpers";

test.beforeEach(async ({ request }) => {
  await resetSelection(request);
  await clearSelection(request);
});

const serverBlocks = async (request: import("@playwright/test").APIRequestContext): Promise<number> =>
  ((await (await request.get("/api/scope/selection")).json()) as SelectionOut).summary.blocks;

async function firstTopic(request: import("@playwright/test").APIRequestContext) {
  const groups = await getGroups(request);
  return groups[0].groups.topics.find((t) => !t.is_unassigned)!;
}

test("FX1 click a topic then press 2 at once: the server has the blocks", async ({ page, request }) => {
  const topic = await firstTopic(request);
  await page.goto("/scope");
  await waitForTree(page);
  await row(page, topic.id).click();
  await page.keyboard.press("2");
  await expect(page).toHaveURL(/\/verify$/);
  await expect.poll(() => serverBlocks(request)).toBe(topic.block_count);
});

test("FX2 click a topic then reload within 150 ms: the server has the change", async ({ page, request }) => {
  const topic = await firstTopic(request);
  await page.goto("/scope");
  await waitForTree(page);
  await row(page, topic.id).click();
  await page.reload();
  await expect.poll(() => serverBlocks(request)).toBe(topic.block_count);
  await waitForTree(page);
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(topic.block_count));
});

test("FX3 a stale refetch answered after the save does not overwrite it", async ({ page, request }) => {
  const topic = await firstTopic(request);
  let polls = 0;
  await page.route(/\/api\/jobs\?.*status=/, (route) => {
    polls++;
    const job = { id: "j-x", kind: "run", plan: {}, status: "running", progress: 0.5, units_done: 1, units_total: 2, node: "group", doc: null, message: "", created_at: "2026-01-01T00:00:00Z" };
    return route.fulfill({ json: polls <= 2 ? [job] : [] });
  });
  await page.route("**/api/jobs/j-x", (route) =>
    route.fulfill({ json: { id: "j-x", kind: "run", plan: {}, status: "done", progress: 1, units_done: 2, units_total: 2, node: null, doc: null, message: "", created_at: "2026-01-01T00:00:00Z" } }),
  );
  let armed = false;
  let started!: () => void;
  const getStarted = new Promise<void>((r) => (started = r));
  await page.route("**/api/scope/selection", async (route) => {
    if (route.request().method() !== "GET" || !armed) return route.continue();
    armed = false;
    const res = await route.fetch(); // server state before the click
    started();
    await new Promise((r) => setTimeout(r, 1200));
    await route.fulfill({ response: res });
  });
  await page.goto("/scope");
  await waitForTree(page);
  armed = true;
  await getStarted;
  await row(page, topic.id).click();
  await page.waitForTimeout(2500);
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(topic.block_count));
  await expect(row(page, topic.id)).toHaveAttribute("data-check", "checked");
  expect(await serverBlocks(request)).toBe(topic.block_count);
});

test("FX4 focus stays in the tree after t and s", async ({ page }) => {
  await page.goto("/scope");
  await waitForTree(page);
  await expect(page.locator("[data-testid=row]:focus")).toBeVisible();
  await page.keyboard.press("t");
  await expect(page).toHaveURL(/view=structure/);
  await expect(page.locator("[data-zone=tree] [data-testid=row]:focus")).toHaveCount(1);
  await page.keyboard.press("s");
  await expect(page.getByRole("radio", { name: /per document/ })).toHaveAttribute("aria-checked", "true");
  await waitSettled(page);
  await expect(page.locator("[data-zone=tree] [data-testid=row]:focus")).toHaveCount(1);
  const cur = () => page.evaluate(() => document.activeElement?.getAttribute("data-group-id"));
  const before = await cur();
  await page.keyboard.press("j"); // still operable without a click
  expect(await cur()).not.toBe(before);
});
