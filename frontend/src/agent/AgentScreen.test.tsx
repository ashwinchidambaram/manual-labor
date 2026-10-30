import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { CalibrationReport, Flag, Proposal } from "../api/schema";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";

const flag: Flag = { id: "flag-000001", category: "wrong_text", target_id: "b-doc-p001-01", note: "torque looks wrong", status: "open", created_at: "2026-10-29T09:00:00Z", resolution: null, resolved_at: null };
const proposal = (over: Partial<Proposal> = {}): Proposal =>
  ({
    id: "prop-000001",
    flag_id: "flag-000001",
    target_id: "b-doc-p001-01",
    kind: "text",
    round: 1,
    model: "mock/agent",
    status: "pending",
    proposal_text: "Tighten to 35 N·m.",
    rationale: "The OCR read 36; the text layer says 35.",
    evidence: [
      { source: "pymupdf", span: "35 N·m", verified: true },
      { source: "ocr", span: "36 N·m", verified: false },
    ],
    rechecks: [
      { check: "faithfulness", passed: true, detail: null },
      { check: "numbers_preserved", passed: false, detail: "36 became 35" },
    ],
    history: [],
    created_at: "2026-10-29T09:10:00Z",
    input_hash: "0".repeat(64),
    ...over,
  }) as Proposal;
const calibration: CalibrationReport = {
  buckets: [
    { lo: 0.8, hi: 0.85, n: 10, edited: 3, edit_rate: 0.3, sparse: false, wilson_lo: 0.1, wilson_hi: 0.6 },
    { lo: 0.85, hi: 0.9, n: 0, edited: 0, edit_rate: null, sparse: true, wilson_lo: 0, wilson_hi: 1 },
  ],
  current_threshold: 0.85,
  suggested_threshold: 0.9,
  suggestion_detail: "edit rate above 0.90 is under the 5% target",
  suggestion_reason: "ok",
  target_edit_rate: 0.05,
  n_outcomes: 10,
  n_numeric_excluded: 4,
  pooled: [],
  signals: [],
  warnings: [],
  scope: "project",
} as unknown as CalibrationReport;

describe("U10 AgentScreen", () => {
  it("empty: no open flags tells you how to make one, and the run button is disabled", async () => {
    installFake();
    renderApp("/agent");
    expect(await screen.findByTestId("agent-empty")).toHaveTextContent("No open flags. Flag a block in Verify (f)");
    expect(screen.getByTestId("agent-run")).toBeDisabled();
    expect(await screen.findByTestId("calibration-unavailable")).toHaveTextContent("not available");
    expect(screen.getByRole("link", { name: "Back to Scope" })).toBeInTheDocument();
  });
  it("lists open flags, runs the agent pass, and shows each proposal's re-checks and evidence as reported", async () => {
    installFake({ flags: [flag], proposals: [proposal()], calibration });
    const runs: unknown[] = [];
    server.use(http.post("*/api/agent/run", async ({ request }) => (runs.push(await request.json()), HttpResponse.json(makeJob({ id: "ag1", kind: "agent" }), { status: 202 }))));
    const { user } = renderApp("/agent");
    expect(await screen.findByTestId("agent-flag")).toHaveTextContent("Wrong text");
    await user.click(screen.getByTestId("agent-run"));
    await waitFor(() => expect(runs).toHaveLength(1));
    const p = await screen.findByTestId("proposal");
    expect(p).toHaveTextContent("1 check failed");
    const checks = within(p).getByTestId("rechecks");
    expect(within(checks).getAllByRole("listitem").map((l) => l.getAttribute("data-outcome"))).toEqual(["passed", "failed"]);
    expect(checks).toHaveTextContent("36 became 35");
    expect(within(p).getByText("36 N·m").tagName).toBe("S");
    expect(p).toHaveTextContent("(not found in this source)");
  });
  it("accept and reject post to the existing endpoints", async () => {
    installFake({ flags: [flag], proposals: [proposal()] });
    const calls: string[] = [];
    server.use(
      http.post("*/api/agent/proposals/:id/accept", ({ params }) => (calls.push(`accept ${String(params.id)}`), HttpResponse.json(proposal({ status: "accepted" })))),
      http.post("*/api/agent/proposals/:id/reject", async ({ params, request }) => {
        const b = (await request.json()) as { reason: string | null };
        calls.push(`reject ${String(params.id)} ${b.reason}`);
        return HttpResponse.json(proposal({ status: "rejected" }));
      }),
    );
    const { user } = renderApp("/agent");
    const p = await screen.findByTestId("proposal");
    await user.click(within(p).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(calls).toEqual(["accept prop-000001"]));
    await user.click(within(p).getByRole("button", { name: "Reject" }));
    await user.type(within(p).getByLabelText(/Why is it wrong/), "still 36");
    await user.click(within(p).getByRole("button", { name: "Reject proposal" }));
    await waitFor(() => expect(calls[1]).toBe("reject prop-000001 still 36"));
  });
  it("calibration: buckets with decisions, the suggestion and that it is never applied automatically", async () => {
    installFake({ calibration });
    renderApp("/agent");
    const c = await screen.findByTestId("calibration");
    const rows = within(screen.getByTestId("calibration-table")).getAllByRole("row");
    expect(rows).toHaveLength(2); // header + the one bucket with decisions
    expect(rows[1]).toHaveTextContent("0.80 to 0.8510330%");
    expect(c).toHaveTextContent("4 numeric blocks left out");
    expect(screen.getByTestId("calibration-suggestion")).toHaveTextContent("Suggested 0.90: edit rate above 0.90 is under the 5% target");
    expect(c).toHaveTextContent("never applied automatically");
  });
});
