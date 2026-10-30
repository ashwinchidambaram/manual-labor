// First-use report C9 (2026-10-30): an empty queue while scoring is queued or running says so, with the worker's
// count, and never "All caught up" or "Go to Export"; a document nobody is scoring is "not scored yet", not "preparing".
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeJob } from "../test/fixtures";
import { counts, ready } from "../test/verifyFake";
import { mountVerify } from "./helpers.test-util";

const pending = (id: string, waiting = "score") => ({ doc_id: id, state: "pending" as const, stale: false, waiting_for: waiting });

describe("Verify empty state while scoring", () => {
  it("a running score step: 'Scoring in progress, N of M blocks scored' with the file name; no caught-up, no export link", async () => {
    await mountVerify(
      0,
      (f) => {
        f.docs = [pending("alpha")];
        f.counts = counts({});
      },
      { jobPolls: [[makeJob({ id: "s1", kind: "run", plan: { to: "score2" }, node: "score", doc: "alpha", units_done: 2, units_total: 6, step_done: 40, step_total: 87, step_unit: "block" })]] },
    ).catch(() => undefined);
    const empty = await screen.findByTestId("queue-empty", undefined, { timeout: 5000 });
    await within(empty).findByTestId("queue-scoring-count");
    expect(empty).toHaveAttribute("data-variant", "scoring");
    expect(within(empty).getByTestId("queue-scoring-count")).toHaveTextContent("Scoring in progress, 40 of 87 blocks scored in alpha.pdf");
    expect(empty).not.toHaveTextContent("All caught up");
    expect(within(empty).queryByRole("link", { name: "Go to Export" })).toBeNull();
    expect(screen.getByTestId("queue-footer")).not.toHaveTextContent("You can start now");
  });

  it("another step of the scoring job is named with its own count; a step without one says it has no estimate", async () => {
    await mountVerify(
      0,
      (f) => {
        f.docs = [pending("alpha", "figures")];
      },
      // a scoring run on its grouping step (a reading-only job, an upload, says "Reading in progress": review2.test.tsx)
      { jobPolls: [[makeJob({ id: "s2", kind: "run", plan: { to: "score2" }, node: "group", doc: "alpha", units_done: 3, units_total: 4, step_done: null, step_total: null, step_unit: null })]] },
    ).catch(() => undefined);
    const empty = await screen.findByTestId("queue-empty", undefined, { timeout: 5000 });
    await within(empty).findByTestId("queue-scoring-count");
    expect(within(empty).getByTestId("queue-scoring-count")).toHaveTextContent("Scoring in progress, step 4 of 4: Grouping alpha.pdf into topics (working, no estimate)");
  });

  it("a queued scoring job also counts: nothing is ready yet", async () => {
    await mountVerify(0, (f) => (f.docs = [pending("alpha")]), {
      jobPolls: [[makeJob({ id: "q", status: "queued", kind: "run", plan: { to: "score2" }, node: null, doc: null, units_done: 0, units_total: 0, progress: 0 })]],
    }).catch(() => undefined);
    const empty = await screen.findByTestId("queue-empty", undefined, { timeout: 5000 });
    await within(empty).findByTestId("queue-scoring-count");
    expect(within(empty).getByTestId("queue-scoring-count")).toHaveTextContent("Scoring in progress, waiting to start");
    expect(empty).not.toHaveTextContent("All caught up");
  });

  it("a pending document with no job running is 'not scored yet', with the way to start it; nothing claims work", async () => {
    await mountVerify(0, (f) => {
      f.docs = [ready("doc"), pending("late")];
      f.counts = counts({ flagged_open: 2 });
    }).catch(() => undefined);
    const empty = await screen.findByTestId("queue-empty", undefined, { timeout: 5000 });
    expect(empty).toHaveAttribute("data-variant", "not-scored");
    expect(empty).toHaveTextContent("1 document is not scored yet");
    expect(within(empty).getByRole("link", { name: "Go to Scope" })).toBeInTheDocument();
    expect(empty).not.toHaveTextContent("All caught up");
    expect(screen.getByTestId("queue-footer")).toHaveTextContent("1 document not scored yet");
    expect(screen.getByTestId("queue-footer")).not.toHaveTextContent("still preparing");
  });
});
