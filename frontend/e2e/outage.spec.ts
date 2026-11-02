// First-time user run 5 (design 07 section 20): with the model service down, a reading job failed with "group
// pump-service-tables: stage failed" and the first banner had no Retry. The server side (preflight, records) is covered
// by pytest; here the jobs routes are stubbed so the shared project is never touched: a reading job fails with the
// provider-unreachable code, the banner says what to do in one sentence, and its Retry posts Scope's re-run plan.
import { expect, test, type Route } from "@playwright/test";
import { waitForTree } from "./helpers";

const DOWN = "Ollama is not running at http://127.0.0.1:11434. Start it (`ollama serve`) and press Retry.";
const PLAN = { to: "group", docs: null, force: [], allow_reparse: false };
const job = (status: string, extra: Record<string, unknown> = {}) => ({
  id: "job-990001",
  kind: "ingest_run",
  plan: PLAN,
  status,
  progress: 0,
  units_done: 0,
  units_total: 0,
  node: null,
  doc: null,
  files: ["pump-service-tables.pdf"],
  created_at: "2026-11-02T11:45:08Z",
  ...extra,
});

test("a reading job that met a stopped model service says so and can be retried", async ({ page }) => {
  let listed = 0;
  const posted: unknown[] = [];
  // the active-jobs list: the job once (running), then never again, so the bar reads its final record
  await page.route(/\/api\/jobs\?/, (route: Route) => route.fulfill({ json: listed++ === 0 ? [job("running")] : [] }));
  await page.route(/\/api\/jobs\/job-990001$/, (route: Route) =>
    route.fulfill({ json: job("failed", { error: DOWN, error_code: "provider_unreachable", finished_at: "2026-11-02T11:45:09Z" }) }),
  );
  await page.route(/\/api\/jobs$/, async (route: Route) => {
    if (route.request().method() !== "POST") return route.fallback();
    posted.push(route.request().postDataJSON());
    return route.fulfill({ status: 202, json: job("queued", { id: "job-990002", kind: "run", files: [] }) });
  });
  await page.goto("/scope");
  await waitForTree(page);
  const banner = page.getByTestId("job-failed");
  await expect(banner).toBeVisible({ timeout: 15_000 });
  await expect(banner).toHaveText(new RegExp(`Reading the new manuals failed: ${DOWN.replace(/[.*+?^${}()|[\]\\`]/g, "\\$&")}`));
  await expect(banner).not.toContainText("stage failed");
  await banner.getByRole("button", { name: "Retry" }).click();
  await expect.poll(() => posted).toEqual([{ to: "group", allow_reparse: false }]);
  await expect(page.getByTestId("job-failed")).toHaveCount(0);
});
