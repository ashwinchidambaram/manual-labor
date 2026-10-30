// A project ingested from the CLI arrives with every stage "missing" and no job running.
// The Scope screen must offer to run it, not claim it is processing. Stages that only run on
// Confirm (clean, score2) are not Scope's to run and never produce a button here.
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { jobCovers } from "./SourcesList";

const loaded = async () => {
  const r = renderApp("/scope");
  await screen.findByTestId("group-tree");
  await screen.findByTestId("sum-blocks");
  return r;
};
const chip = (i: number) => within(screen.getAllByTestId("source-row")[i]).getByTestId("source-chip");

describe("sources that have never been run", () => {
  it("offers Run and says the stage has not run, when no job is running", async () => {
    const f = installFake();
    f.sources = [{ ...f.sources[0], nodes: [{ node: "parse", state: "missing" }] }];
    await loaded();
    expect(chip(0)).toHaveTextContent("Not run yet: parse");
    expect(screen.getByRole("button", { name: "Run" })).toBeInTheDocument();
  });
  it("names the step a running job is on for that manual and offers no button", async () => {
    const f = installFake();
    f.sources = [{ ...f.sources[0], nodes: [{ node: "parse", state: "missing" }] }];
    f.jobPolls = [[makeJob({ id: "j1", kind: "run", doc: f.sources[0].slug, node: "parse" })]];
    await loaded();
    expect(chip(0)).toHaveTextContent("Reading");
    expect(chip(0)).not.toHaveTextContent("Processing");
    expect(screen.queryByRole("button", { name: "Run" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-run" })).toBeNull();
  });
  it("a queued job (no progress yet) makes the manuals in its plan wait their turn; the others are Ready", async () => {
    const f = installFake();
    f.sources = [
      { ...f.sources[0], nodes: [{ node: "parse", state: "missing" }] },
      { ...f.sources[1], nodes: [{ node: "parse", state: "fresh" }, { node: "group", state: "fresh" }] },
    ];
    f.jobPolls = [[makeJob({ id: "j1", kind: "run", status: "queued", doc: null, node: null, plan: { docs: [f.sources[0].slug] } })]];
    await loaded();
    expect(chip(0)).toHaveTextContent("Waiting its turn");
    expect(chip(1)).toHaveTextContent("Ready");
    expect(jobCovers(makeJob({ doc: null, plan: {} }), "anything")).toBe(true); // no filter: project-wide
  });
  it("clean and score2 missing after an upload is Ready on Scope, with no Run button: Confirm runs them", async () => {
    const f = installFake();
    f.sources = [
      {
        ...f.sources[0],
        nodes: [
          { node: "parse", state: "fresh" },
          { node: "group", state: "fresh" },
          { node: "clean", state: "missing" },
          { node: "score2", state: "missing" },
        ],
      },
    ];
    await loaded();
    expect(chip(0)).toHaveTextContent("Ready");
    expect(screen.queryByRole("button", { name: "Run" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-run" })).toBeNull();
  });
});

describe("first-use report E: the manual's chip names the step, never 'Processing clean'", () => {
  it("a manual being grouped says so with the worker's count; one already read is Ready", async () => {
    const f = installFake();
    f.sources = [
      { ...f.sources[0], nodes: [{ node: "parse", state: "fresh" }, { node: "group", state: "missing" }, { node: "clean", state: "missing" }] },
      { ...f.sources[1], nodes: [{ node: "parse", state: "fresh" }, { node: "group", state: "fresh" }, { node: "clean", state: "missing" }] },
    ];
    f.jobPolls = [[makeJob({ id: "j1", kind: "ingest_run", plan: { to: "group" }, doc: f.sources[0].slug, node: "group", units_done: 3, units_total: 4, step_done: 2, step_total: 5, step_unit: "topic" })]];
    await loaded();
    expect(chip(0)).toHaveTextContent("Grouping into topics, 2 of 5 topics");
    expect(chip(1)).toHaveTextContent("Ready");
    expect(chip(1)).not.toHaveTextContent("clean");
  });
});
