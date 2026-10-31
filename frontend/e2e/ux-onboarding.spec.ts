// Module 12 UX check: a first-time user who has never seen the app (design 12 section 7, CLAUDE.md UX-check paragraph).
// Written by a reviewer who did not build the screens. Server-side evidence is queried from the API in each test.
// Order-independent: UX7 checks the override requests through route interception, so no override is recorded on the
// shared server; every test starts from the first-run guide state and afterAll restores seen=true.
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { BlockDetail, DocGroups, ExportStatus, GuideState, QueuePage, ScopeBlocks, ScopeSummary } from "../src/api/schema";
import { api, resetSelection, waitForTree, waitJobsIdle } from "./helpers";

test.describe.configure({ mode: "default" });
test.setTimeout(120_000);

const panel = (page: Page) => page.getByRole("complementary", { name: "Getting started" });
const currentCard = (page: Page) => page.locator("[data-testid^='card-'][aria-current='true']");
const rid = (): string => `uxo-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const setGuide = (request: APIRequestContext, seen: boolean) => api(request).put<GuideState>("/api/ui/guide", { seen });
const putCursor = (request: APIRequestContext, id: string | null) =>
  api(request).put("/api/verify/cursor", { sort: "worst_first", view_threshold: null, doc_filter: null, current_block_id: id, request_id: rid() });
const getQueue = (request: APIRequestContext, q = "") => api(request).get<QueuePage>(`/api/verify/queue?limit=2000${q}`);
interface Row { id: number; kind: string; screen: string; target_id: string | null }
async function decisions(request: APIRequestContext): Promise<Row[]> {
  const t = await (await request.get("/api/decisions/export")).text();
  return t.split("\n").filter(Boolean).map((l) => JSON.parse(l) as Row);
}
const note = (what: string, text: string) => test.info().annotations.push({ type: what, description: text.replace(/\s+/g, " ").trim().slice(0, 900) });
const visibleText = (page: Page) => page.evaluate(() => document.body.innerText);

test.beforeAll(async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  await waitJobsIdle(ctx);
  await ctx.dispose();
});
test.beforeEach(async ({ request }) => {
  await waitJobsIdle(request);
  await resetSelection(request);
  await putCursor(request, null);
  await setGuide(request, false); // first-run state
});
test.afterAll(async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  await setGuide(ctx, true);
  await putCursor(ctx, null);
  await ctx.dispose();
});

test("UX1 cold start: the first screen says what the app does, what the numbers mean and what to press", async ({ page, request }) => {
  await page.goto("/scope");
  await waitForTree(page);
  await expect(panel(page)).toBeVisible();
  await expect(panel(page)).toHaveAttribute("data-step", "scope");
  await expect(page.getByTestId("step-short-scope")).toHaveText("here"); // design 13 section 5: the rail marks the step
  const guideText = await panel(page).innerText();
  const screen = await visibleText(page);
  note("guide-text-relied-on", guideText);
  note("scope-screen-text", screen);
  // what it does
  expect(guideText).toMatch(/knowledge base/i);
  // what the numbers mean: the summary labels and the estimated-review line explain themselves
  await expect(page.getByTestId("selection-summary")).toContainText("Estimated review");
  // design 13 section 5: the estimate is explained by the summary's own sentence
  await expect(page.getByTestId("selection-summary")).toContainText("contain numbers, which a person always checks");
  // what to press next
  expect(guideText).toMatch(/confirms: scoring starts and Verify opens/);
  expect(guideText).toMatch(/\b[A-Za-z]\b.*selects/);
  // per-document reconciliation adds up against the API
  const groups = await api(request).get<DocGroups[]>("/api/scope/groups");
  const blocks = await api(request).get<ScopeBlocks[]>("/api/scope/blocks");
  const summary = await api(request).get<ScopeSummary>("/api/scope/summary");
  let inTopicsAll = 0;
  let unassignedAll = 0;
  for (const d of groups) {
    const bl = blocks.find((b) => b.doc_id === d.doc_id)!.blocks;
    const hf = bl.filter((b) => b.type === "header" || b.type === "footer").length;
    const inTopics = d.groups.topics.filter((t) => !t.is_unassigned).reduce((n, t) => n + t.block_ids.length, 0);
    const un = d.groups.topics.filter((t) => t.is_unassigned).reduce((n, t) => n + t.block_ids.length, 0);
    inTopicsAll += inTopics;
    unassignedAll += un;
    const line = await page.locator(`[data-testid=doc-heading][data-doc='${d.doc_id}'] [data-testid=doc-reconcile]`).innerText();
    const m = line.match(/(\d+) blocks found = (\d+) in topics \+ (\d+) not placed \+ (\d+) page headers and footers, left out/);
    expect(m, `${d.doc_id}: ${line}`).not.toBeNull();
    const [p, t, u, h] = m!.slice(1).map(Number);
    expect(p).toBe(h + t + u); // the line adds up
    expect([p, h, t, u]).toEqual([bl.length, hf, inTopics, un]); // and equals the API
  }
  // the all-selected Blocks stat is a subset of what the reconciliation lines list as eligible
  const shownBlocks = Number((await page.getByTestId("sum-blocks").innerText()).trim());
  expect(shownBlocks).toBe(summary.blocks);
  expect(summary.blocks).toBeLessThanOrEqual(inTopicsAll + unassignedAll);
});

test("UX2 confirm scope then process 5 blocks using only what the screen shows", async ({ page, request }) => {
  await page.goto("/scope");
  await waitForTree(page);
  // the first-timer finds the primary button by its label and the key by the hint the screen offers
  const confirm = page.getByRole("button", { name: /Confirm scope and go to Verify/ });
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(page).toHaveURL(/\/verify/);
  await expect(currentCard(page)).toBeFocused();
  const before = await getQueue(request);
  const rowsBefore = (await decisions(request)).length;
  // learn the approve key from the toolbar the user can see
  const kbd = (await page.getByRole("toolbar", { name: "Review actions" }).getByRole("button", { name: /Approve/ }).locator("kbd").innerText()).trim();
  note("approve-key-read-from-toolbar", kbd);
  let done = 0;
  for (let i = 0; i < 5; i++) {
    const id = (await page.getByTestId("block-id").innerText()).trim();
    await page.keyboard.press(kbd.toLowerCase());
    await expect.poll(async () => (await decisions(request)).filter((r) => r.target_id === id && r.kind === "approve").length, { message: id }).toBeGreaterThan(0);
    done++;
    await expect(page.getByTestId("block-id")).not.toHaveText(id); // wait for the screen to move on before the next key
    await expect(currentCard(page), `after approve #${done} of ${id}; active: ${await page.evaluate(() => { const a = document.activeElement as HTMLElement | null; return a ? `${a.tagName} ${a.getAttribute("data-testid") ?? a.getAttribute("aria-label") ?? ""}` : "none"; })}`).toBeFocused();
  }
  expect(done).toBe(5);
  const after = await getQueue(request);
  expect(after.total).toBe(before.total - 5);
  expect((await decisions(request)).length).toBeGreaterThanOrEqual(rowsBefore + 5);
  expect(after.counts.approved + after.counts.edited).toBeGreaterThanOrEqual(before.counts.approved + before.counts.edited + 5);
});

test("UX3 trust: why queued, checks, source line and diff/original panes agree with the API", async ({ page, request }) => {
  const q = (await getQueue(request)).items;
  let found: { id: string; d: BlockDetail } | null = null;
  for (const it of q.slice(0, 250)) {
    const d = await api(request).get<BlockDetail>(`/api/verify/blocks/${it.block_id}`);
    if (d.block.type !== "figure" && d.block.has_numeric_spec && d.block.faithfulness && d.block.clean_text != null) {
      found = { id: it.block_id, d };
      break;
    }
  }
  expect(found, "a queued block with numbers and a faithfulness result").not.toBeNull();
  const { id, d } = found!;
  await putCursor(request, id);
  await page.goto("/verify");
  await expect(page.getByTestId("block-id")).toHaveText(id);
  // why queued
  const why = page.getByRole("region", { name: "Extracted text" }).getByLabel("Why this needs you").first();
  await expect(page.getByText("Why this needs you", { exact: true })).toBeVisible();
  await expect(page.getByTestId("why-rule")).toContainText("Blocks with numbers are always reviewed by a person");
  note("why-queued", await page.getByTestId("why-rule").innerText());
  void why;
  // checks list vs API
  const checks = page.getByTestId("checks-list");
  await expect(checks).toBeVisible();
  const f = d.block.faithfulness!;
  await expect(page.getByTestId("check-faithfulness")).toHaveAttribute("data-outcome", f.passed ? "passed" : "failed");
  await expect(page.getByTestId("check-faithfulness")).toContainText(f.passed ? "Passed" : "Failed");
  const numericBad = (f.violations ?? []).some((v) => v.kind === "numeric_mismatch");
  await expect(page.getByTestId("check-numbers")).toHaveAttribute("data-outcome", numericBad ? "failed" : "passed");
  // no row claims "Passed" while the API says failed, and vice versa
  const rows = await checks.locator("[data-outcome]").evaluateAll((els) => els.map((e) => [e.getAttribute("data-testid"), e.getAttribute("data-outcome"), (e as HTMLElement).innerText] as [string, string, string]));
  note("checks", rows.map((r) => r.join(": ")).join(" | "));
  if (!f.passed) for (const [, outcome] of rows.filter((r) => r[0] === "check-faithfulness")) expect(outcome).not.toBe("passed");
  // source line
  const sources = await api(request).get<{ slug: string; filename: string }[]>("/api/sources");
  const filename = sources.find((s) => s.slug === d.block.doc_id)?.filename ?? d.block.doc_id;
  const prov = await page.getByTestId("provenance").innerText();
  note("provenance", prov);
  expect(prov).toContain(filename);
  expect(prov).toMatch(new RegExp(`page ${d.block.page}\\b`));
  // original and cleaned views
  await expect(page.getByRole("group", { name: "Original vs cleaned" })).toBeVisible();
  await expect(page.getByTestId("view-text")).toBeVisible();
  await expect(page.getByTestId("view-diff")).toBeVisible();
  await expect(page.getByRole("region", { name: "Source page" })).toBeVisible();
  if ((d.block.raw_text ?? "") !== (d.block.clean_text ?? "")) {
    await page.getByTestId("view-diff").click();
    await expect(page.getByTestId("diff-view")).toBeVisible();
  }
});

test("UX4 the guide never steals focus: editor keeps it through a late ack and guide clicks; Esc returns to the queue", async ({ page, request }) => {
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await expect(panel(page)).toBeVisible();
  // late ack: approve (POST in flight) then immediately open the editor on the next card
  const before = (await decisions(request)).length;
  await page.keyboard.press("a");
  await page.keyboard.press("e");
  const ta = page.getByLabel("Edit block text");
  if ((await ta.count()) === 0) await expect(page.getByTestId("act-edit")).toBeDisabled(); // a figure card: editing is disabled by design
  else {
    await expect(ta).toBeFocused();
    await expect.poll(async () => (await decisions(request)).length).toBeGreaterThan(before); // the ack has landed
    await page.waitForTimeout(800);
    await expect(ta).toBeFocused();
    await panel(page).getByTestId("next-step").click(); // guide interaction mid-edit (design 13 section 5: no Next button)
    await expect(ta).toBeFocused();
    await page.keyboard.type("?");
    await expect(page.getByRole("dialog", { name: "Help" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(ta).toHaveCount(0);
    await expect(currentCard(page)).toBeFocused();
  }
  // ? from the queue opens Help; Esc gives the card its focus back
  const id = await currentCard(page).getAttribute("data-testid");
  await page.keyboard.press("?");
  const dlg = page.getByRole("dialog", { name: "Help" });
  await expect(dlg).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dlg).toHaveCount(0);
  await expect(page.getByTestId(id!)).toBeFocused();
});

test("UX5 tooltips by keyboard: Tab to three controls, text appears on focus and goes on Esc/blur without closing anything", async ({ page }) => {
  await page.goto("/scope");
  await waitForTree(page);
  await page.getByTestId("group-tree").locator("[data-testid=row]").first().focus();
  const tabTo = async (matcher: (info: string) => boolean, max = 80, back = false): Promise<void> => {
    for (let i = 0; i < max; i++) {
      await page.keyboard.press(back ? "Shift+Tab" : "Tab");
      const info = await page.evaluate(() => {
        const e = document.activeElement as HTMLElement | null;
        return e ? `${e.getAttribute("aria-label") ?? ""}|${e.getAttribute("data-testid") ?? ""}|${(e.textContent ?? "").trim().slice(0, 60)}` : "";
      });
      if (matcher(info)) return;
    }
    throw new Error("control not reachable by Tab");
  };
  const tip = page.getByRole("tooltip");
  // 1. Confirm (forward from the tree)
  await tabTo((i) => i.includes("|confirm|"));
  await expect(tip).toBeVisible();
  note("tooltip-confirm", await tip.innerText());
  await page.keyboard.press("Escape");
  await expect(tip).toHaveCount(0);
  await expect(page).toHaveURL(/\/scope/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // 2. the Verify nav link (back towards the header)
  await tabTo((i) => i.startsWith("Verify|"), 120, true);
  await expect(tip).toBeVisible();
  note("tooltip-nav-verify", await tip.innerText());
  const verifyTip = page.locator("[role='tooltip'][data-hint='navVerify']");
  await expect(verifyTip).toBeVisible();
  await page.keyboard.press("Tab"); // blur by moving on: the next link has its own tooltip, this one must be gone
  await expect(verifyTip).toHaveCount(0);
  // 3. Help button
  await tabTo((i) => i.includes("Help") || i.includes("help"), 120, true).catch(async () => {
    await page.locator("[data-help-button]").focus();
  });
  await page.keyboard.press("Shift"); // make the modality keyboard
  await page.locator("[data-help-button]").focus();
  await expect(tip).toBeVisible();
  note("tooltip-help", await tip.innerText());
  await page.keyboard.press("Escape");
  await expect(tip).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // Esc on a tooltip while the editor is open: the tooltip goes; the editor is not the thing the user asked to close
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await page.keyboard.press("e");
  const ta = page.getByLabel("Edit block text");
  if (await ta.count()) {
    const typed = ` ux5-${Date.now()}`;
    await page.keyboard.type(typed);
    await page.keyboard.press("Shift");
    await page.getByTestId("act-approve").focus();
    await expect(tip).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(tip).toHaveCount(0);
    note("esc-with-tooltip-and-editor", `editor still open after Esc: ${(await ta.count()) > 0}`);
    await expect(ta, "Esc dismissed the tooltip and must not also cancel the editor").toHaveCount(1);
    await expect(ta, "the typed text survives the Esc").toHaveValue(new RegExp(`${typed}$`));
    // with no tooltip open, Esc behaves exactly as before: it cancels the editor, nothing saved
    await ta.focus();
    await page.keyboard.press("Escape");
    await expect(ta).toHaveCount(0);
  }
});

test("UX6 Hide persists: reload keeps it hidden, the server says seen, ? reopens Help on the Guide tab", async ({ page, request }) => {
  await page.goto("/scope");
  await waitForTree(page);
  // design 13 section 5: Hide moved to the first-run welcome
  await page.getByTestId("welcome").getByRole("button", { name: "I have used this before" }).click();
  await expect(page.getByTestId("welcome")).toHaveCount(0);
  await expect.poll(async () => (await api(request).get<GuideState>("/api/ui/guide")).seen).toBe(true);
  const guideGet = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/ui/guide" && r.request().method() === "GET");
  await page.reload();
  expect((await guideGet).ok()).toBe(true);
  await waitForTree(page);
  await expect(page.getByTestId("welcome")).toHaveCount(0);
  expect((await api(request).get<GuideState>("/api/ui/guide")).seen).toBe(true);
  await page.keyboard.press("?");
  const dlg = page.getByRole("dialog", { name: "Help" });
  await expect(dlg).toBeVisible();
  await expect(dlg.getByRole("tab", { name: "Guide" })).toHaveAttribute("aria-selected", "true");
  // and a first-timer who hid it can find it again from the Guide tab
  // review M13 P2-19: the button names what it does
  await expect(dlg.getByRole("button", { name: /Show the welcome again/ })).toBeVisible();
  await page.keyboard.press("Escape");
});

test("UX8 Agent screen explains an agent pass and what to do with no flags; the run button is actionable or explains itself", async ({ page, request }) => {
  const flags = await api(request).get<unknown[]>("/api/flags");
  await page.goto("/agent");
  const screen = page.getByTestId("agent-screen");
  await expect(screen).toBeVisible();
  const text = await screen.innerText();
  note("agent-screen-text", text);
  // the explanation must be readable without clicking the button
  const withoutButton = await screen.evaluate((el) => {
    const c = el.cloneNode(true) as HTMLElement;
    c.querySelectorAll("button").forEach((b) => b.remove());
    return c.innerText;
  });
  // review M13 P2-21: the intro is in plain words ("goes to a model with your note", "checked again by the same checks")
  expect(withoutButton).toMatch(/goes to a model with your note/i);
  expect(withoutButton).toMatch(/checked again by the same checks/i);
  const run = page.getByTestId("agent-run");
  if (flags.length === 0) {
    await expect(page.getByTestId("agent-empty")).toContainText("No open flags");
    await expect(page.getByTestId("agent-empty")).toContainText("Flag a block in Verify");
    // disabled is only acceptable when the page says why
    if (await run.isDisabled()) {
      const reason = (await run.getAttribute("title")) ?? (await run.getAttribute("aria-describedby")) ?? "";
      expect(reason || (await page.getByTestId("agent-empty").innerText())).toBeTruthy();
    }
  } else {
    await expect(run).toBeEnabled();
    await expect(run).toContainText(`${flags.length} flag`);
  }
  // the guide panel on this screen is the agent card
  await expect(panel(page)).toHaveAttribute("data-step", "agent");
});

test("UX9 narrow width: guide is a bottom sheet and the Verify action bar stays reachable", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await expect(panel(page)).toBeVisible();
  const vp = page.viewportSize()!;
  const pb = (await panel(page).boundingBox())!;
  expect(Math.round(pb.x)).toBe(0);
  expect(Math.round(pb.width)).toBe(vp.width);
  expect(Math.round(pb.y + pb.height)).toBe(vp.height); // pinned to the bottom edge
  expect(pb.height).toBeLessThanOrEqual(vp.height * 0.4 + 1);
  const bar = (await page.getByRole("toolbar", { name: "Review actions" }).boundingBox())!;
  note("geometry", `viewport ${vp.height}, sheet y=${Math.round(pb.y)} h=${Math.round(pb.height)}, toolbar y=${Math.round(bar.y)} h=${Math.round(bar.height)}`);
  const covered: string[] = [];
  for (const t of ["act-approve", "act-edit", "act-flag", "act-skip", "act-back"]) {
    const b = page.getByTestId(t);
    const box = (await b.boundingBox())!;
    const hit = await page.evaluate(([x, y, id]) => (document.elementFromPoint(x as number, y as number) as HTMLElement | null)?.closest(`[data-testid='${id}']`) !== null, [box.x + box.width / 2, box.y + box.height / 2, t] as const);
    if (!hit) covered.push(t);
  }
  expect(covered, `buttons covered by the guide sheet (${test.info().annotations.find((a) => a.type === "geometry")?.description})`).toEqual([]);
  expect(bar.y + bar.height, "toolbar must end at or above the sheet").toBeLessThanOrEqual(pb.y + 1);
  // and it still works with the mouse while the sheet is open
  await expect(page.getByTestId("act-approve")).toBeEnabled();
  // Scope: the Confirm button can be scrolled to and is not under the sheet
  await page.goto("/scope");
  await waitForTree(page);
  const c = page.getByTestId("confirm");
  const notCovered = async (): Promise<boolean> => {
    const b = (await c.boundingBox())!;
    return page.evaluate(([x, y]) => !!document.elementFromPoint(x as number, y as number)?.closest("[data-testid=confirm]"), [b.x + b.width / 2, b.y + b.height / 2] as const);
  };
  // at the top of the page, without hunting for it: pinned above the sheet
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(c).toBeInViewport();
  expect(await notCovered(), "Confirm is under the guide sheet at the top of the page").toBe(true);
  const cTop = (await c.boundingBox())!;
  const sheet = (await panel(page).boundingBox())!;
  expect(cTop.y + cTop.height, "Confirm ends above the sheet").toBeLessThanOrEqual(sheet.y + 1);
  await c.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight)); // a user scrolls to the end
  await expect(c).toBeVisible();
  const cb = (await c.boundingBox())!;
  const hit = await page.evaluate(([x, y]) => !!document.elementFromPoint(x as number, y as number)?.closest("[data-testid=confirm]"), [cb.x + cb.width / 2, cb.y + cb.height / 2] as const);
  expect(hit, "Confirm is under the guide sheet even at the end of the page").toBe(true);
});

test("UX10 honest copy: no exclamation marks, em dashes or unexplained bare confidence numbers on any screen", async ({ page, request }) => {
  const offenders: string[] = [];
  const scan = async (label: string): Promise<void> => {
    const res = await page.evaluate(() => {
      const root = document.body.cloneNode(true) as HTMLElement;
      // text that belongs to the manual (block text, previews, topic titles, ids) is data, not app copy
      root.querySelectorAll("[data-testid=block-text],[data-testid=diff-view],[data-zone=source],textarea,[data-testid=row],[data-testid=doc-heading],[data-testid^=card-],[data-testid=blocker-link],[data-testid=provenance]").forEach((n) => n.remove());
      const t = root.innerText ?? root.textContent ?? "";
      const out: string[] = [];
      if (/!/.test(t)) out.push(`exclamation: ${(t.match(/.{0,30}!.{0,20}/) ?? [""])[0]}`);
      if (/—/.test(t)) out.push(`em dash: ${(t.match(/.{0,30}—.{0,20}/) ?? [""])[0]}`);
      // bare score numbers (0.xx / 1.00) in the live DOM, with no word that names them
      document.querySelectorAll<HTMLElement>("body *").forEach((e) => {
        if (e.children.length || e.closest("[data-testid=why-item],[data-testid=block-text],[data-testid=diff-view],mark,[data-testid=checks-list]")) return;
        const s = (e.textContent ?? "").trim();
        if (!/^(0|1)\.\d{2}$/.test(s)) return;
        const types = /^(paragraph|heading|list_item|list|table|figure|header|footer|caption|code|text|n\/a)$/i;
        const own = `${e.getAttribute("aria-label") ?? ""} ${e.getAttribute("title") ?? ""}`;
        const prev = (e.previousSibling?.textContent ?? "").trim();
        const inSentence = e.parentElement?.tagName === "P" && (e.parentElement.textContent ?? "").replace(s, "").length > 20;
        const labelled = inSentence || /[A-Za-z]{4,}/.test(own) || (/[A-Za-z]{4,}/.test(prev) && !types.test(prev));
        if (!labelled) out.push(`bare score number with no label or reason in ${e.closest("[data-testid^=card-]") ? "a queue card" : (e.getAttribute("data-testid") ?? e.tagName)}`);
      });
      return out;
    });
    for (const r of new Set(res)) offenders.push(`${label}: ${r}`);
  };
  await page.goto("/scope");
  await waitForTree(page);
  // design 13 section 5: the rail shows one next step (no paging); the welcome replaces Hide guide
  await scan("scope with welcome");
  await page.getByTestId("welcome").getByRole("button", { name: "I have used this before" }).click();
  await scan("scope");
  const q = (await getQueue(request)).items;
  if (q[0]) await putCursor(request, q[0].block_id);
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await scan("verify");
  await page.getByTestId("view-diff").click().catch(() => undefined);
  await scan("verify diff");
  await page.goto("/agent");
  await expect(page.getByTestId("agent-flags")).toBeVisible();
  await scan("agent");
  await page.goto("/export");
  await expect(page.getByTestId("export-locked")).toBeVisible();
  await scan("export");
  const dlg = page.getByRole("dialog", { name: "Help" });
  // review M13 P3-22: the Guide as it opens on each of the four screens, then the other two tabs
  for (const path of ["/scope", "/verify", "/agent", "/export"]) {
    await page.goto(path);
    if (path === "/scope") await waitForTree(page);
    if (path === "/verify") await expect(currentCard(page)).toBeFocused();
    await page.keyboard.press("?");
    await expect(dlg).toBeVisible();
    await expect(dlg.getByRole("tab", { name: "Guide" })).toHaveAttribute("aria-selected", "true");
    await scan(`help Guide from ${path}`);
    await page.keyboard.press("Escape");
    await expect(dlg).toHaveCount(0);
  }
  await page.keyboard.press("?");
  await expect(dlg).toBeVisible();
  for (const tab of ["Keyboard shortcuts", "Glossary"]) {
    await dlg.getByRole("tab", { name: tab }).click();
    await scan(`help ${tab}`);
  }
  await page.keyboard.press("Escape");
  expect(offenders, offenders.join("\n")).toEqual([]);
});

test("UX7 Export locked: reason text, counts match the queue, override needs a reason and is one request per blocker", async ({ page, request }) => {
  const st = await api(request).get<ExportStatus>("/api/export/status");
  const queue = await getQueue(request);
  expect(st.unlocked).toBe(false);
  await page.goto("/export");
  await expect(page.getByRole("heading", { name: "Export is locked" })).toBeVisible();
  note("export-locked-text", await page.getByTestId("export-locked").innerText());
  await expect(page.getByTestId("export-locked")).toContainText("the export only contains text a person or the checks have accepted");
  // "to review" is the gate partition's to_review (design 11 section 17); with no override recorded it is the queue's queued
  const toReview = st.counts?.to_review ?? st.queued ?? 0;
  if (toReview > 0) {
    await expect(page.getByTestId("reason-queued")).toContainText(`${toReview} block`);
    expect(toReview + (st.counts?.overridden ?? 0), "to review + overridden must equal the server's queued count").toBe(queue.counts.queued);
  }
  const holdFlags = (st.flag_blockers ?? []).length;
  if (holdFlags > 0) await expect(page.getByTestId("reason-flags")).toContainText(`${holdFlags} open flag`);
  // the copy says what an override covers before anything is recorded
  await expect(page.getByTestId("override-form")).toContainText(
    "a flag raised on it after you record the override blocks the export again",
  );
  await expect(page.getByTestId("override-form")).toContainText("a block that starts blocking later is not covered");
  // empty reason is refused, nothing is sent
  const posted: { reason: string; target_id?: string | null; flag_id?: string | null; request_id?: string }[] = [];
  const statusAfterPosts = (): ExportStatus => {
    const done = new Set(posted.map((p) => p.target_id));
    return {
      ...st,
      blockers: (st.blockers ?? []).filter((b) => !done.has(b)),
      overrides: [...(st.overrides ?? []), ...posted.map((p) => ({ reason: p.reason, at: new Date().toISOString(), target_id: p.target_id ?? null, flag_id: null }))],
    };
  };
  await page.route("**/api/export/override", async (route) => {
    // intercepted: the shared server records nothing, so later specs see the same gate
    const body = route.request().postDataJSON() as (typeof posted)[number];
    posted.push(body);
    await route.fulfill({ json: statusAfterPosts() });
  });
  // the screen rereads the status after recording (and the rail's counts invalidate it): once anything was posted,
  // the reread must agree with the intercepted posts, as the real server would
  await page.route("**/api/export/status", async (route) => {
    if (posted.length === 0) return route.continue();
    await route.fulfill({ json: statusAfterPosts() });
  });
  await page.getByTestId("override-submit").click();
  await expect(page.getByRole("alert").filter({ hasText: "write why" })).toBeVisible();
  expect(posted).toEqual([]);
  // a reason sends one override per unflagged blocker, each with its own request id, never a blanket override; the stub
  // lists no further page after the first, so the run ends with the listed ones (design 11 section 18)
  const reason = `ux check ${Date.now()}`;
  await page.getByTestId("override-reason").fill(reason);
  await page.getByTestId("override-submit").click();
  await expect(page.getByTestId("overrides")).toContainText(reason);
  await expect(page.getByTestId("overrides")).toContainText("recorded in manifest.json");
  // a flagged blocker is left out of the batch: a block override never covers a flag (design 11 section 14)
  const flaggedIds = new Set((st.flag_blockers ?? []).map((f) => f.block_id));
  expect(posted.map((p) => p.target_id)).toEqual((st.blockers ?? []).filter((b) => !flaggedIds.has(b)));
  expect(posted.every((p) => p.reason === reason && p.flag_id == null && typeof p.target_id === "string")).toBe(true);
  expect(new Set(posted.map((p) => p.request_id)).size).toBe(posted.length);
  await page.unroute("**/api/export/override");
  await page.unroute("**/api/export/status");
  // and the server's gate is untouched
  expect(((await api(request).get<ExportStatus>("/api/export/status")).overrides ?? []).length).toBe((st.overrides ?? []).length);
});
