// Frontend review 2 (2026-10-30): the short-window budget of the job bar and the flag notice (M1), reading jobs named
// as reading (M2), no "re-scoring" without a job (M3), one sentence for how a flag is resolved (M4), and the Export
// screen's focus, live regions, names and wording (L1 to L4).
import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { AgentItemView, ExportStatus, ExportSummary, Flag } from "./api/schema";
import { stepStates } from "./onboarding/StepNav";
import { makeJob } from "./test/fixtures";
import { renderApp } from "./test/render";
import { installFake, server } from "./test/server";
import { counts, installVerifyFake, makeBlockDetail, makeQueueItem, ready, seedQueue } from "./test/verifyFake";
import { mountVerify } from "./verify/helpers.test-util";
import { FLAG_RESOLUTION } from "./verify/labels";

const FLAGGED = "b-doc-p002-07";
const flag: Flag = { id: "flag-000001", category: "wrong_text", target_id: FLAGGED, note: "torque looks wrong", status: "open", created_at: "2026-10-30T12:20:00Z", resolution: null, resolved_at: null };
const item: AgentItemView = { flag, target_id: FLAGGED, round: 1, attempts: 1, pending_proposal_id: null, last_outcome: "no_proposal", last_detail: null };

const locked = (over: Partial<ExportStatus> = {}): ExportStatus => ({
  unlocked: false,
  open_flags: 0,
  queued: 3,
  blockers: ["b-doc-p001-01", "b-doc-p001-02", "b-doc-p001-03"],
  overrides: [],
  summary: null,
  zip_path: null,
  ...over,
});
const fb = (n: number) => ({ flag_id: `flag-00000${n}`, block_id: `b-doc-p001-0${n}`, category: "wrong_text" as const, note: null });

describe("M1 the job bar on a short window", () => {
  it("publishes its height as --jobs-bar while shown, keeps the whole step sentence in a title, and removes it after", async () => {
    const job = makeJob({ id: "r1", kind: "run", plan: { to: "score2" }, node: "score", doc: "alpha", units_done: 1, units_total: 4, step_done: 3, step_total: 87, step_unit: "block" });
    installFake({ jobPolls: [[job], [job], []] });
    renderApp("/export");
    const step = await screen.findByTestId("job-step", undefined, { timeout: 5000 });
    expect(step).toHaveTextContent("Step 2 of 4: Scoring alpha.pdf, 3 of 87 blocks");
    expect(step).toHaveAttribute("title", "Step 2 of 4: Scoring alpha.pdf, 3 of 87 blocks");
    expect(document.documentElement.style.getPropertyValue("--jobs-bar")).toMatch(/^\d+px$/);
    await waitFor(() => expect(screen.queryByTestId("jobs-bar")).toBeNull(), { timeout: 5000 });
    expect(document.documentElement.style.getPropertyValue("--jobs-bar")).toBe("");
  }, 15000);
});

describe("M1 and M4 the flag notice on the Verify card", () => {
  it("is one summary line with a Details toggle; the details hold the note and the one sentence on how a flag is resolved", async () => {
    const s = await mountVerify(
      2,
      (f) => {
        f.details[FLAGGED] = makeBlockDetail(makeQueueItem(7, { block_id: FLAGGED, page: 2, status: "flagged" }), { flags: [flag] });
        f.cursor = { ...f.cursor, current_block_id: FLAGGED };
        server.use(http.get("*/api/agent/items", () => HttpResponse.json([item])));
      },
      { flags: [flag] },
    );
    const notice = await screen.findByTestId("verify-flag");
    const summary = within(notice).getByTestId("verify-flag-summary");
    expect(summary).toHaveTextContent("Flagged: Wrong text");
    await waitFor(() => expect(within(summary).getByTestId("verify-flag-agent")).toHaveTextContent("tried once"));
    const toggle = within(notice).getByRole("button", { name: "Details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const details = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(notice).toContainElement(details);
    expect(details).toHaveTextContent("torque looks wrong");
    expect(details).toHaveTextContent(FLAG_RESOLUTION);
    await s.r.user.click(toggle);
    expect(within(notice).getByRole("button", { name: "Fewer details" })).toHaveAttribute("aria-expanded", "true");
  }, 15000);
});

describe("M4 one sentence for how a flag is resolved, true to the server", () => {
  it("names every way out the server has, and says a block override never covers a flag", () => {
    expect(FLAG_RESOLUTION).toMatch(/approve or edit the block in Verify/);
    expect(FLAG_RESOLUTION).toMatch(/accept the agent's fix on the Agent screen/);
    expect(FLAG_RESOLUTION).toMatch(/override that names the flag on the Export screen/);
    // the command line is documented in README, never named in the screens (design 11 section 19)
    expect(FLAG_RESOLUTION).not.toMatch(/labor export|--override/);
    expect(FLAG_RESOLUTION).toMatch(/override of the block alone never covers a flag/);
  });
  it("the flag dialog says it", async () => {
    const s = await mountVerify(2);
    await s.r.user.keyboard("f");
    expect(await screen.findByTestId("flag-next")).toHaveTextContent(FLAG_RESOLUTION);
  });
  it("the Export screen says it in the locked reasons and above the flag decisions", async () => {
    installFake({ exportStatus: locked({ open_flags: 1, flag_blockers: [fb(2)] }) });
    renderApp("/export");
    expect(await screen.findByTestId("reason-flags")).toHaveTextContent(FLAG_RESOLUTION);
    expect(screen.getByTestId("flag-overrides")).toHaveTextContent(FLAG_RESOLUTION);
  });
});

describe("M2 a reading job is called reading, not scoring", () => {
  it("the rail: Verify 'reading manuals', Export 'after reading'", () => {
    const g = stepStates("/agent", { unlocked: true, open_flags: 0, queued: 0, blockers: [], overrides: [], summary: null, zip_path: null }, { scoring: true, reading: true });
    expect(g.verify).toMatchObject({ short: "reading manuals", done: false });
    expect(g.verify.long).toBe("Step 2 of 4. Reading manuals.");
    expect(g.export).toMatchObject({ short: "after reading", done: false });
    expect(g.export.long).toBe("Step 4 of 4. Waits for reading to finish.");
  });
  it("the rail on screen while an upload is read", async () => {
    installFake({ jobPolls: [[makeJob({ id: "u", kind: "ingest_run", plan: { to: "group" }, node: "parse", doc: "alpha" })]] });
    renderApp("/scope");
    const nav = screen.getByRole("navigation", { name: "Screens" });
    await waitFor(() => expect(within(nav).getByTestId("step-short-verify")).toHaveTextContent("reading manuals"));
    expect(within(nav).getByTestId("step-short-export")).toHaveTextContent("after reading");
  }, 15000);
  it("Verify's empty list while a manual is read: 'Reading in progress', and its blocks come after it is scored from Scope", async () => {
    await mountVerify(
      0,
      (f) => {
        f.docs = [{ doc_id: "alpha", state: "pending", stale: false, waiting_for: "figures" }];
      },
      { jobPolls: [[makeJob({ id: "s2", kind: "ingest_run", plan: { to: "group" }, node: "group", doc: "alpha", units_done: 3, units_total: 4, step_done: null, step_total: null, step_unit: null })]] },
    ).catch(() => undefined);
    const empty = await screen.findByTestId("queue-empty", undefined, { timeout: 5000 });
    await within(empty).findByTestId("queue-scoring-count");
    expect(empty).toHaveAttribute("data-variant", "reading");
    expect(empty).toHaveTextContent("Reading in progress");
    expect(within(empty).getByTestId("queue-scoring-count")).toHaveTextContent("Reading in progress, step 4 of 4: Grouping alpha.pdf into topics (working, no estimate)");
    expect(empty).toHaveTextContent("Reading puts no block in this list: blocks come here after scoring. Confirm your scope on the Scope screen once reading finishes.");
    expect(empty).not.toHaveTextContent("finishes scoring");
    expect(screen.getByTestId("queue-footer")).toHaveTextContent("1 document being read");
  });
});

describe("M3 're-scoring' only while a job re-scores the manual", () => {
  it("a stale manual with no job is 'scores out of date', with the way to Scope; the card says the same", async () => {
    await mountVerify(2, (f) => {
      f.docs = [ready("doc"), { doc_id: "redo", state: "ready", stale: true, waiting_for: null }];
      f.items = [makeQueueItem(1), makeQueueItem(2, { stale_doc: true, doc_id: "redo" })];
    });
    const chips = await screen.findAllByTestId("doc-chip");
    expect(chips.map((c) => c.textContent)).toEqual(["redo: scores out of date"]);
    expect(screen.getByRole("link", { name: "Score it on Scope" })).toHaveAttribute("href", "/scope");
    const card = screen.getByTestId("card-b-doc-p001-02");
    expect(card).toHaveTextContent("scores out of date");
    expect(card).not.toHaveTextContent("re-scoring");
  });
  it("with a scoring job covering it, the chip and the card say 're-scoring'", async () => {
    await mountVerify(
      2,
      (f) => {
        f.docs = [ready("doc"), { doc_id: "redo", state: "ready", stale: true, waiting_for: null }];
        f.items = [makeQueueItem(1), makeQueueItem(2, { stale_doc: true, doc_id: "redo" })];
      },
      { jobPolls: [[makeJob({ id: "rs", kind: "run", plan: { to: "score2", docs: ["redo"] }, node: "clean", doc: "redo" })]] },
    );
    await waitFor(() => expect(screen.getAllByTestId("doc-chip").map((c) => c.textContent)).toEqual(["redo: re-scoring"]));
    expect(screen.getByTestId("card-b-doc-p001-02")).toHaveTextContent("re-scoring");
    expect(screen.queryByRole("link", { name: "Score it on Scope" })).toBeNull();
  });
  it("a reading job does not make a stale manual 're-scoring'", async () => {
    await mountVerify(
      2,
      (f) => {
        f.docs = [ready("doc"), { doc_id: "redo", state: "ready", stale: true, waiting_for: null }];
      },
      { jobPolls: [[makeJob({ id: "u", kind: "ingest_run", plan: { to: "group" }, node: "parse", doc: "new" })]] },
    );
    await waitFor(() => expect(screen.getAllByTestId("doc-chip").map((c) => c.textContent)).toEqual(["redo: scores out of date"]));
  });
});

describe("M5 no totals note from counts the screen never had", () => {
  it("mounting while a job ends before the queue answers makes no 'more blocks queued' note", async () => {
    const job = makeJob({ id: "s", kind: "run", plan: { to: "score2" }, node: "score2", doc: "doc", units_done: 1, units_total: 2 });
    const scope = installFake({ jobPolls: [[job], []], jobById: { s: { ...job, status: "done", progress: 1 } } });
    const f = installVerifyFake();
    seedQueue(f, 3);
    f.counts = counts({ in_scope: 160, auto_approved: 53, queued: 107, pending: 107 });
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    server.use(
      http.get("*/api/verify/queue", async () => {
        await gate;
        return HttpResponse.json({ items: f.items, total: f.items.length, counts: f.counts, docs: f.docs, cursor: f.cursor });
      }),
    );
    renderApp("/verify");
    // the job is seen, then seen gone, before the queue has answered
    await waitFor(() => expect(scope.requests.length).toBeGreaterThanOrEqual(2), { timeout: 5000 });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    release();
    await screen.findByTestId("card-b-doc-p001-01");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 300));
    });
    expect(screen.queryByTestId("review-change")).toBeNull();
    expect(screen.getByTestId("review-change-live")).toHaveTextContent("");
  }, 15000);
});

describe("L1 Export: focus stays with the reader, and results are announced", () => {
  it("after 'Export despite' succeeds, focus goes to the next flag's reason; after the last flag, to the locked heading", async () => {
    const f = installFake({ exportStatus: locked({ open_flags: 2, flag_blockers: [fb(1), fb(2)] }) });
    server.use(
      http.post("*/api/export/override", async ({ request }) => {
        const b = (await request.json()) as { flag_id: string };
        const left = (f.exportStatus.flag_blockers ?? []).filter((x) => x.flag_id !== b.flag_id);
        f.exportStatus = { ...f.exportStatus, open_flags: left.length, flag_blockers: left };
        return HttpResponse.json(f.exportStatus);
      }),
    );
    const { user } = renderApp("/export");
    const first = await screen.findByRole("textbox", { name: /Reason for exporting b-doc-p001-01 despite its flag/ });
    await user.type(first, "checked on paper");
    await user.click(screen.getByRole("button", { name: "Export b-doc-p001-01 despite its flag" }));
    const second = await screen.findByRole("textbox", { name: /Reason for exporting b-doc-p001-02 despite its flag/ });
    await waitFor(() => expect(second).toHaveFocus());
    expect(screen.getByTestId("export-live")).toHaveTextContent("Override recorded for the flag on b-doc-p001-01. 1 flag still needs a decision.");
    await user.type(second, "also checked");
    await user.click(screen.getByRole("button", { name: "Export b-doc-p001-02 despite its flag" }));
    await waitFor(() => expect(screen.queryByTestId("flag-overrides")).toBeNull());
    await waitFor(() => expect(screen.getByRole("heading", { name: "Export is locked" })).toHaveFocus());
  });

  it("after an export that spent its overrides, focus goes to the 'Last export' heading and the result is announced", async () => {
    const summary = {
      articles: 7,
      figures: 3,
      pages_covered: 12,
      docs: 2,
      review: { blocks: 64, approved: 20, auto_approved: 40, edited: 0, numbers_verified: 6, overrides: 4, total_blocks: 64, left_out: {} },
      warnings: [],
      zip_bytes: 20480,
      zip_sha256: "ab".repeat(32),
      generated_at: "2026-10-29T10:00:00Z",
    } as ExportSummary;
    const f = installFake({ exportStatus: { ...locked({ blockers: [], queued: 0 }), unlocked: false } });
    server.use(
      http.post("*/api/export", () => {
        f.exportStatus = locked({ summary });
        return HttpResponse.json(makeJob({ id: "exp", kind: "export", status: "queued" }), { status: 202 });
      }),
    );
    f.jobById = { exp: makeJob({ id: "exp", kind: "export", status: "done" }) };
    const { user } = renderApp("/export");
    const live = await screen.findByTestId("export-live");
    expect(live).toHaveAttribute("role", "status");
    expect(live).toHaveTextContent("");
    await user.click(await screen.findByTestId("export-start"));
    await screen.findByTestId("export-locked");
    await waitFor(() => expect(screen.getByRole("heading", { name: /Last export/ })).toHaveFocus());
    expect(screen.getByTestId("export-live")).toHaveTextContent("Export finished. Download the zip below.");
  });

  it("the agent pass outcome lands in a live region that was already on screen", async () => {
    const f = installFake({ flags: [flag] });
    server.use(
      http.get("*/api/agent/items", () => HttpResponse.json([{ ...item, attempts: 0, last_outcome: null }])),
      http.post("*/api/agent/run", () => HttpResponse.json(makeJob({ id: "ag1", kind: "agent" }), { status: 202 })),
    );
    f.jobById = { ag1: makeJob({ id: "ag1", kind: "agent", status: "done" }) };
    const { user } = renderApp("/agent");
    const live = await screen.findByTestId("agent-run-status");
    expect(live).toHaveAttribute("role", "status");
    await user.click(await screen.findByTestId("agent-run"));
    await waitFor(() => expect(live).toHaveTextContent("Agent pass on your flags finished."), { timeout: 4000 });
    expect(screen.getByTestId("agent-run-outcome")).toBeInTheDocument();
  });
});

describe("L2 every flag decision has its own name", () => {
  it("names the button by its block, and the overrides list names a flag override's block", async () => {
    installFake({
      flags: [{ ...flag, id: "flag-000009", target_id: "b-doc-p001-09" }],
      exportStatus: locked({
        open_flags: 2,
        flag_blockers: [fb(1), fb(2)],
        overrides: [{ flag_id: "flag-000009", target_id: null, reason: "seen", at: "2026-10-30T10:00:00Z" }],
      }),
    });
    renderApp("/export");
    expect(await screen.findByRole("button", { name: "Export b-doc-p001-01 despite its flag" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export b-doc-p001-02 despite its flag" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("overrides")).toHaveTextContent("flag flag-000009 on b-doc-p001-09"));
  });
});

describe("L3 the override form counts what it records", () => {
  it("says how many unflagged blocks it covers, and that a block override never covers a flag", async () => {
    installFake({ exportStatus: locked({ open_flags: 1, flag_blockers: [fb(2)] }) });
    renderApp("/export");
    const form = await screen.findByTestId("override-form");
    // an older status without the scope partition: the listed unflagged blockers are what the form can count
    expect(form).toHaveTextContent("Records one override for each of the 2 blocks still to review (every one, not only those listed)");
    expect(within(form).getByTestId("override-submit")).toHaveTextContent("Override the remaining 2 with this reason");
    expect(within(form).getByTestId("override-left-out")).toHaveTextContent(
      "1 flagged block is left out: a block override never covers a flag; each flag needs its own decision, below.",
    );
  });
});

describe("L4 the blocker list does not flash while overrides are recorded", () => {
  it("keeps the named list on screen when the blockers shrink after a write", async () => {
    const f = installFake({ exportStatus: locked({ open_flags: 1, flag_blockers: [fb(2)] }) });
    const titles = (ids: string[]) => ids.map((id) => ({ block_id: id, doc_id: "doc", page: 1, type: "paragraph", section_title: "Torque values" }));
    let titleReads = 0;
    let release: () => void = () => undefined;
    server.use(
      http.get("*/api/verify/titles", async ({ request }) => {
        titleReads++;
        const ids = new URL(request.url).searchParams.getAll("ids");
        if (titleReads > 1) await new Promise<void>((r) => (release = r));
        return HttpResponse.json(titles(ids));
      }),
      http.post("*/api/export/override", async ({ request }) => {
        const b = (await request.json()) as { target_id: string };
        f.exportStatus = { ...f.exportStatus, blockers: (f.exportStatus.blockers ?? []).filter((x) => x !== b.target_id) };
        return HttpResponse.json(f.exportStatus);
      }),
    );
    const { user } = renderApp("/export");
    await waitFor(() => expect(screen.getByTestId("blocker-list")).toBeVisible());
    await user.type(screen.getByTestId("override-reason"), "pilot");
    await user.click(screen.getByTestId("override-submit"));
    await waitFor(() => expect(titleReads).toBeGreaterThan(1));
    expect(screen.queryByTestId("blocker-list-loading")).toBeNull();
    expect(screen.getByTestId("blocker-list")).toBeVisible();
    release();
  });
});
