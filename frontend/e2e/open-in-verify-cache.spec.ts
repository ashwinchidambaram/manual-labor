// F11 (design 09 section 11): Verify -> Export -> a blocker -> Verify, all in-app (no reload). The Verify queue cached
// from the first visit must not be applied with its old cursor: the card that opens is the blocker that was clicked.
import { expect, test } from "@playwright/test";
import { api, resetSelection, waitJobsIdle } from "./helpers";
import type { ExportStatus } from "../src/api/schema";

test("a blocker opened from Export after Verify was open lands on that block, not the cached cursor", async ({ page, request }) => {
  const a = api(request);
  await resetSelection(request);
  await waitJobsIdle(request);
  const st = await a.get<ExportStatus>("/api/export/status");
  const blockers = st.blockers ?? [];
  expect(blockers.length).toBeGreaterThan(2);
  const first = blockers[0];
  const target = blockers[2];

  await a.put("/api/verify/cursor", { sort: "by_page", view_threshold: null, doc_filter: null, current_block_id: first, request_id: `e2e-cur-${Date.now()}` });
  await page.goto("/verify");
  await expect(page.getByTestId(`card-${first}`)).toHaveAttribute("aria-current", "true");

  await page.keyboard.press("4"); // in-app: the queue snapshot stays in the page's cache
  await expect(page).toHaveURL(/\/export$/);
  const link = page.getByRole("link", { name: `Open ${target} in Verify` }).or(page.getByRole("button", { name: `Open ${target} in Verify` }));
  await link.first().click();
  await expect(page).toHaveURL(/\/verify$/);
  await expect(page.getByTestId(`card-${target}`)).toHaveAttribute("aria-current", "true");
  await page.waitForTimeout(1000); // a late stale snapshot would move it back
  await expect(page.getByTestId(`card-${target}`)).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("block-id")).toHaveText(target);
  expect((await a.get<{ current_block_id: string | null }>("/api/verify/cursor")).current_block_id).toBe(target);
});
