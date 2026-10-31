import { act, screen, waitFor, within } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { trackJob } from "../api/queries";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";

describe("JobsBar: what now after a failed job (design 12 section 2.6)", () => {
  it("Retry re-posts the same plan; See log shows the job's log", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "j9" })], []];
    f.jobById = { j9: makeJob({ id: "j9", status: "failed", error: "parser crashed", plan: { to: "score2", docs: ["alpha"], allow_reparse: false } }) };
    const posted: unknown[] = [];
    server.use(
      http.get("*/api/jobs/:id/log", () => HttpResponse.json([{ message: "parse alpha: start" }, { message: "parse alpha: crashed" }])),
      http.post("*/api/jobs", async ({ request }) => (posted.push(await request.json()), HttpResponse.json(makeJob({ id: "j10" }), { status: 202 }))),
    );
    const { user } = renderApp("/export");
    const alert = await screen.findByTestId("job-failed", undefined, { timeout: 5000 });
    await user.click(within(alert).getByRole("button", { name: "See log" }));
    expect(await within(alert).findByTestId("job-log")).toHaveTextContent("parse alpha: crashed");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(posted).toEqual([{ to: "score2", docs: ["alpha"], allow_reparse: false }]));
    await waitFor(() => expect(screen.queryByTestId("job-failed")).toBeNull());
  }, 15000);
  it("a job whose plan is not a pipeline run offers no Retry", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "a1", kind: "agent" })], []];
    f.jobById = { a1: makeJob({ id: "a1", kind: "agent", status: "failed", error: "model down", plan: { flag_ids: [] } }) };
    renderApp("/export");
    const alert = await screen.findByTestId("job-failed", undefined, { timeout: 5000 });
    expect(within(alert).queryByRole("button", { name: "Retry" })).toBeNull();
    expect(within(alert).getByRole("button", { name: "See log" })).toBeInTheDocument();
  }, 15000);
});

describe("JobsBar: a running job in words (review M13 P2-11)", () => {
  it("a scoring run reads as a sentence with 'Step N of M' and a named Cancel; never 0/0", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "r1", kind: "run", plan: { to: "score2" }, units_done: 0, units_total: 0, progress: 0 })]];
    renderApp("/export");
    const row = await screen.findByTestId("job-row", undefined, { timeout: 5000 });
    expect(row).toHaveTextContent("Scoring your selection");
    expect(row).toHaveTextContent("Starting");
    expect(row).not.toHaveTextContent("0/0");
    expect(within(row).getByRole("button", { name: "Cancel scoring" })).toBeInTheDocument();
  }, 15000);
  it("progress names the step 'Step N of M' (the one running); an unknown kind falls back to its name", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "r2", kind: "run", plan: { to: "score2" }, units_done: 2, units_total: 5 }), makeJob({ id: "x1", kind: "reindex", plan: {}, units_done: 0, units_total: 3 })]];
    renderApp("/export");
    const rows = await screen.findAllByTestId("job-row", undefined, { timeout: 5000 });
    await waitFor(() => expect(screen.getAllByTestId("job-row")).toHaveLength(2));
    expect(rows[0]).toHaveTextContent("Step 3 of 5: Grouping alpha.pdf into topics");
    const other = screen.getAllByTestId("job-row")[1];
    expect(other).toHaveTextContent("reindex");
    expect(other).toHaveTextContent("Step 1 of 3");
  }, 15000);
});

describe("JobsBar: a burst of identical jobs is one bar (design 07 section 18)", () => {
  it("a re-attach's three responses (one queued, two merged into it) show one bar", async () => {
    const f = installFake();
    const survivor = makeJob({ id: "job-000016", kind: "run", status: "queued", plan: { to: "score2", docs: ["alpha"] }, progress: 0, units_done: 0, units_total: 0 });
    f.jobPolls = [[survivor]];
    // the server's list answers late, so whatever the client put in its cache is what shows meanwhile
    server.use(http.get("*/api/jobs", async () => (await delay(400), HttpResponse.json([survivor]))));
    const { qc } = renderApp("/export");
    act(() => {
      trackJob(qc, survivor);
      trackJob(qc, makeJob({ id: "job-000017", status: "merged", merged_into: "job-000016", plan: { to: "score2", docs: ["alpha"] } }));
      trackJob(qc, makeJob({ id: "job-000018", status: "merged", merged_into: "job-000016", plan: { to: "score2", docs: ["alpha"] } }));
    });
    const rows = await screen.findAllByTestId("job-row", undefined, { timeout: 5000 });
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Scoring your selection");
    await new Promise((r) => setTimeout(r, 600));
    expect(screen.getAllByTestId("job-row")).toHaveLength(1);
  }, 15000);
  it("merged responses alone (the survivor came from elsewhere) show one bar for the survivor, and its end reconciles", async () => {
    const f = installFake();
    const survivor = makeJob({ id: "job-000030", kind: "run", status: "running", plan: { to: "score2", docs: ["alpha"] } });
    f.jobPolls = [[], []];
    f.jobById = { "job-000030": { ...survivor, status: "done", progress: 1 } };
    server.use(http.get("*/api/jobs", async () => (await delay(300), HttpResponse.json([]))));
    const { qc } = renderApp("/export");
    act(() => {
      trackJob(qc, makeJob({ id: "job-000031", status: "merged", merged_into: "job-000030", plan: { to: "score2", docs: ["alpha"] } }));
      trackJob(qc, makeJob({ id: "job-000032", status: "merged", merged_into: "job-000030", plan: { to: "score2", docs: ["alpha"] } }));
    });
    const rows = await screen.findAllByTestId("job-row", undefined, { timeout: 5000 });
    expect(rows).toHaveLength(1);
    // the survivor finished before the list was refetched: its record is still read once
    await waitFor(() => expect(f.jobGets).toBeGreaterThan(0), { timeout: 5000 });
    await waitFor(() => expect(screen.queryByTestId("job-row")).toBeNull(), { timeout: 5000 });
  }, 15000);
});
