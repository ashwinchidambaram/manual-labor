import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { CalibrationReport, Flag, Proposal } from "../api/schema";
import { makeJob } from "../test/fixtures";
import { makeBlockDetail, makeQueueItem } from "../test/verifyFake";
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
    expect(await screen.findByTestId("agent-empty")).toHaveTextContent("No open flags. Flag a block in Verify (F)");
    const run = screen.getByTestId("agent-run");
    expect(run).toBeDisabled();
    expect(run).toHaveAccessibleDescription(/No open flags/);
    // what an agent pass is, in one sentence, before the button
    const def = screen.getByTestId("agent-definition");
    expect(def).toHaveTextContent(/^An agent pass works through your open flags\. Each flagged block goes to a model with your note/);
    expect(def.compareDocumentPosition(run) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
  it("Accept is disabled with the reason when a re-check failed or none was reported", async () => {
    installFake({ flags: [flag], proposals: [proposal(), proposal({ id: "prop-000002", rechecks: [] })] });
    renderApp("/agent");
    const [failed, none] = await screen.findAllByTestId("proposal");
    expect(within(failed).getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(within(failed).getByRole("button", { name: "Accept" })).toHaveAccessibleDescription("Accept is off: 1 re-check failed. Edit the proposal or reject it.");
    expect(within(none).getByRole("button", { name: "Accept" })).toHaveAccessibleDescription("Accept is off: no re-check was reported for this proposal. Edit it or reject it.");
  });
  it("a rejected proposal is described honestly: the flag stays open and the item waits for the next pass", async () => {
    installFake({ flags: [flag], proposals: [proposal()] });
    renderApp("/agent");
    const note = await screen.findByTestId("reject-note");
    expect(note).toHaveTextContent("Rejecting a proposal leaves its flag open");
    expect(note).not.toHaveTextContent(/back to the Verify queue/);
  });
  it("a failed start and a failed jump to Verify are alerts", async () => {
    installFake({ flags: [flag], proposals: [proposal()] });
    server.use(
      http.post("*/api/agent/run", () => HttpResponse.json({ detail: "a pass is already running", code: "busy" }, { status: 409 })),
      http.get("*/api/verify/cursor", () => HttpResponse.json({ detail: "store locked", code: "internal" }, { status: 500 })),
    );
    const { user } = renderApp("/agent");
    await user.click(await screen.findByTestId("agent-run"));
    // the alert region is mounted with the screen and its text changes (an inserted alert is often not announced)
    expect((await screen.findByText(/Agent pass not started: a pass is already running/)).closest("[role=alert]")).toBe(screen.getByTestId("agent-run-alert"));
    await user.click(within(await screen.findByTestId("agent-flag")).getByRole("link", { name: /Open b-doc-p001-01 in Verify/ }));
    expect(await screen.findByText(/Could not open b-doc-p001-01 in Verify: store locked/)).toHaveAttribute("role", "alert");
  });
  it("accept and reject post to the existing endpoints", async () => {
    installFake({ flags: [flag], proposals: [proposal({ rechecks: [{ check: "faithfulness", passed: true, detail: null }] })] });
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
    expect(c).toHaveTextContent("from 6 decisions on blocks without numbers");
    expect(c).toHaveTextContent("4 decisions on blocks with numbers are left out");
    expect(screen.getByTestId("calibration-suggestion")).toHaveTextContent("Suggested 0.90: blocks scoring 0.90 or more were edited less often than your goal of 5 in 100.");
    expect(c).toHaveTextContent("The scorer's note: edit rate above 0.90 is under the 5% target");
    expect(c).toHaveTextContent("never applied for you");
  });
  it("an open flag is titled from its block (file, page, type), with the category and the id; a fresh flag reads 'not tried yet'", async () => {
    installFake({ flags: [{ ...flag, target_id: "b-beta-p009-10" }] });
    const blocks: string[] = [];
    server.use(
      http.get("*/api/verify/blocks/:id", ({ params }) => {
        blocks.push(String(params.id));
        return HttpResponse.json(makeBlockDetail(makeQueueItem(1, { block_id: "b-beta-p009-10", doc_id: "beta", page: 9 })));
      }),
      http.get("*/api/agent/items", () => HttpResponse.json([{ flag: { ...flag, target_id: "b-beta-p009-10" }, target_id: "b-beta-p009-10", round: 1, pending_proposal_id: null, last_outcome: null, last_detail: null }])),
    );
    renderApp("/agent");
    const row = await screen.findByTestId("agent-flag");
    await waitFor(() => expect(row).toHaveTextContent("beta.pdf, page 9, paragraph"));
    expect(row.firstElementChild).toHaveTextContent(/^beta\.pdf, page 9, paragraph$/);
    expect(row).toHaveTextContent("Wrong text");
    expect(row).toHaveTextContent("b-beta-p009-10");
    expect(row).toHaveTextContent("not tried yet");
    expect(row).not.toHaveTextContent("round 1");
    expect(blocks).toEqual(["b-beta-p009-10"]);
  });
  it("after an agent pass the flag says how often it was tried and how the last try ended", async () => {
    installFake({ flags: [flag] });
    server.use(http.get("*/api/agent/items", () => HttpResponse.json([{ flag, target_id: flag.target_id, round: 2, pending_proposal_id: null, last_outcome: "rejected", last_detail: null }])));
    renderApp("/agent");
    const row = await screen.findByTestId("agent-flag");
    await waitFor(() => expect(row).toHaveTextContent("tried once, last: rejected"));
  });
  it("calibration with no counted decisions: the designed empty state, and both sentences count the same decisions", async () => {
    installFake({ calibration: { ...calibration, buckets: [], n_outcomes: 1, n_numeric_excluded: 1, suggested_threshold: null, suggestion_reason: "insufficient_data", suggestion_detail: "no score bucket holds 20 reviewed decisions yet" } as CalibrationReport });
    renderApp("/agent");
    const c = await screen.findByTestId("calibration");
    expect(c).toHaveTextContent("Builds as you review. After 20 decisions in a score range you will see how often you edited blocks there, and a suggested threshold. It is never applied for you.");
    expect(c).toHaveTextContent("No decisions counted yet");
    expect(c).toHaveTextContent("1 decision on a block with numbers is left out");
    expect(c).not.toHaveTextContent("from 1 decision");
    expect(c).not.toHaveTextContent("Target edit rate");
    expect(screen.getByTestId("calibration-suggestion")).toHaveTextContent("No threshold is suggested yet: a suggestion needs 20 decisions in one score range.");
  });
});

