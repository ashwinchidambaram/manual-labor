// "Open in Verify" lands on the named block (design 09 section 11, F11), and a flagged block shows its flag with the
// agent's outcome. Reproduces the first-use report: after visiting Verify, the Agent screen's link to the flagged block
// and the Export screen's blocker links opened the top of the queue (a cached queue snapshot carried the old cursor).
import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { AgentItemView, Flag } from "../api/schema";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";
import { makeBlockDetail, makeQueueItem, vid } from "../test/verifyFake";
import { mountVerify } from "../verify/helpers.test-util";
import { openInVerify } from "../shell/openInVerify";
import { jobLogLines } from "../shell/jobLog";
import { FLAG_RESOLUTION } from "../verify/labels";
import { triedText } from "./outcome";

const FLAGGED = "b-doc-p002-07";
const flag: Flag = { id: "flag-000001", category: "wrong_text", target_id: FLAGGED, note: "torque looks wrong", status: "open", created_at: "2026-10-30T12:20:00Z", resolution: null, resolved_at: null };
const item: AgentItemView = { flag, target_id: FLAGGED, round: 1, attempts: 2, pending_proposal_id: null, last_outcome: "error", last_detail: "proposal_text is missing" };
// the log of the agent pass in the report (build/human-test/logs/jobs/job-000004.jsonl)
const DANA_LOG = [
  { event: "job_start", units: 1, line: 0 },
  { event: "heartbeat", llm_calls: 1, line: 1 },
  { event: "heartbeat", llm_calls: 2, line: 2 },
  { detail: "proposal_text is missing", event: "agent_outcome", flag_id: "flag-000001", outcome: "error", round: 1, line: 3 },
  { doc: "x200-two-column", event: "unit_done", node: "agent", status: "error", line: 4 },
  { error: "1 agent item(s) ended in an error", event: "job_end", failed: {}, status: "failed", line: 5 },
];

async function setup() {
  const s = await mountVerify(4, (f) => {
    // flagged blocks are never in the queue: only their detail exists
    f.details[FLAGGED] = makeBlockDetail(makeQueueItem(7, { block_id: FLAGGED, page: 2, status: "flagged" }), { flags: [flag] });
  }, { flags: [flag] });
  server.use(http.get("*/api/agent/items", () => HttpResponse.json([item])));
  return s;
}

const current = () => document.querySelector('[data-testid^="card-"][aria-current="true"]')?.getAttribute("data-testid");

describe("open in Verify", () => {
  it("from the Agent screen, after Verify was open earlier, lands on the flagged block and shows the flag with the agent's outcome", async () => {
    const { r } = await setup();
    expect(current()).toBe(`card-${vid(1)}`);
    await act(() => r.router.navigate("/agent"));
    const row = await screen.findByTestId("agent-flag");
    await r.user.click(within(row).getByRole("link", { name: `Open ${FLAGGED} in Verify` }));
    await waitFor(() => expect(r.router.state.location.pathname).toBe("/verify"));
    await waitFor(() => expect(current()).toBe(`card-${FLAGGED}`));
    // and it stays there: the old snapshot is never applied afterwards
    await new Promise((res) => setTimeout(res, 400));
    expect(current()).toBe(`card-${FLAGGED}`);
    const notice = await screen.findByTestId("verify-flag");
    expect(notice).toHaveTextContent("Wrong text");
    expect(notice).toHaveTextContent("torque looks wrong");
    expect(notice).toHaveTextContent("tried 2 times, last: error, the model answered without the corrected text");
    expect(notice).toHaveTextContent(FLAG_RESOLUTION);
    expect(within(notice).getByRole("link", { name: /Agent screen/ })).toHaveAttribute("href", "/agent");
  }, 15000);

  it("from any screen that calls openInVerify without a query client (Export), the cached queue is not applied", async () => {
    const { r } = await setup();
    expect(current()).toBe(`card-${vid(1)}`);
    await act(() => r.router.navigate("/scope"));
    await act(() => openInVerify(FLAGGED));
    await act(() => r.router.navigate("/verify"));
    await waitFor(() => expect(current()).toBe(`card-${FLAGGED}`));
    await new Promise((res) => setTimeout(res, 400));
    expect(current()).toBe(`card-${FLAGGED}`);
  }, 15000);

  it("a queued block opened from elsewhere is the current card too", async () => {
    const { r } = await setup();
    await act(() => r.router.navigate("/scope"));
    await act(() => openInVerify(vid(3)));
    await act(() => r.router.navigate("/verify"));
    await waitFor(() => expect(current()).toBe(`card-${vid(3)}`));
    expect(screen.queryByTestId("verify-flag")).toBeNull();
  }, 15000);
});

// Second first-use report C8 (design 09 section 14): the flagged block was titled by its file name ("x200-two-column.pdf")
// on the Agent card and on Verify. Its title comes from where a queue card's does: the section heading, then the
// block's excerpt, the file name last.
describe("a flagged block's title", () => {
  const titleRow = (section_title: string | null) => [{ block_id: FLAGGED, doc_id: "alpha", page: 2, type: "paragraph", section_title }];
  const flagIn = (section_title: string | null) => {
    const f = installFake({ flags: [{ ...flag }], sources: [{ slug: "alpha", filename: "x200-two-column.pdf", kind: "born_digital_pdf", pages: 4, ocr_warning: null, nodes: [] }] });
    server.use(
      http.get("*/api/agent/items", () => HttpResponse.json([item])),
      http.get("*/api/verify/titles", () => HttpResponse.json(titleRow(section_title))),
      http.get(`*/api/verify/blocks/${FLAGGED}`, () =>
        HttpResponse.json(makeBlockDetail(makeQueueItem(7, { block_id: FLAGGED, doc_id: "alpha", page: 2, status: "flagged" }), { flags: [flag] }, { doc_id: "alpha", clean_text: "Allow the unit to cool before you refill 2.5 L." })),
      ),
    );
    return f;
  };
  it("on the Agent card: the section heading, never the file name", async () => {
    flagIn("1.1 Overview");
    renderApp("/agent");
    const row = await screen.findByTestId("agent-flag");
    await waitFor(() => expect(row).toHaveTextContent("1.1 Overview"));
    expect(row).not.toHaveTextContent("x200-two-column.pdf");
  });
  it("on the Agent card without a heading above it: the block's excerpt", async () => {
    flagIn(null);
    renderApp("/agent");
    const row = await screen.findByTestId("agent-flag");
    await waitFor(() => expect(row).toHaveTextContent("Allow the unit to cool before you refill 2.5 L."));
    expect(row).not.toHaveTextContent("x200-two-column.pdf");
  });
  it("on Verify, opened from the Agent card: the section heading", async () => {
    const s = await setup();
    server.use(http.get("*/api/verify/titles", () => HttpResponse.json([{ block_id: FLAGGED, doc_id: "doc", page: 2, type: "paragraph", section_title: "1.1 Overview" }])));
    await act(() => s.r.router.navigate("/agent"));
    const row = await screen.findByTestId("agent-flag");
    await s.r.user.click(within(row).getByRole("link", { name: `Open ${FLAGGED} in Verify` }));
    await waitFor(() => expect(current()).toBe(`card-${FLAGGED}`));
    await waitFor(() => expect(screen.getByTestId(`card-${FLAGGED}`)).toHaveTextContent("1.1 Overview"));
    expect(screen.getByRole("heading", { level: 3, name: "1.1 Overview" })).toBeInTheDocument();
  }, 15000);
});

describe("the flag card after agent passes that failed", () => {
  it("says how often it was tried and how the last try ended, in words, with a way out", async () => {
    installFake({ flags: [flag] });
    server.use(http.get("*/api/agent/items", () => HttpResponse.json([item])));
    renderApp("/agent");
    const row = await screen.findByTestId("agent-flag");
    await waitFor(() => expect(row).toHaveTextContent("tried 2 times, last: error, the model answered without the corrected text"));
    expect(row).not.toHaveTextContent("not tried yet");
    expect(row).toHaveTextContent(/Run the agent pass again, or open the block in Verify/);
  });
  it("the 'started' line is replaced by how the pass ended", async () => {
    const f = installFake({ flags: [flag] });
    server.use(
      http.get("*/api/agent/items", () => HttpResponse.json([{ ...item, attempts: 0, last_outcome: null, last_detail: null }])),
      http.post("*/api/agent/run", () => HttpResponse.json(makeJob({ id: "ag1", kind: "agent" }), { status: 202 })),
    );
    f.jobById = { ag1: makeJob({ id: "ag1", kind: "agent", status: "failed", error: "1 agent item(s) ended in an error" }) };
    const { user } = renderApp("/agent");
    await user.click(await screen.findByTestId("agent-run"));
    const out = await screen.findByTestId("agent-run-outcome", undefined, { timeout: 4000 });
    expect(out.closest("[role=alert]")).toBe(screen.getByTestId("agent-run-alert"));
    expect(out).toHaveTextContent("Agent pass on your flags ended with an error: 1 agent item(s) ended in an error.");
    expect(screen.queryByText(/Agent pass started/)).toBeNull();
  });
  it("triedText: round alone (1) cannot say a pass ran; attempts and a recorded outcome can", () => {
    expect(triedText({ ...item, attempts: 0 })).toBe("tried once, last: error, the model answered without the corrected text");
    expect(triedText({ ...item, attempts: 0, last_outcome: null, last_detail: null })).toBe("not tried yet");
    expect(triedText({ ...item, attempts: 0, last_outcome: "out_of_scope", last_detail: "target is not in review scope" })).toBe("not tried: the block is not in your selection");
    expect(triedText({ ...item, attempts: 3, last_outcome: "error", last_detail: "ollama: model not found" })).toBe("tried 3 times, last: error, the model call failed: ollama: model not found");
  });
});

describe("See log", () => {
  it("renders the agent pass log as sentences, never JSON", () => {
    const lines = jobLogLines(DANA_LOG);
    expect(lines).toEqual([
      "Started: 1 step to do.",
      "Flag flag-000001: error, the model answered without the corrected text.",
      "Agent pass (x200-two-column): ended with an error.",
      "Stopped: ended with an error. 1 agent item(s) ended in an error.",
    ]);
    for (const l of lines) expect(l).not.toMatch(/[{}"]/);
  });
  it("the failed job banner's See log shows those lines", async () => {
    const s = await setup();
    s.scope.jobPolls = [[makeJob({ id: "job-000004", kind: "agent", plan: {} })], []];
    s.scope.jobById = { "job-000004": makeJob({ id: "job-000004", kind: "agent", plan: {}, status: "failed", error: "1 agent item(s) ended in an error" }) };
    server.use(http.get("*/api/jobs/:id/log", () => HttpResponse.json(DANA_LOG)));
    await act(() => s.r.router.navigate("/agent"));
    await act(() => s.r.qc.invalidateQueries({ queryKey: ["jobs", "active"] }));
    const failed = await screen.findByTestId("job-failed", undefined, { timeout: 5000 });
    await s.r.user.click(within(failed).getByRole("button", { name: "See log" }));
    const log = await screen.findByTestId("job-log");
    expect(log).toHaveTextContent("Flag flag-000001: error, the model answered without the corrected text.");
    expect(log.textContent).not.toMatch(/[{}]/);
  }, 15000);
});
