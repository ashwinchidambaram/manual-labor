import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ExportStatus } from "../api/schema";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";

// Review D3: a project whose documents have no current scores (never run, or scored by an older version) has an
// empty gate. The screen says it needs a run instead of "Ready to export".
const notReady = (over: Partial<ExportStatus> = {}): ExportStatus => ({
  unlocked: true,
  open_flags: 0,
  queued: 0,
  blockers: [],
  overrides: [],
  not_ready: ["clean", "scanned"],
  summary: null,
  zip_path: null,
  ...over,
});

describe("ExportScreen, documents not scored yet", () => {
  it("says which documents need a run and offers no export", async () => {
    installFake({ exportStatus: notReady() });
    renderApp("/export");
    const note = await screen.findByTestId("export-not-ready");
    expect(note).toHaveTextContent("Not ready to export: clean, scanned have not been scored by this version yet.");
    expect(note).toHaveTextContent("Run the pipeline from the Scope screen (or labor run), then come back.");
    expect(screen.queryByTestId("export-ready")).toBeNull();
    expect(screen.queryByTestId("export-start")).toBeNull();
  });
  it("an empty list leaves the ready view as it was", async () => {
    installFake({ exportStatus: notReady({ not_ready: [] }) });
    renderApp("/export");
    expect(await screen.findByTestId("export-ready")).toHaveTextContent("Ready to export");
    expect(screen.queryByTestId("export-not-ready")).toBeNull();
  });
});
