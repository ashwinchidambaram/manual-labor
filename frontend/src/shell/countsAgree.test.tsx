// Design 11 section 17 (Dana's second run, shots 048 and 107 to 112): the step rail, the next-step card and the Verify
// status strip say the same numbers, all read from one export status. A block an override covers is never "to review";
// a block being scored is never "waiting for you".
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ExportStatus } from "../api/schema";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { counts, installVerifyFake, makeQueueItem, ready } from "../test/verifyFake";

type Counts = NonNullable<ExportStatus["counts"]>;

function status(c: Counts, over: Partial<ExportStatus> = {}): ExportStatus {
  const blocking = c.to_review + c.flagged;
  return {
    unlocked: c.overridden + blocking === 0,
    open_flags: c.flagged,
    queued: c.overridden + c.to_review,
    blockers: Array.from({ length: Math.min(20, blocking) }, (_, i) => makeQueueItem(i + 1).block_id),
    flag_blockers: c.flagged ? [{ flag_id: "flag-000001", block_id: makeQueueItem(1).block_id, category: "wrong_text", note: null }] : [],
    overrides: [],
    summary: null,
    zip_path: null,
    counts: c,
    ...over,
  };
}

/** The Verify queue's own counts at the same moment: status buckets, overrides not known. */
function reviewCountsOf(c: Counts) {
  return counts({
    in_scope: c.in_scope,
    auto_approved: c.auto_approved,
    approved: c.approved,
    edited: c.edited,
    rejected: c.rejected,
    flagged_open: c.flagged,
    queued: c.to_review + c.overridden,
  });
}

const n = (el: HTMLElement): number => Number((el.textContent ?? "").replace(/\D/g, ""));

/** "N to review" / "N blocks ... wait" in a sentence, or 0 when it names none. */
function waiting(text: string): number {
  const m = /(\d+) (?:to review|blocks? (?:still )?waits?)/.exec(text);
  return m ? Number(m[1]) : 0;
}

async function readAll(c: Counts) {
  const f = installFake({ exportStatus: status(c) });
  const v = installVerifyFake({ counts: reviewCountsOf(c) });
  v.items = Array.from({ length: c.to_review + c.overridden }, (_, i) => makeQueueItem(i + 1));
  const r = renderApp("/export");
  // the rail on another screen carries Verify's count; the next-step card says the Export step's sentence
  const nav = screen.getByRole("navigation", { name: "Screens" });
  await waitFor(() => expect(screen.getByTestId("export-screen")).toBeInTheDocument());
  await waitFor(() => expect(document.getElementById("step-state-verify")?.textContent).toMatch(/Step 2 of 4\. ./));
  const rail = document.getElementById("step-state-verify")!.textContent ?? "";
  const railExport = document.getElementById("step-state-export")!.textContent ?? "";
  const card = screen.getByTestId("next-step-text").textContent ?? "";
  await r.router.navigate("/verify");
  await screen.findByTestId(`card-${v.items[0].block_id}`);
  await waitFor(() => expect(screen.getByTestId("reconcile-review").textContent).toContain(`In scope ${c.in_scope}`));
  return { f, nav, rail, railExport, card, strip: screen.getByTestId("reconcile-review").textContent ?? "" };
}

describe("one count of what waits for a person", () => {
  it("after every unflagged block was overridden: 0 to review everywhere, the overrides named as such", async () => {
    const c: Counts = { in_scope: 173, auto_approved: 60, approved: 7, edited: 1, rejected: 0, overridden: 104, to_review: 0, flagged: 1, blocking: 1 };
    const s = await readAll(c);
    expect(waiting(s.rail)).toBe(0);
    expect(waiting(s.card)).toBe(0);
    expect(n(screen.getByTestId("cnt-queued"))).toBe(0);
    // what was said before: "105 to review", "105 blocks still wait for review", "105 waiting for you"
    for (const t of [s.rail, s.railExport, s.card, s.strip]) expect(t).not.toMatch(/10[45] (to review|blocks? still wait|waiting)/);
    expect(s.rail).toContain("104 overridden");
    expect(n(screen.getByTestId("cnt-overridden"))).toBe(104);
    expect(n(screen.getByTestId("cnt-flagged"))).toBe(1);
    expect(s.card).toContain("1 open flag still blocks the export");
    expect(s.strip).toBe("In scope 173 = 0 to review + 104 overridden + 60 auto-approved + 8 done + 1 flagged + 0 rejected");
  });

  it("part way through the overrides: the same numbers on the rail, the card and the strip", async () => {
    const c: Counts = { in_scope: 173, auto_approved: 60, approved: 7, edited: 1, rejected: 0, overridden: 40, to_review: 64, flagged: 1, blocking: 65 };
    const s = await readAll(c);
    expect(waiting(s.rail)).toBe(64);
    expect(waiting(s.card)).toBe(64);
    expect(waiting(s.railExport)).toBe(64);
    expect(n(screen.getByTestId("cnt-queued"))).toBe(64);
    expect(n(screen.getByTestId("cnt-overridden"))).toBe(40);
    expect(s.strip).toBe("In scope 173 = 64 to review + 40 overridden + 60 auto-approved + 8 done + 1 flagged + 0 rejected");
    // the rail on Verify carries Export's reasons with the same count
    expect(within(s.nav).getByTestId("step-short-export")).toHaveTextContent("locked: 1 open flag");
  });

  it("an empty, filtered Verify list after the overrides: the next step names the flag, never blocks 'to review'", async () => {
    const c: Counts = { in_scope: 173, auto_approved: 60, approved: 7, edited: 1, rejected: 0, overridden: 104, to_review: 0, flagged: 1, blocking: 1 };
    installFake({ exportStatus: status(c) });
    installVerifyFake({ counts: reviewCountsOf(c) }); // the document filter leaves nothing in this list
    renderApp("/verify");
    const next = await screen.findByTestId("queue-next");
    await waitFor(() => expect(next).toHaveTextContent("Next: hand the 1 flagged block to the Agent, or export with an override."));
    expect(next).not.toHaveTextContent(/need review|104/);
    expect(screen.getByTestId("queue-empty")).not.toHaveTextContent("Nothing in this list");
  });

  it("while scoring runs, blocks are being scored: nothing is called waiting before the list has it", async () => {
    // the gate already counts a document the Verify list has not read yet (two reads, one document finished between them)
    const f = installFake({
      exportStatus: status({ in_scope: 60, auto_approved: 0, approved: 0, edited: 0, rejected: 0, overridden: 0, to_review: 60, flagged: 0, blocking: 60 }),
    });
    f.jobPolls = [[makeJob({ id: "r", kind: "run", plan: { to: "score2" }, node: "clean", doc: "x200-manual", units_done: 1, units_total: 6 })]];
    installVerifyFake({ counts: counts(), docs: [{ ...ready("pump"), state: "pending", waiting_for: "clean" }] });
    renderApp("/verify");
    const nav = screen.getByRole("navigation", { name: "Screens" });
    await waitFor(() => expect(within(nav).getByTestId("step-short-export")).toHaveTextContent("after scoring"));
    await waitFor(() => expect(screen.getByTestId("next-step-text")).toHaveTextContent(/being scored/));
    expect(screen.getByTestId("next-step-text").textContent).not.toMatch(/wait/);
    expect(n(screen.getByTestId("cnt-queued"))).toBe(0);
    expect(screen.getByTestId("reconcile-review").textContent).toBe("In scope 0 = 0 to review + 0 auto-approved + 0 done + 0 flagged + 0 rejected");
  });
});
