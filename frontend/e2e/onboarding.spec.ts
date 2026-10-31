// Module 12: onboarding guide, tooltips, trust evidence and the Agent/Export screens (design 12 section 7, OB1-OB10).
// The guide flag is cleared before each test here and set again afterwards; global-setup.ts sets it for every
// other spec. Nothing here records a review decision.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { DocGroups, ExportStatus, GuideState, QueuePage, ScopeBlocks } from "../src/api/schema";
import { HOTKEYS } from "../src/hotkeys";
import { HINTS, type HintId } from "../src/onboarding/hints";
import { api, resetSelection, row, waitForTree, waitJobsIdle } from "./helpers";

test.describe.configure({ mode: "serial" });

const panel = (page: Page) => page.getByRole("complementary", { name: "Getting started" });
const setGuide = async (request: Parameters<typeof api>[0], seen: boolean) => api(request).put<GuideState>("/api/ui/guide", { seen });
const putCursor = async (request: Parameters<typeof api>[0], id: string | null) =>
  api(request).put("/api/verify/cursor", { sort: "worst_first", view_threshold: null, doc_filter: null, current_block_id: id, request_id: `ob-${Date.now()}-${Math.random()}` });
const currentCard = (page: Page) => page.locator("[data-testid^='card-'][aria-current='true']");
const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

test.beforeAll(async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  expect((await ctx.post("/api/probe")).ok()).toBeTruthy(); // the model panel's Apply control needs a probe
  await waitJobsIdle(ctx);
  await ctx.dispose();
});
test.beforeEach(async ({ request }) => {
  await waitJobsIdle(request);
  await resetSelection(request);
  await putCursor(request, null);
  await setGuide(request, false);
});
test.afterAll(async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8765" });
  await setGuide(ctx, true);
  await resetSelection(ctx);
  await putCursor(ctx, null);
  await ctx.dispose();
});

test("OB1 fresh project: panel docked on /scope, focus in the tree, hotkeys work with it open", async ({ page }) => {
  await page.goto("/scope");
  await waitForTree(page);
  await expect(panel(page)).toBeVisible();
  await expect(panel(page)).toHaveAttribute("data-step", "scope");
  await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest("[data-zone='tree']"))).toBe(true);
  const cur = () => page.evaluate(() => (document.activeElement as HTMLElement).getAttribute("data-group-id"));
  const first = await cur();
  await page.keyboard.press("j");
  const second = await cur();
  expect(second).not.toBe(first);
  const before = await row(page, second!).getAttribute("data-check");
  await page.keyboard.press("Space");
  await expect(row(page, second!)).not.toHaveAttribute("data-check", before!);
  await page.keyboard.press("t");
  await expect(page).toHaveURL(/view=structure/);
  expect(await page.evaluate(() => !!document.activeElement?.closest("[data-zone='tree']"))).toBe(true);
  await expect(panel(page)).toBeVisible();
  expect(await page.evaluate(() => !!document.activeElement?.closest("[aria-label='Getting started']"))).toBe(false);
});

test("OB2 Hide persists on the server: reload shows no panel", async ({ page, request }) => {
  await page.goto("/scope");
  await waitForTree(page);
  // design 13 section 5: the guide panel's Hide moved to the first-run welcome ("I have used this before")
  const welcome = page.getByTestId("welcome");
  await welcome.getByRole("button", { name: "I have used this before" }).click();
  await expect(welcome).toHaveCount(0);
  await expect.poll(async () => (await api(request).get<GuideState>("/api/ui/guide")).seen).toBe(true);
  const g = await api(request).get<GuideState>("/api/ui/guide");
  expect(g.version).toBe(1);
  expect(g.seen_at).toBeTruthy();
  // wait for the app's own guide GET to answer, not for a fixed time
  const guideGet = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/ui/guide" && r.request().method() === "GET");
  await page.reload();
  expect((await guideGet).ok()).toBe(true);
  await waitForTree(page);
  await expect(page.getByTestId("welcome")).toHaveCount(0);
});

test("OB3 ? opens Help on the Guide tab at the current step; Esc restores focus", async ({ page }) => {
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  const id = await currentCard(page).getAttribute("data-testid");
  await page.keyboard.press("?");
  const dlg = page.getByRole("dialog", { name: "Help" });
  await expect(dlg).toBeVisible();
  await expect(dlg.getByRole("tab", { name: "Guide" })).toHaveAttribute("aria-selected", "true");
  await expect(dlg.locator("[data-guide-step='verify']")).toBeInViewport();
  await page.keyboard.press("Escape");
  await expect(dlg).toHaveCount(0);
  await expect(page.getByTestId(id!)).toBeFocused();
});

test("OB4 the guide never takes focus mid-edit; ? typed in the editor is text", async ({ page, request }) => {
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await expect(panel(page)).toHaveAttribute("data-step", "verify");
  const id = (await page.getByTestId("block-id").innerText()).trim();
  await page.keyboard.press("e");
  const ta = page.getByLabel("Edit block text");
  await expect(ta).toBeFocused();
  const start = await ta.inputValue();
  await page.keyboard.type(" abc");
  // design 13 section 5: the rail has no Next/Previous; pressing on it (the next-step card) must not take focus either
  await panel(page).getByTestId("next-step").click();
  await panel(page).getByTestId("next-step-text").click();
  await expect(panel(page)).toHaveAttribute("data-step", "verify");
  await expect(ta).toBeFocused();
  await page.keyboard.type(" def?");
  await expect(ta).toHaveValue(`${start} abc def?`);
  await expect(page.getByRole("dialog", { name: "Help" })).toHaveCount(0);
  await page.keyboard.press("Escape"); // cancels the edit: nothing is saved
  await expect(ta).toHaveCount(0);
  const d = await api(request).get<{ block: { clean_text: string | null; raw_text: string } }>(`/api/verify/blocks/${id}`);
  expect(d.block.clean_text ?? d.block.raw_text).toBe(start);
});

test("OB5 tooltips: keyboard focus on each named control shows its registered text and key", async ({ page }) => {
  const seen: string[] = [];
  // `described`: the element that carries aria-describedby (a group hint describes its radiogroup)
  const check = async (target: ReturnType<Page["locator"]>, id: HintId, described = target) => {
    await page.keyboard.press("Shift"); // keyboard modality, as a Tab would be
    await target.focus();
    const tip = page.locator(`[role='tooltip'][data-hint='${id}']`);
    await expect(tip, id).toBeVisible();
    await expect(tip, id).toContainText(HINTS[id].text);
    const h = HINTS[id] as { hotkey?: keyof typeof HOTKEYS };
    if (h.hotkey) await expect(tip.locator("kbd"), id).toBeVisible();
    expect((await described.getAttribute("aria-describedby")) ?? "", id).toContain((await tip.getAttribute("id"))!);
    seen.push(id);
  };
  await page.goto("/scope");
  await waitForTree(page);
  const nav = page.getByRole("navigation", { name: "Screens" });
  await check(nav.getByRole("link", { name: "Scope" }), "navScope");
  await check(nav.getByRole("link", { name: "Verify" }), "navVerify");
  await check(nav.getByRole("link", { name: "Agent" }), "navAgent");
  await check(nav.getByRole("link", { name: "Export" }), "navExport");
  await check(page.locator("[data-help-button]"), "help");
  const views = page.getByRole("radiogroup", { name: "Grouping view" });
  await check(views.getByRole("radio", { checked: true }), "viewToggle", views);
  const split = page.getByRole("radiogroup", { name: "Article split" });
  await check(split.getByRole("radio", { checked: true }), "splitMode", split);
  await check(page.getByRole("button", { name: "Select all" }), "selectAll");
  await check(page.getByTestId("clear-selection"), "selectNone");
  await check(page.getByTestId("confirm"), "confirm");
  await check(page.getByRole("button", { name: "Add documents" }), "addDocuments");
  await check(page.getByTestId("apply-tier"), "applyTier");
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await check(page.getByLabel("Also review auto-approved blocks below"), "viewSlider");
  await check(page.getByRole("combobox", { name: "Sort" }), "sort");
  const textDiff = page.getByRole("group", { name: "Original vs cleaned" });
  await check(page.getByTestId("view-text"), "textDiff", textDiff);
  await check(page.getByTestId("act-approve"), "approve");
  await check(page.getByTestId("act-edit"), "edit");
  await check(page.getByTestId("act-flag"), "flag");
  await check(page.getByTestId("act-skip"), "skip");
  await check(page.getByTestId("act-back"), "back");
  await check(page.getByTestId("rail-attach").first(), "attachFigure");
  await page.goto("/export");
  await check(page.getByTestId("override-reason"), "overrideReason");
  expect(seen.length).toBeGreaterThanOrEqual(16);
});

test("OB6 step indicator: 'here' on the current route; Export locked with the counts from the API", async ({ page, request }) => {
  const st = await api(request).get<ExportStatus>("/api/export/status");
  await page.goto("/scope");
  await waitForTree(page);
  const nav = page.getByRole("navigation", { name: "Screens" });
  await expect(nav.getByTestId("step-short-scope")).toHaveText("here");
  // "to review" is the gate partition's to_review; the lock names the flags that hold it (design 11 section 17)
  const queued = st.counts?.to_review ?? st.queued ?? 0;
  const holdFlags = (st.flag_blockers ?? []).length;
  expect((st.blockers ?? []).length, "the seeded project starts locked").toBeGreaterThan(0);
  const short = `locked: ${holdFlags > 0 ? plural(holdFlags, "open flag") : `${queued} to review`}`;
  await expect(nav.getByTestId("step-short-export")).toHaveText(short);
  await expect(nav.getByRole("link", { name: "Export" })).toHaveAccessibleDescription(/Step 4 of 4\. Locked: /);
  if (queued > 0) await expect(nav.getByTestId("step-short-verify")).toHaveText(`${queued} to review`);
  await nav.getByRole("link", { name: "Export" }).click();
  await expect(nav.getByTestId("step-short-export")).toHaveText("here");
});

test("OB7 the shortcut table in Help and USER_GUIDE.md both have one row per HOTKEYS entry", async ({ page }) => {
  await page.goto("/scope");
  await waitForTree(page);
  await page.keyboard.press("?");
  const dlg = page.getByRole("dialog", { name: "Help" });
  await dlg.getByRole("tab", { name: "Keyboard shortcuts" }).click();
  await expect(dlg.getByTestId("hotkey-row")).toHaveCount(Object.keys(HOTKEYS).length);
  const md = readFileSync(fileURLToPath(new URL("../../docs/USER_GUIDE.md", import.meta.url)), "utf8");
  const table = md.slice(md.indexOf("## Keyboard shortcuts"), md.indexOf("### Inside a widget"));
  expect(table.split("\n").filter((l) => l.startsWith("| ") && !l.startsWith("| Keys"))).toHaveLength(Object.keys(HOTKEYS).length);
  await page.keyboard.press("Escape");
});

test("OB8 reconciliation lines equal the API numbers on Scope and Verify", async ({ page, request }) => {
  const groups = await api(request).get<DocGroups[]>("/api/scope/groups");
  const blocks = await api(request).get<ScopeBlocks[]>("/api/scope/blocks");
  await page.goto("/scope");
  await waitForTree(page);
  for (const d of groups) {
    const bl = blocks.find((b) => b.doc_id === d.doc_id)!.blocks;
    const hf = bl.filter((b) => b.type === "header" || b.type === "footer").length;
    const inTopics = d.groups.topics.filter((t) => !t.is_unassigned).reduce((n, t) => n + t.block_ids.length, 0);
    const un = d.groups.topics.filter((t) => t.is_unassigned).reduce((n, t) => n + t.block_ids.length, 0);
    expect(bl.length, `${d.doc_id} identity`).toBe(hf + inTopics + un);
    await expect(page.locator(`[data-testid=doc-heading][data-doc='${d.doc_id}'] [data-testid=doc-reconcile]`)).toHaveText(
      `${bl.length} blocks found = ${inTopics} in topics + ${un} not placed + ${hf} page headers and footers, left out`,
    );
  }
  await expect(page.getByTestId("doc-reconcile-mismatch")).toHaveCount(0);
  const q = await api(request).get<QueuePage>("/api/verify/queue?limit=1");
  const c = q.counts;
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  // every term is the API's own field (to review = `queued`, never in_scope minus the others)
  expect(c.queued + c.auto_approved + c.approved + c.edited + c.flagged_open + c.rejected, "the API's buckets add up").toBe(c.in_scope);
  await expect(page.getByTestId("reconcile-review")).toContainText(
    `In scope ${c.in_scope} = ${c.queued} to review + ${c.auto_approved} auto-approved + ${c.approved + c.edited} done + ${c.flagged_open} flagged + ${c.rejected} rejected`,
  );
  await expect(page.getByTestId("reconcile-mismatch")).toHaveCount(0);
});

test("OB9 Export locked view lists the API's blockers; a blocker link opens that block in Verify", async ({ page, request }) => {
  const st = await api(request).get<ExportStatus>("/api/export/status");
  const blockers = st.blockers ?? [];
  expect(blockers.length).toBeGreaterThan(1);
  await page.goto("/export");
  await expect(page.getByRole("heading", { name: "Export is locked" })).toBeVisible();
  await expect(page.getByTestId("blocker-link")).toHaveText(blockers);
  const toReview = st.counts?.to_review ?? st.queued ?? 0;
  if (toReview > 0) await expect(page.getByTestId("reason-queued")).toContainText(`${toReview} block`);
  const target = blockers[1];
  await page.getByTestId("blocker-link").nth(1).click();
  await expect(page).toHaveURL(/\/verify$/);
  await expect(page.getByTestId("block-id")).toHaveText(target);
  await expect(page.getByTestId(`card-${target}`)).toHaveAttribute("aria-current", "true");
});

test("OB10 axe: no serious or critical issues with the panel open and a tooltip open", async ({ page }) => {
  const scan = async (label: string, disable: string[] = []) => {
    const r = await new AxeBuilder({ page }).disableRules(disable).analyze();
    const bad = r.violations
      .filter((v) => v.impact === "serious" || v.impact === "critical")
      .map((v) => `${label}: ${v.id} ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
    expect(bad, bad.join("\n")).toEqual([]);
  };
  await page.goto("/scope");
  await waitForTree(page);
  await expect(panel(page)).toBeVisible();
  await scan("scope+panel");
  await page.keyboard.press("Shift");
  await page.getByRole("navigation", { name: "Screens" }).getByRole("link", { name: "Verify" }).focus();
  await expect(page.getByRole("tooltip")).toBeVisible();
  await scan("scope+tooltip");
  await page.goto("/verify");
  await expect(currentCard(page)).toBeFocused();
  await expect(panel(page)).toBeVisible();
  // colour contrast on Verify is covered (and excluded) the same way as in VE8
  await scan("verify+panel", ["color-contrast"]);
  await page.keyboard.press("Shift");
  await page.getByTestId("act-approve").focus();
  await expect(page.getByRole("tooltip")).toBeVisible();
  await scan("verify+tooltip", ["color-contrast"]);
  await page.goto("/export");
  await expect(page.getByTestId("export-locked")).toBeVisible();
  await scan("export+panel");
  await page.goto("/agent");
  await expect(page.getByTestId("agent-flags")).toBeVisible();
  await scan("agent+panel");
});
