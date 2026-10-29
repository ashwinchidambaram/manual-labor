import { expect, type APIRequestContext, type Page } from "@playwright/test";

export interface Group {
  id: string;
  title: string;
  block_ids: string[];
  block_count: number;
  is_unassigned: boolean;
  parent_id: string | null;
  cohesion: number | null;
}
export interface DocGroups {
  doc_id: string;
  groups: { structure: Group[]; topics: Group[]; params: { low_cohesion: number } };
}

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
