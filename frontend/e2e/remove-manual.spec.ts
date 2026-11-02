// Removing a manual (design 07 section 22, design 08 section 11). It deletes files, so it runs its own server over a
// fresh copy of the cached project (e2e/ownServer.ts); the shared 8765 and 8766 projects never see it.
import { expect, test } from "@playwright/test";
import type { SourceInfo, SourceRemoval } from "../src/api/schema";
import { stat, waitForTree, waitJobsIdle, type SelectionOut } from "./helpers";
import { startOwnServer, type OwnServer } from "./ownServer";

const PORT = 8767;
test.use({ baseURL: `http://127.0.0.1:${PORT}` });

let own: OwnServer | null = null;
test.beforeAll(async () => {
  test.setTimeout(180_000);
  own = await startOwnServer({ port: PORT });
});
test.afterAll(async () => {
  test.setTimeout(90_000);
  await own?.stop();
  own = null;
});

test("a manual removed from its card is gone from the list, the selection and the counts", async ({ page, request }) => {
  test.setTimeout(120_000);
  await waitJobsIdle(request);
  const before = (await (await request.get("/api/sources")).json()) as SourceInfo[];
  expect(before.length).toBeGreaterThan(1);
  const gone = before[before.length - 1];
  const preview = (await (await request.get(`/api/sources/${gone.slug}/removal`)).json()) as SourceRemoval;
  expect(preview.blocked_by).toBeNull();

  await page.goto("/scope");
  await waitForTree(page);
  const card = page.locator(`[data-testid=source-row][data-slug="${gone.slug}"]`);
  await card.getByTestId("source-remove").click();
  const dlg = page.getByTestId("remove-dialog");
  await expect(dlg).toBeVisible();
  await expect(dlg.getByRole("heading")).toHaveText(`Remove ${gone.filename}?`);
  // the server's counts, as the confirmation says them
  await expect(dlg.getByTestId("remove-body")).toContainText(`${preview.blocks} blocks`);
  await expect(dlg.getByRole("button", { name: "Keep it" })).toBeFocused();
  await dlg.getByTestId("remove-confirm").click();
  await expect(dlg).toHaveCount(0);
  await expect(card).toHaveCount(0);

  // the server agrees: no such manual, no block of it selected, the summary recounted
  const after = (await (await request.get("/api/sources")).json()) as SourceInfo[];
  expect(after.map((s) => s.slug)).toEqual(before.filter((s) => s.slug !== gone.slug).map((s) => s.slug));
  const sel = (await (await request.get("/api/scope/selection")).json()) as SelectionOut;
  expect(sel.selection.block_ids.filter((b) => b.startsWith(`b-${gone.slug}-`))).toEqual([]);
  expect(sel.summary.docs).toBe(after.length);
  await expect.poll(() => stat(page, "sum-blocks")).toBe(sel.summary.blocks);
  expect((await request.get(`/api/sources/${gone.slug}/removal`)).status()).toBe(404);
});
