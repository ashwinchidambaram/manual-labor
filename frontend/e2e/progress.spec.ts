// First-use report C9, C10, D (2026-10-30): while scoring runs, the jobs bar names the step, the manual and the
// worker's own block count, the count moves only when the worker moves it, the bar stays on screen while the page
// scrolls, and Verify's empty list says "Scoring in progress, N of M blocks scored" instead of "All caught up".
//
// Runs its own server on 8767 over a copy of the cached e2e project with every document unscored, and with
// MANUALLABOR_DELAY slowing each block-count step of `score` (manuallabor/jobs/worker.py StepLog), so the step is
// reliably visible. The page is the built dist (made by the 8766 web server's `npm run build`).
import fs from "node:fs";
import path from "node:path";
import { expect, test, type APIRequestContext } from "@playwright/test";
import type { JobInfo, SourceInfo } from "../src/api/schema";
import { startOwnServer, type OwnServer } from "./ownServer";

const PORT = 8767;
const BASE = `http://127.0.0.1:${PORT}`;

let own: OwnServer | null = null;
let api: APIRequestContext;

test.beforeAll(async () => {
  test.setTimeout(180_000);
  own = await startOwnServer({
    port: PORT,
    // every document unscored: Verify has nothing to list until scoring runs (data/readiness: scores.json + clean.json)
    prepare: (project) => {
      for (const slug of fs.readdirSync(path.join(project, "docs"))) fs.rmSync(path.join(project, "docs", slug, "scores.json"), { force: true });
    },
    env: { MANUALLABOR_DELAY: "step:score=0.3" },
  });
  api = own.api;
});

test.afterAll(async () => {
  test.setTimeout(90_000);
  await own?.stop();
  own = null;
});

test("while scoring runs: the step with its count, real motion, a sticky bar, and an honest empty Verify", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1100, height: 560 });
  const sources = (await (await api.get("/api/sources")).json()) as SourceInfo[];
  const file = new Map(sources.map((s) => [s.slug, s.filename]));
  const job = (await (await api.post("/api/jobs", { data: { to: "score2", allow_reparse: false } })).json()) as JobInfo;

  const running = async (): Promise<JobInfo | undefined> =>
    ((await (await api.get("/api/jobs?status=running")).json()) as JobInfo[]).find((j) => j.id === job.id);
  // the server reaches the score step and counts blocks
  await expect.poll(async () => (await running())?.step_unit ?? null, { timeout: 120_000, intervals: [250] }).toBe("block");

  await page.goto(`${BASE}/verify`);
  const bar = page.getByTestId("jobs-bar");
  await expect(bar).toBeVisible();
  const step = bar.getByTestId("job-step");
  // the bar names the manual by its slug until the Sources list has loaded (JobsBar `useFileOf`), then by its file
  // name; under load that list can arrive after the first step text, so the step must name one of the files
  const anyFile = [...file.values()].map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  await expect(step).toHaveText(new RegExp(`^Step \\d+ of \\d+: Scoring (${anyFile}), \\d+ of \\d+ blocks$`), { timeout: 30_000 });

  // the screen says what the server says: same manual, a count the server reported
  const shown = await step.innerText();
  const j1 = (await running())!;
  expect(j1.node).toBe("score");
  expect(shown).toContain(file.get(j1.doc!) ?? j1.doc!);
  expect(shown).toContain(`of ${j1.step_total} blocks`);

  // motion is real: the count and the bar advance only as the worker reports blocks (no animation, no estimate)
  const count = async (): Promise<number> => Number(/, (\d+) of \d+ blocks$/.exec(await step.innerText())?.[1] ?? -1);
  const value = async (): Promise<number> => Number(await bar.getByRole("progressbar").getAttribute("value"));
  const c0 = await count();
  const v0 = await value();
  await expect.poll(count, { timeout: 30_000 }).toBeGreaterThan(c0);
  await expect.poll(value, { timeout: 30_000 }).toBeGreaterThan(v0);
  expect(await value()).toBeLessThanOrEqual(((await running())?.progress ?? 1) + 1e-9);
  await expect(bar.getByTestId("job-no-estimate")).toHaveCount(0);

  // Verify: nothing is scored yet, so the list says scoring is in progress, with the count, and offers no export
  const empty = page.getByTestId("queue-empty");
  await expect(empty).toHaveAttribute("data-variant", "scoring");
  await expect(empty.getByTestId("queue-scoring-count")).toHaveText(/^Scoring in progress, \d+ of \d+ blocks scored in .+$/);
  await expect(empty).not.toContainText("All caught up");
  await expect(empty.getByRole("link", { name: "Go to Export" })).toHaveCount(0);
  await expect(page.getByTestId("queue-footer")).not.toContainText("You can start now");

  // the step rail waits for scoring instead of claiming Export is ready or Verify done
  const nav = page.getByRole("navigation", { name: "Screens" });
  await expect(nav.getByTestId("step-short-export")).toHaveText("after scoring");

  // the bar stays on screen while a long page scrolls
  await page.goto(`${BASE}/scope`);
  await expect(page.getByTestId("group-tree")).toBeVisible();
  const scrollable = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
  expect(scrollable, "the Scope page must scroll at this window size").toBeGreaterThan(200);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(200);
  const top = await bar.evaluate((el) => el.getBoundingClientRect().top);
  expect(top).toBeGreaterThanOrEqual(0);
  expect(top).toBeLessThanOrEqual(1);
  await expect(bar.getByTestId("job-step")).toBeInViewport();
});
