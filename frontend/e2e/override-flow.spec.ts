// Second first-use report C2, C3 (design 11 sections 17 and 18): one click with one reason overrides every unflagged
// block, across the server's pages of 20 blockers, never the flagged one; the reason stays in its box; afterwards no
// screen calls the overridden blocks "to review": the rail, the next-step card, the Export lock and the Verify strip
// all read the gate's partition. The flag keeps its own decision, and only that unlocks the export.
//
// Records real overrides, so it runs its own server on 8767 over a copy of the cached e2e project (ownServer.ts); the
// shared server's gate, which other specs read, is never touched. The page is the built dist.
import { expect, test, type APIRequestContext } from "@playwright/test";
import type { ExportStatus } from "../src/api/schema";
import { startOwnServer, type OwnServer } from "./ownServer";

const PORT = 8767;
const BASE = `http://127.0.0.1:${PORT}`;
const BLOCKER_LIMIT = 20;

let own: OwnServer | null = null;
let api: APIRequestContext;

test.beforeAll(async () => {
  test.setTimeout(180_000);
  own = await startOwnServer({ port: PORT });
  api = own.api;
});

test.afterAll(async () => {
  test.setTimeout(90_000);
  await own?.stop();
  own = null;
});

const status = async (): Promise<ExportStatus> => (await (await api.get("/api/export/status")).json()) as ExportStatus;

test("OV1 one click overrides every unflagged block with one reason; nothing overridden is called 'to review'", async ({ page }) => {
  test.setTimeout(240_000);
  const before = await status();
  expect(before.counts, "the server reports the scope partition").toBeTruthy();
  expect(before.counts!.to_review, "the project needs more blockers than one page of the status lists").toBeGreaterThan(BLOCKER_LIMIT);
  expect(before.counts!.overridden).toBe(0);
  // a reviewer's flag on one queued block: it must stay out of every batch
  const flagged = before.blockers![1];
  const fr = await api.post("/api/verify/actions", {
    data: { kind: "flag", block_id: flagged, flag: { category: "wrong_text", note: "check the refill line" }, request_id: `ov1-flag-${Date.now()}` },
  });
  expect(fr.ok(), await fr.text()).toBeTruthy();
  const mid = await status();
  const n = mid.counts!.to_review;
  expect(n).toBe(before.counts!.to_review - 1);
  expect(mid.counts!.flagged).toBe(1);

  await page.goto(`${BASE}/export`);
  const form = page.getByTestId("override-form");
  await expect(form.getByTestId("override-submit")).toHaveText(`Override the remaining ${n} with this reason`);
  await expect(form.getByTestId("override-left-out")).toContainText("1 flagged block is left out");
  const reason = `pilot run, reviewed on paper ${Date.now()}`;
  await form.getByTestId("override-reason").fill(reason);
  await form.getByTestId("override-submit").click();
  // one click: progress to the end, the reason still in its box, nothing left for the button to do
  await expect(form.getByTestId("override-progress")).toHaveText(`Recorded ${n} of ${n}.`, { timeout: 120_000 });
  await expect(form.getByTestId("override-reason")).toHaveValue(reason);
  await expect(form.getByTestId("override-submit")).toBeDisabled();
  await expect(form.getByTestId("override-submit")).toHaveText("Nothing left to override");

  // the server: every unflagged block covered by one override with this reason, the flagged one by none
  const after = await status();
  expect(after.counts).toMatchObject({ to_review: 0, flagged: 1, blocking: 1, overridden: n });
  const overrides = after.overrides ?? [];
  expect(overrides).toHaveLength(n);
  expect(overrides.every((o) => o.reason === reason && o.flag_id == null && o.target_id)).toBe(true);
  expect(overrides.some((o) => o.target_id === flagged)).toBe(false);
  expect(new Set(overrides.map((o) => o.target_id)).size).toBe(n);
  expect((after.flag_blockers ?? []).map((f) => f.block_id)).toEqual([flagged]);

  // every place says the same: overridden, not "to review"
  await expect(page.getByTestId("export-reconcile")).toContainText(`+ ${n} overridden + 0 to review + 1 flagged`);
  await expect(page.getByTestId("reason-queued")).toHaveCount(0);
  await expect(page.locator("#step-state-verify")).toHaveText(new RegExp(`${n} overridden, not reviewed`));
  await expect(page.locator("#step-state-verify")).not.toHaveText(/to review/);
  await expect(page.getByTestId("next-step-text")).toHaveText("1 open flag still blocks the export. Export unlocks after that.");

  await page.goto(`${BASE}/verify`);
  await expect(page.getByTestId("cnt-queued")).toHaveText("0");
  await expect(page.getByTestId("cnt-overridden")).toHaveText(String(n));
  await expect(page.getByTestId("reconcile-review")).toContainText(`= 0 to review + ${n} overridden + `);
  await expect(page.getByTestId("reconcile-mismatch")).toHaveCount(0);

  // the flag's own decision is what unlocks the export
  await page.goto(`${BASE}/export`);
  const flagBox = page.getByTestId("flag-override");
  await flagBox.getByRole("textbox").fill("checked against the page");
  await flagBox.getByRole("button", { name: `Export ${flagged} despite its flag` }).click();
  await expect(page.getByTestId("export-ready")).toBeVisible();
  await expect(page.getByTestId("export-ready")).toContainText("Overrides cover every remaining block");
  await expect(page.locator("#step-state-export")).toHaveText(/Ready with an override/);
  expect((await status()).counts).toMatchObject({ to_review: 0, flagged: 0, blocking: 0, overridden: n + 1 });
});
