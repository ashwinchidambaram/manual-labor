import { expect, type APIRequestContext, type Page } from "@playwright/test";
import os from "node:os";

// Types come from the generated OpenAPI aliases, never hand-written copies.
import type { DocGroups, Group, SelectionOut } from "../src/api/schema";
export type { DocGroups, Group, SelectionOut };

export async function getGroups(request: APIRequestContext): Promise<DocGroups[]> {
  const r = await request.get("/api/scope/groups");
  expect(r.ok()).toBeTruthy();
  return (await r.json()) as DocGroups[];
}

let n = 0;
const rid = (): string => `e2e-${Date.now()}-${n++}`;

export async function putOp(request: APIRequestContext, op: Record<string, unknown>) {
  const r = await request.put("/api/scope/selection", { data: { request_id: rid(), subtree: false, block_ids: [], ...op } });
  expect(r.ok(), await r.text()).toBeTruthy();
  return r.json();
}

/** Back to the seeded default: topic view, per-topic split, every topic selected. */
export async function resetSelection(request: APIRequestContext): Promise<void> {
  const cur = await (await request.get("/api/scope/selection")).json();
  if (cur.selection.block_ids.length) await putOp(request, { op: "deselect", block_ids: cur.selection.block_ids });
  for (const d of await getGroups(request))
    for (const t of d.groups.topics) await putOp(request, { op: "select_group", group_id: t.id, doc_id: d.doc_id });
  await putOp(request, { op: "set_view", view: "topic" });
  await putOp(request, { op: "set_split", split: "per_topic" });
}

export async function clearSelection(request: APIRequestContext): Promise<void> {
  const cur = await (await request.get("/api/scope/selection")).json();
  if (cur.selection.block_ids.length) await putOp(request, { op: "deselect", block_ids: cur.selection.block_ids });
}

export const stat = async (page: Page, id: string): Promise<number> =>
  Number((await page.getByTestId(id).innerText()).trim());

export const row = (page: Page, groupId: string) => page.locator(`[data-testid=row][data-group-id="${groupId}"]`);

export async function waitForTree(page: Page): Promise<void> {
  await expect(page.getByTestId("group-tree")).toBeVisible();
  await expect(page.getByTestId("row").first()).toBeVisible();
}

/** The PUT queue is idle once no coverage chip is dimmed. */
export async function waitSettled(page: Page): Promise<void> {
  await expect(page.locator("[data-testid=coverage-chip][data-stale=true]")).toHaveCount(0);
}

/** Wait until no job is queued or running. */
export async function waitJobsIdle(request: APIRequestContext, ms = 180_000): Promise<void> {
  await expect
    .poll(
      async () => {
        const r = await request.get("/api/jobs?status=queued&status=running");
        return ((await r.json()) as unknown[]).length;
      },
      { timeout: ms, intervals: [500, 1000] },
    )
    .toBe(0);
}

/** Small typed JSON helpers over the request context. */
export function api(request: APIRequestContext) {
  return {
    get: async <T>(url: string): Promise<T> => {
      const r = await request.get(url);
      expect(r.ok(), `${url}: ${await r.text()}`).toBeTruthy();
      return (await r.json()) as T;
    },
    put: async <T>(url: string, data: unknown): Promise<T> => {
      const r = await request.put(url, { data });
      expect(r.ok(), `${url}: ${await r.text()}`).toBeTruthy();
      return (await r.json()) as T;
    },
    post: async <T>(url: string, data: unknown): Promise<T> => {
      const r = await request.post(url, { data });
      expect(r.ok(), `${url}: ${await r.text()}`).toBeTruthy();
      return (await r.json()) as T;
    },
  };
}

/**
 * A latency budget measured from the browser (key or click to the server's answer) while work runs beside it. Budgets
 * are set on the 10-core reference Mac and hold unchanged on any machine with 4 or more cores. Below that (GitHub's
 * 2-vCPU ubuntu runner) the browser, the Playwright driver, the dev server, the API and the job worker share two
 * cores, and the browser's own scheduling is part of every measurement, so the budget is doubled. Why not 1x: the
 * server-side approve ack under a re-parse is now a median 55 to 106 ms, but its tail reached 683 ms on the Mac under
 * external load, and the client adds its own time on a shared core; a 2-core run cannot promise 500 ms. The cost:
 * on 2 cores this check only catches acks over 1 s (the pre-fix CI acks, 175 to 878 ms, would have passed it), so the
 * 4-core-plus runs remain the real 500 ms check. Design 09 section 12 has the measurements.
 */
export const LATENCY_SCALE = os.cpus().length < 4 ? 2 : 1;
export const latencyBudget = (ms: number): number => ms * LATENCY_SCALE;
