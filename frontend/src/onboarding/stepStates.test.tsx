// First-use report C10 (2026-10-30): the step rail is read from server truth (the export gate, its scope counts and
// the active jobs), never contradicts itself, and follows the reviewer's writes and running jobs without a reload.
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ExportStatus, ExportSummary } from "../api/schema";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { mountVerify } from "../verify/helpers.test-util";
import { stepStates } from "./StepNav";

const scope = (over: Partial<NonNullable<ExportStatus["counts"]>> = {}): NonNullable<ExportStatus["counts"]> => ({
  in_scope: 10,
  auto_approved: 4,
  approved: 6,
  edited: 0,
  rejected: 0,
  overridden: 0,
  blocking: 0,
  ...over,
});
const gate = (over: Partial<ExportStatus> = {}): ExportStatus => ({
  unlocked: true,
  open_flags: 0,
  queued: 0,
  blockers: [],
  overrides: [],
  summary: null,
  zip_path: null,
  counts: scope(),
  ...over,
});
const summary = { articles: 3, generated_at: "2026-10-30T12:30:49Z" } as unknown as ExportSummary;

describe("stepStates from server truth", () => {
  it("an empty project: Verify is not done and Export is not ready", () => {
    const s = stepStates("/scope", gate({ counts: scope({ in_scope: 0, auto_approved: 0, approved: 0 }) }));
    expect(s.verify.done).toBe(false);
    expect(s.verify.short).toBeNull();
    expect(s.export.done).toBe(false);
    expect(s.export.short).toBe("nothing to export yet");
  });
  it("a locked export never shows the checkmark, even after an earlier export", () => {
    const s = stepStates("/scope", gate({ unlocked: false, open_flags: 1, blockers: ["b-doc-p001-01"], summary }));
    expect(s.export.short).toBe("locked: 1 open flag");
    expect(s.export.done).toBe(false);
    expect(s.export.long).not.toContain("Done");
  });
  it("an export made from the current state is done and says so", () => {
    const s = stepStates("/scope", gate({ summary }));
    expect(s.export).toMatchObject({ short: "exported", done: true });
  });
  it("while scoring runs, Verify and Export wait for it instead of claiming done or ready", () => {
    const s = stepStates("/agent", gate(), { scoring: true });
    expect(s.verify).toMatchObject({ short: "scoring in progress", done: false });
    expect(s.export).toMatchObject({ short: "after scoring", done: false });
    expect(s.verify.long).toBe("Step 2 of 4. Scoring in progress.");
  });
  it("Verify is done only when blocks are in scope and none waits", () => {
    expect(stepStates("/scope", gate()).verify.done).toBe(true);
    expect(stepStates("/scope", gate({ queued: 2, unlocked: false, blockers: ["b-doc-p001-01"] })).verify).toMatchObject({ short: "2 to review", done: false });
  });
});

describe("the rail follows the server without a reload", () => {
  it("re-reads the export gate after a Verify decision is saved", async () => {
    const { f, scope: fake, r } = await mountVerify(3, undefined, { exportStatus: gate({ queued: 3, unlocked: false, blockers: ["b-doc-p001-01"] }) });
    const nav = screen.getByRole("navigation", { name: "Screens" });
    // on Verify the Verify step reads "here"; the Export step carries the count
    await waitFor(() => expect(within(nav).getByTestId("step-short-export")).toHaveTextContent("locked: 3 to review"));
    fake.exportStatus = gate({ queued: 2, unlocked: false, blockers: ["b-doc-p001-02"] });
    await r.user.keyboard("a");
    await waitFor(() => expect(f.actions).toHaveLength(1));
    await waitFor(() => expect(within(nav).getByTestId("step-short-export")).toHaveTextContent("locked: 2 to review"));
  });
  it("re-reads the export gate when a running job finishes a step, and shows scoring meanwhile", async () => {
    const f = installFake({ exportStatus: gate({ counts: scope({ in_scope: 0, auto_approved: 0, approved: 0 }) }) });
    const run = (done: number) => makeJob({ id: "r", kind: "run", plan: { to: "score2" }, node: "score", doc: "alpha", units_done: done, units_total: 4 });
    f.jobPolls = [[run(1)], [run(1)], [run(2)], [run(2)], [run(2)]];
    renderApp("/scope");
    const nav = screen.getByRole("navigation", { name: "Screens" });
    await waitFor(() => expect(within(nav).getByTestId("step-short-verify")).toHaveTextContent("scoring in progress"));
    const reads = () => f.log.filter((l) => l === "GET /api/export/status").length;
    const before = reads();
    await waitFor(() => expect(reads()).toBeGreaterThan(before), { timeout: 5000 });
  }, 15000);
});
