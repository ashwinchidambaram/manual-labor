// First-use report D (2026-10-30): the jobs bar names the step, the manual and the inner count the worker reports,
// says when a step has no estimate, names the files of a waiting upload, and stays on screen (design 13 section 2.5.6).
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { stepSentence } from "./jobStep";

const files = (s: string): string => `${s}.pdf`;

describe("stepSentence (pure)", () => {
  it("names the step, the file and the inner count", () => {
    const j = makeJob({ node: "figures", doc: "x200-two-column", units_done: 2, units_total: 4, step_done: 4, step_total: 6, step_unit: "page" });
    expect(stepSentence(j, files)).toEqual({ text: "Step 3 of 4: Finding figures in x200-two-column.pdf, page 4 of 6", estimate: true });
    const s = makeJob({ node: "score", doc: "pump", units_done: 0, units_total: 6, step_done: 40, step_total: 87, step_unit: "block" });
    expect(stepSentence(s, files).text).toBe("Step 1 of 6: Scoring pump.pdf, 40 of 87 blocks");
    const t = makeJob({ node: "group", doc: "pump", units_done: 3, units_total: 4, step_done: 1, step_total: 1, step_unit: "topic" });
    expect(stepSentence(t, files).text).toBe("Step 4 of 4: Grouping pump.pdf into topics, 1 of 1 topic");
  });
  it("a step without a count has no estimate; it never invents one", () => {
    const j = makeJob({ node: "group", doc: "pump", units_done: 3, units_total: 4, step_done: null, step_total: null, step_unit: null });
    expect(stepSentence(j, files)).toEqual({ text: "Step 4 of 4: Grouping pump.pdf into topics", estimate: false });
  });
  it("a waiting upload names its files; an upload being added says so", () => {
    expect(stepSentence(makeJob({ kind: "ingest_run", status: "queued", units_total: 0, node: null, doc: null, files: ["x200-two-column.pdf"] }), files).text).toBe(
      "Waiting to start: x200-two-column.pdf",
    );
    expect(stepSentence(makeJob({ kind: "ingest_run", units_done: 0, units_total: 0, node: null, doc: null, files: ["pump.pdf"] }), files).text).toBe("Adding pump.pdf");
    expect(stepSentence(makeJob({ units_done: 0, units_total: 0, node: null, doc: null }), files).text).toBe("Starting");
  });
});

describe("JobsBar while reading and scoring", () => {
  it("each row names its step with the manual's file name and the worker's own count", async () => {
    const f = installFake();
    f.jobPolls = [
      [
        makeJob({ id: "a", kind: "ingest_run", plan: { to: "group" }, node: "figures", doc: "alpha", units_done: 2, units_total: 4, step_done: 4, step_total: 6, step_unit: "page", progress: (2 + 4 / 6) / 4, files: ["alpha.pdf"] }),
        makeJob({ id: "b", kind: "ingest_run", status: "queued", plan: { to: "group" }, node: null, doc: null, units_done: 0, units_total: 0, progress: 0, files: ["beta.pdf"] }),
      ],
    ];
    renderApp("/scope");
    await waitFor(() => expect(screen.getAllByTestId("job-row")).toHaveLength(2));
    const [a, b] = screen.getAllByTestId("job-row");
    expect(within(a).getByTestId("job-step")).toHaveTextContent("Step 3 of 4: Finding figures in alpha.pdf, page 4 of 6");
    expect(within(a).getByRole("progressbar")).toHaveAttribute("value", String((2 + 4 / 6) / 4));
    expect(a).not.toHaveTextContent("no estimate");
    expect(within(b).getByTestId("job-step")).toHaveTextContent("Waiting to start: beta.pdf");
  }, 15000);

  it("a step with no count says 'working, no estimate' and the bar shows only finished steps", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "g", kind: "run", plan: { to: "score2" }, node: "group", doc: "beta", units_done: 3, units_total: 4, progress: 0.75 })]];
    renderApp("/scope");
    const row = await screen.findByTestId("job-row", undefined, { timeout: 5000 });
    expect(within(row).getByTestId("job-step")).toHaveTextContent("Step 4 of 4: Grouping beta.pdf into topics");
    expect(within(row).getByTestId("job-no-estimate")).toHaveTextContent("working, no estimate");
    expect(within(row).getByRole("progressbar")).toHaveAttribute("value", "0.75");
  }, 15000);

  it("stays on screen while the page scrolls (sticky at the top)", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "s", plan: { to: "score2" } })]];
    renderApp("/scope");
    const bar = await screen.findByTestId("jobs-bar", undefined, { timeout: 5000 });
    expect(bar.className).toMatch(/(^|\s)sticky(\s|$)/);
    expect(bar.className).toMatch(/(^|\s)top-0(\s|$)/);
  }, 15000);
});
