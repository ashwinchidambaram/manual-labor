// First-use report D (2026-10-30): "Totals moved 107 -> 109 to check, 53 -> 51 auto-approved" with no word why. When a
// job finishes and the review estimate moves, the summary says why, from the server's counts before and after.
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { makeJob } from "../test/fixtures";
import { server } from "../test/server";
import { counts } from "../test/verifyFake";
import { mountVerify } from "./helpers.test-util";
import { reviewChangeNote } from "./reviewChange";

describe("reviewChangeNote (pure)", () => {
  it("says how many more blocks are queued and why", () => {
    const before = counts({ in_scope: 160, auto_approved: 53 });
    expect(reviewChangeNote(before, counts({ in_scope: 160, auto_approved: 51 }), "scoring")).toBe(
      "2 more blocks queued after scoring finished (2 fewer cleared by the checks).",
    );
    expect(reviewChangeNote(before, counts({ in_scope: 161, auto_approved: 53 }), "reading")).toBe("1 more block queued after reading finished (1 more in scope).");
    expect(reviewChangeNote(before, counts({ in_scope: 160, auto_approved: 56 }), "scoring")).toBe(
      "3 fewer blocks to review after scoring finished (3 more cleared by the checks).",
    );
  });
  it("a reviewer's own decisions never move the estimate, so they make no note", () => {
    const before = counts({ in_scope: 10, auto_approved: 4, queued: 6 });
    expect(reviewChangeNote(before, counts({ in_scope: 10, auto_approved: 4, approved: 2, queued: 4 }), "scoring")).toBeNull();
  });
});

describe("the Verify summary explains a moved total", () => {
  it("after scoring finishes: '2 more blocks queued after scoring finished'", async () => {
    const job = makeJob({ id: "s", kind: "run", plan: { to: "score2" }, node: "score2", doc: "doc", units_done: 1, units_total: 2 });
    const { f } = await mountVerify(
      3,
      (vf) => {
        vf.counts = counts({ in_scope: 10, auto_approved: 7, queued: 3 });
      },
      { jobPolls: [[job], [job], []] },
    );
    server.use(
      http.get("*/api/jobs/:id", () => {
        // the job's re-score moved two blocks from "cleared by the checks" to "waiting for you"
        f.counts = counts({ in_scope: 10, auto_approved: 5, queued: 5 });
        return HttpResponse.json({ ...job, status: "done", progress: 1 });
      }),
    );
    const note = await screen.findByTestId("review-change", undefined, { timeout: 8000 });
    await waitFor(() => expect(note).toHaveTextContent("2 more blocks queued after scoring finished (2 fewer cleared by the checks)."));
  }, 15000);
});
