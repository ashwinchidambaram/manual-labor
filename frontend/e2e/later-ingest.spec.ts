// Defect 1 of the first-use report (design 08 section 10): a manual added after the reviewer touched the selection
// arrives selected. The spec adds a fourth document, so it runs its own server over a fresh copy of the cached project
// (e2e/ownServer.ts): the shared 8765 and 8766 projects never see it, and a CI retry starts from the cache again instead
// of from a project that already holds "manual" (review 2 L12).
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { getGroups, putOp, resetSelection, row, stat, waitForTree, waitJobsIdle, waitSettled, type SelectionOut } from "./helpers";
import { startOwnServer, type OwnServer } from "./ownServer";

const PORT = 8767;
test.use({ baseURL: `http://127.0.0.1:${PORT}` });

const DOCX = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../tests/fixtures/manual.docx");

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

test("a manual added after the selection was touched enters selected, and the counts include it", async ({ page, request }) => {
  test.setTimeout(240_000);
  await resetSelection(request);
  const before = await getGroups(request);
  expect(before.map((d) => d.doc_id)).not.toContain("manual");
  const first = before[0];
  const dropped = first.groups.topics.find((t) => !t.is_unassigned && t.block_ids.length)!;

  await page.goto("/scope");
  await waitForTree(page);
  // the reviewer touches the selection: one topic cleared
  await row(page, dropped.id).click();
  await expect(row(page, dropped.id)).toHaveAttribute("data-check", "unchecked");
  await waitSettled(page);

  // then adds a manual through the screen
  await page.getByTestId("upload-input").setInputFiles(DOCX);
  await expect.poll(async () => (await getGroups(request)).some((d) => d.doc_id === "manual"), { timeout: 180_000 }).toBe(true);
  await waitJobsIdle(request);

  // the server: every selectable block of the new manual is selected; the reviewer's choice is kept
  const sel = (await (await request.get("/api/scope/selection")).json()) as SelectionOut;
  const manual = (await getGroups(request)).find((d) => d.doc_id === "manual")!;
  const manualIds = manual.groups.structure.flatMap((g) => g.block_ids);
  expect(manualIds.length).toBeGreaterThan(0);
  const chosen = new Set(sel.selection.block_ids);
  expect(manualIds.filter((b) => !chosen.has(b))).toEqual([]);
  expect(dropped.block_ids.filter((b) => chosen.has(b))).toEqual([]);
  expect(sel.summary.docs).toBe(before.length + 1);

  // the screen: the new manual's topics are ticked, nothing says it is left out, and the counts equal the server's
  const heading = page.locator('[data-testid=doc-heading][data-doc="manual"]');
  await expect(heading).toBeVisible({ timeout: 30_000 });
  await expect(heading.getByTestId("doc-not-selected")).toHaveCount(0);
  for (const t of manual.groups.topics.filter((x) => x.block_ids.length)) await expect(row(page, t.id)).toHaveAttribute("data-check", "checked");
  await expect(page.getByTestId("sum-docs")).toHaveText(String(sel.summary.docs));
  await expect(page.getByTestId("sum-blocks")).toHaveText(String(sel.summary.blocks));
  const server = (await (await request.get("/api/scope/summary")).json()) as SelectionOut["summary"];
  expect(await stat(page, "sum-blocks")).toBe(server.blocks);

  // a manual the reviewer clears is told apart from a new one: it stays cleared, and its heading says so
  await putOp(request, { op: "deselect", block_ids: manualIds });
  await page.reload();
  await waitForTree(page);
  await expect(heading.getByTestId("doc-not-selected")).toContainText(`Not in your selection: ${manualIds.length} blocks`);
});
