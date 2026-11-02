// First-time user run 5: with the model service down, the banner said "group pump-service-tables: stage failed",
// the first banner had no Retry, the screen stayed stale under it, the cause showed only after a reload, the probe could
// not be run again, and "Table structure" was offered for a list block (design 07 section 20, design 08 section 12).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { makeJob, makeModels } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";
import FlagDialog, { flagCategoriesFor } from "../verify/FlagDialog";
import { withoutCommandHints } from "./jobLog";

const DOWN = "Ollama is not running at http://127.0.0.1:11434. Start it (`ollama serve`) and press Retry.";

describe("a job that failed because the model service was not running", () => {
  it("the banner says so plainly and a reading job's Retry runs Scope's re-run plan", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "u1", kind: "ingest_run", plan: { to: "group", docs: null, force: [], allow_reparse: false } })], []];
    f.jobById = {
      u1: makeJob({ id: "u1", kind: "ingest_run", status: "failed", error: DOWN, error_code: "provider_unreachable", plan: { to: "group", docs: null, force: [], allow_reparse: false } }),
    };
    const posted: unknown[] = [];
    server.use(http.post("*/api/jobs", async ({ request }) => (posted.push(await request.json()), HttpResponse.json(makeJob({ id: "r2" }), { status: 202 }))));
    const { user } = renderApp("/export");
    const alert = await screen.findByTestId("job-failed", undefined, { timeout: 5000 });
    expect(alert).toHaveTextContent(`Reading the new manuals failed: ${DOWN}`);
    expect(alert).not.toHaveTextContent("stage failed");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(posted).toEqual([{ to: "group", allow_reparse: false }]));
  }, 15000);

  it("a failed job refreshes the screen's data, as a finished one does", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "u2", kind: "run", plan: { to: "group" } })], []];
    f.jobById = { u2: makeJob({ id: "u2", kind: "run", status: "failed", error: DOWN, error_code: "provider_unreachable", plan: { to: "group" } }) };
    renderApp("/scope");
    await screen.findByTestId("job-failed", undefined, { timeout: 5000 });
    // the manuals are read again after the failed job's record was (before this change only after a done one)
    await waitFor(() => expect(f.log.lastIndexOf("GET /api/sources")).toBeGreaterThan(f.log.indexOf("GET /api/jobs/u2")), { timeout: 3000 });
  }, 15000);

  it("the manual's card says the service is not running and shows the server's sentence", async () => {
    const f = installFake();
    f.sources = [
      { ...f.sources[0], nodes: [{ node: "parse", state: "fresh" }, { node: "group", state: "failed", reason: DOWN, code: "provider_unreachable" }] },
      { ...f.sources[1], nodes: [{ node: "group", state: "failed", reason: "GroupingError: partition check failed", code: null }] },
    ];
    renderApp("/scope");
    const rows = await screen.findAllByTestId("source-row");
    expect(within(rows[0]).getByTestId("source-chip")).toHaveTextContent("Model service not running");
    expect(within(rows[0]).getByTestId("source-failure")).toHaveTextContent(DOWN);
    expect(within(rows[1]).getByTestId("source-chip")).toHaveTextContent("Failed: group");
    expect(within(rows[1]).getByTestId("source-failure")).toHaveTextContent("partition check failed");
    expect(screen.getByRole("button", { name: "Re-run" })).toBeInTheDocument();
  });
});

describe("the hardware probe can be run again", () => {
  it("offers Run again, says the service is stopped, and gives no download advice then", async () => {
    const f = installFake();
    renderApp("/scope");
    const panel = await screen.findByTestId("model-panel");
    expect(within(panel).getByTestId("ollama-stopped")).toHaveTextContent("Ollama is installed but not running at h");
    expect(within(panel).queryByTestId("pull-commands")).toBeNull();
    await userEvent.click(within(panel).getByTestId("probe-again"));
    await waitFor(() => expect(f.probes).toBe(1));
  });
  it("with the service running, the pull commands come back and the stopped note goes", async () => {
    const f = installFake();
    const m = makeModels(true);
    (m.probe as unknown as { ollama: { reachable: boolean } }).ollama.reachable = true;
    f.models = m;
    renderApp("/scope");
    const panel = await screen.findByTestId("model-panel");
    expect(within(panel).queryByTestId("ollama-stopped")).toBeNull();
    expect(within(panel).getByTestId("pull-commands")).toHaveTextContent("ollama pull cleanup-s");
    expect(within(panel).getByTestId("probe-again")).toHaveTextContent("Run again");
  });
});

describe("the flag dialog offers Table structure only for a table block", () => {
  it("a list block has four categories and key 5 picks nothing; a table block has five", async () => {
    expect(flagCategoriesFor("list").map((c) => c.id)).not.toContain("table_structure");
    expect(flagCategoriesFor("table").map((c) => [c.id, c.key])).toContainEqual(["table_structure", 5]);
    expect(flagCategoriesFor(null).map((c) => c.id)).not.toContain("table_structure");
    const onSubmit = vi.fn();
    const { unmount } = render(<FlagDialog blockType="list" onSubmit={onSubmit} onCancel={() => undefined} />);
    expect(screen.queryByTestId("flag-cat-table_structure")).toBeNull();
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    await userEvent.keyboard("5");
    await userEvent.click(screen.getByRole("button", { name: /Submit/ }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByTestId("flag-msg")).toHaveTextContent("Choose a category");
    unmount();
    render(<FlagDialog blockType="table" onSubmit={onSubmit} onCancel={() => undefined} />);
    expect(screen.getByTestId("flag-cat-table_structure")).toBeInTheDocument();
  });
});

describe("no command lines inside the product", () => {
  it("drops the CLI advice stage errors carry and keeps the rest", () => {
    expect(withoutCommandHints("CleanupError: scores.json missing or stale (run `labor score`)")).toBe("CleanupError: scores.json missing or stale");
    expect(withoutCommandHints("clean.json is stale: raw_text changed since cleanup for b1; re-run `labor clean`")).toBe(
      "clean.json is stale: raw_text changed since cleanup for b1",
    );
    expect(withoutCommandHints("parse would replace blocks that have 2 decision(s); they would be orphaned. Use --discard-decisions to re-parse anyway")).toBe(
      "parse would replace blocks that have 2 decision(s); they would be orphaned.",
    );
    expect(withoutCommandHints(DOWN)).toBe(DOWN);
  });
});
