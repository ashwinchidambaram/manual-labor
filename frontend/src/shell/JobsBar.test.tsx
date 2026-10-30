import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
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
