import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { ExportStatus } from "../api/schema";
import { stepStates } from "../onboarding/StepNav";
import { defaultNextStep } from "../shell/nextStep";
import { makeJob, makeSources } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";

// Review D3: a project whose documents have no current scores (never run, or scored by an older version) has an
// empty gate. The screen says it needs a run instead of "Ready to export". Design 11 section 20.17: the server reports
// such a project as locked (`unlocked: false`), and the rail and the next-step card say why.
const notReady = (over: Partial<ExportStatus> = {}): ExportStatus => ({
  unlocked: false,
  open_flags: 0,
  queued: 0,
  blockers: [],
  overrides: [],
  not_ready: ["clean", "scanned"],
  summary: null,
  zip_path: null,
  ...over,
});
const counts = { in_scope: 4, auto_approved: 2, approved: 2, edited: 0, rejected: 0, overridden: 0, blocking: 0, to_review: 0, flagged: 0, faith_failed: 0 };

describe("ExportScreen, documents not scored yet", () => {
  it("says which documents need a run and offers no export", async () => {
    installFake({ exportStatus: notReady() });
    renderApp("/export");
    const note = await screen.findByTestId("export-not-ready");
    expect(note).toHaveTextContent("Not ready to export: clean, scanned have not been through scoring and cleanup with this version yet.");
    expect(note).toHaveTextContent("Run the pipeline from the Scope screen (or labor run), then come back.");
    expect(screen.queryByTestId("export-ready")).toBeNull();
    expect(screen.queryByTestId("export-start")).toBeNull();
  });
  it("an empty list leaves the ready view as it was", async () => {
    installFake({ exportStatus: notReady({ not_ready: [], unlocked: true }) });
    renderApp("/export");
    expect(await screen.findByTestId("export-ready")).toHaveTextContent("Ready to export");
    expect(screen.queryByTestId("export-not-ready")).toBeNull();
  });
  it("offers no override while a document needs a run, even with blockers in the ready ones", async () => {
    installFake({ exportStatus: notReady({ not_ready: ["scanned"], queued: 2, blockers: ["b-clean-p001-01", "b-clean-p001-02"], counts: { ...counts, blocking: 2, to_review: 2, approved: 0 } }) });
    renderApp("/export");
    expect(await screen.findByTestId("export-not-ready")).toHaveTextContent("Not ready to export: scanned has not been through scoring and cleanup with this version yet.");
    expect(screen.queryByTestId("override-form")).toBeNull();
    expect(screen.queryByTestId("export-locked")).toBeNull();
  });
  it("a 409 naming documents that need a run shows the not-ready line", async () => {
    const f = installFake({ exportStatus: notReady({ not_ready: [], unlocked: true, counts }) });
    server.use(
      http.post("*/api/export", () => {
        f.exportStatus = notReady({ not_ready: ["scanned"], counts });
        return HttpResponse.json(
          { detail: "export is locked: 1 document not scored by this version (scanned): run the pipeline first", code: "export_locked", open_flags: 0, queued: 0, blockers: [], faith_blockers: [], not_ready: ["scanned"] },
          { status: 409 },
        );
      }),
    );
    const { user } = renderApp("/export");
    await user.click(await screen.findByTestId("export-start"));
    expect(await screen.findByTestId("export-not-ready")).toHaveTextContent("scanned has not been through scoring and cleanup with this version yet");
    expect(screen.queryByTestId("export-start")).toBeNull();
  });
});

describe("the rail while a document needs a run (design 11 section 20.17)", () => {
  it("the Export step is locked and says why, also when the ready documents have nothing open", () => {
    const one = stepStates("/scope", notReady({ not_ready: ["scanned"], counts })).export;
    expect(one.short).toBe("locked: needs a run");
    expect(one.long).toBe("Step 4 of 4. Locked: 1 document needs a run (scanned).");
    expect(one.done).toBe(false);
    // nothing in scope yet (every document needs a run): not "nothing to export yet"
    const all = stepStates("/scope", notReady({ counts: { ...counts, in_scope: 0, auto_approved: 0, approved: 0 } })).export;
    expect(all.short).toBe("locked: needs a run");
    expect(all.long).toBe("Step 4 of 4. Locked: 2 documents need a run (clean, scanned).");
    // a run is more basic than the blockers in the ready documents
    expect(stepStates("/scope", notReady({ not_ready: ["scanned"], queued: 1, blockers: ["b"] })).export.short).toBe("locked: needs a run");
  });
  it("shows the lock on the Export step", async () => {
    installFake({ exportStatus: notReady({ not_ready: ["scanned"], counts }) });
    renderApp("/scope");
    const short = await screen.findByTestId("step-short-export");
    expect(short).toHaveTextContent("locked: needs a run");
    expect(short.className).toContain("text-needs-ink");
  });
  it("Your next step names the documents and where to run them", () => {
    expect(defaultNextStep("export", notReady({ not_ready: ["scanned"], counts })).text).toBe(
      "scanned has not been through scoring and cleanup with this version yet. Run the pipeline from the Scope screen, then come back to export.",
    );
    expect(defaultNextStep("export", notReady()).text).toBe(
      "clean, scanned have not been through scoring and cleanup with this version yet. Run the pipeline from the Scope screen, then come back to export.",
    );
    // while a run is going: no "run the pipeline", only what the run is doing (CLAUDE.md "claiming work")
    expect(defaultNextStep("export", notReady({ not_ready: ["scanned"] }), { scoring: true }).text).toBe(
      "scanned is being processed. Export opens when the run has finished and its blocks are reviewed.",
    );
  });
});

describe("the not-ready line names files and knows about a running job (upgrade-fix review)", () => {
  it("uses the file names the Scope screen shows", async () => {
    installFake({ exportStatus: notReady({ not_ready: ["alpha", "beta"] }), sources: makeSources() });
    renderApp("/export");
    expect(await screen.findByTestId("export-not-ready")).toHaveTextContent("Not ready to export: alpha.pdf, beta.pdf have not been through scoring");
  });
  it("says the documents are being processed while a pipeline run is active, and does not ask for a run", async () => {
    installFake({
      exportStatus: notReady({ not_ready: ["alpha"] }),
      sources: makeSources(),
      jobPolls: [[makeJob({ id: "r1", kind: "run", plan: { to: "score2" }, status: "running" })]],
    });
    renderApp("/export");
    const note = await screen.findByTestId("export-not-ready");
    await screen.findByText(/alpha\.pdf is being processed/);
    expect(note).toHaveTextContent("Not ready to export: alpha.pdf is being processed. Export opens when the run has finished and its blocks are reviewed.");
    expect(note).not.toHaveTextContent("Run the pipeline");
  });
  it("Verify is not done while a document needs a run", () => {
    const all = { ...counts, auto_approved: 4, approved: 0 };
    expect(stepStates("/scope", notReady({ not_ready: [], unlocked: true, counts: all })).verify.done).toBe(true);
    expect(stepStates("/scope", notReady({ not_ready: ["scanned"], counts: all })).verify.done).toBe(false);
    // and an export made before the upgrade is not "exported" now
    const summary = { articles: 1 } as unknown as ExportStatus["summary"];
    expect(stepStates("/scope", notReady({ not_ready: ["scanned"], counts: all, summary })).export.short).toBe("locked: needs a run");
  });
});
