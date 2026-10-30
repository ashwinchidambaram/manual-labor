// Defect 2 of the first-use report and F11 (design 09 section 11): "open in Verify" from the Agent screen, after Verify
// was open, lands on the flagged block and shows the flag with the agent's outcome; the flag card counts failed passes;
// the job log reads as sentences.
import { expect, test } from "@playwright/test";
import { api, resetSelection, waitJobsIdle } from "./helpers";
import type { AgentItemView, Flag, QueuePage, ReviewActionOut } from "../src/api/schema";

let flagged: string | null = null;

test.afterEach(async ({ request }) => {
  // leave no open flag behind for the other specs: approving the block resolves it
  if (!flagged) return;
  const a = api(request);
  const open = (await a.get<Flag[]>("/api/flags")).filter((f) => f.target_id === flagged);
  for (const f of open) await a.post(`/api/flags/${f.id}/resolve`, { resolution: "e2e cleanup", request_id: `e2e-res-${Date.now()}-${f.id}` });
  flagged = null;
});

test("the flagged block opens in Verify from the Agent screen, with its agent outcome", async ({ page, request }) => {
  test.setTimeout(180_000);
  const a = api(request);
  await resetSelection(request);
  await waitJobsIdle(request);
  const q = await a.get<QueuePage>("/api/verify/queue?limit=50&sort=by_page");
  expect(q.items.length).toBeGreaterThan(2);
  const target = q.items[2].block_id;
  const first = q.items[0].block_id;

  // Verify is opened first (its queue is now cached in the page), on another block
  await a.put("/api/verify/cursor", { sort: "by_page", view_threshold: null, doc_filter: null, current_block_id: first, request_id: `e2e-cur-${Date.now()}` });
  await page.goto("/verify");
  await expect(page.getByTestId(`card-${first}`)).toHaveAttribute("aria-current", "true");

  // the block is flagged, and the agent pass runs on it (the mock agent model may or may not propose)
  const out = await a.post<ReviewActionOut>("/api/verify/actions", { kind: "flag", block_id: target, flag: { category: "wrong_text", note: "e2e: torque looks wrong" }, request_id: `e2e-flag-${Date.now()}` });
  flagged = target;
  expect(out.flag?.id).toBeTruthy();
  await a.post("/api/agent/run", { request_id: `e2e-agent-${Date.now()}` });
  await waitJobsIdle(request);
  const item = (await a.get<AgentItemView[]>("/api/agent/items")).find((i) => i.flag.id === out.flag!.id)!;

  // in-app navigation (no reload): the Agent screen, then the block's link
  await page.keyboard.press("3");
  await expect(page).toHaveURL(/\/agent$/);
  const card = page.getByTestId("agent-flag").filter({ hasText: target });
  await expect(card).toBeVisible();
  if (item.pending_proposal_id === null) {
    await expect(card.getByTestId("agent-flag-tried")).toContainText("tried once");
    await expect(card.getByTestId("agent-flag-tried")).not.toContainText("not tried yet");
  }
  await card.getByRole("link", { name: `Open ${target} in Verify` }).click();
  await expect(page).toHaveURL(/\/verify$/);
  await expect(page.getByTestId(`card-${target}`)).toHaveAttribute("aria-current", "true");
  await page.waitForTimeout(1000);
  await expect(page.getByTestId(`card-${target}`)).toHaveAttribute("aria-current", "true");
  const notice = page.getByTestId("verify-flag");
  await expect(notice).toContainText("Wrong text");
  await expect(notice).toContainText("e2e: torque looks wrong");
  await expect(notice.getByTestId("verify-flag-agent")).toContainText(item.pending_proposal_id ? "proposal is waiting" : "tried once");
  // and the server agrees about where the reviewer is
  const cur = await a.get<{ current_block_id: string | null }>("/api/verify/cursor");
  expect(cur.current_block_id).toBe(target);
});
