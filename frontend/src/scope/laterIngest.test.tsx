// Selection on later ingest (design 08 section 10). A manual grouped after the reviewer touched the selection enters
// selected (the server rule, mirrored by the fake below); the Scope counts must follow it even when the reviewer's own
// edit is still unconfirmed, and a manual with nothing selected says so in its heading instead of a silent 0%.
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SelectionOut } from "../api/schema";
import { http, HttpResponse } from "msw";
import { makeBlocks, makeDocs, makeJob, makeSelectionOut } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";

const row = (id: string) => document.querySelector<HTMLElement>(`[data-testid=row][data-group-id="${id}"]`)!;
const heading = (doc: string) => document.querySelector<HTMLElement>(`[data-testid=doc-heading][data-doc="${doc}"]`)!;
const selectable = (doc: string) => makeDocs().find((d) => d.doc_id === doc)!.groups.structure.flatMap((g) => g.block_ids);

describe("a manual grouped after the selection was touched", () => {
  it("arrives selected and counted, also while the reviewer's last edit is still on its way", async () => {
    const all = makeDocs();
    const f = installFake({
      docs: all.filter((d) => d.doc_id === "alpha"),
      blocks: makeBlocks().filter((d) => d.doc_id === "alpha"),
      ids: selectable("alpha"),
      jobPolls: [[makeJob({ id: "read-beta", doc: "beta" })]],
    });
    const { user, qc } = renderApp("/scope");
    await screen.findByTestId("group-tree");
    await waitFor(() => expect(screen.getByTestId("sum-blocks")).toHaveTextContent("7"));

    // the reviewer clears "Intro" (3 blocks); the server holds the answer
    let release!: () => void;
    f.gate = new Promise<void>((r) => (release = r));
    await user.click(row("g-alpha-t001"));
    await waitFor(() => expect(screen.getByTestId("sum-blocks")).toHaveTextContent("4"));

    // meanwhile beta finishes reading: grouped, and (server rule) in the selection
    f.docs = all;
    f.blocks = makeBlocks();
    f.ids = [...f.ids, ...selectable("beta")];
    f.jobPolls = [[]];
    f.jobById = { "read-beta": makeJob({ id: "read-beta", status: "done" }) };
    await waitFor(() => expect(row("g-beta-t001")).toBeTruthy(), { timeout: 5000 });

    release();
    await waitFor(() => expect(row("g-beta-t001")).toHaveAttribute("data-check", "checked"));
    await waitFor(() => expect(f.puts.length).toBe(1));
    // what the screen shows equals what the server counts
    const server = qc.getQueryData<SelectionOut>(["selection"])!;
    await waitFor(() => expect(screen.getByTestId("sum-blocks")).toHaveTextContent(String(4 + 3)));
    expect(server.summary.blocks).toBe(7);
    expect(screen.getByTestId("sum-docs")).toHaveTextContent("2");
    expect(row("g-alpha-t001")).toHaveAttribute("data-check", "unchecked");
    expect(within(heading("beta")).queryByTestId("doc-not-selected")).toBeNull();
  }, 15000);

  it("a manual with nothing selected says so in its heading, with the block count and the key that adds it", async () => {
    installFake({ ids: selectable("alpha") });
    renderApp("/scope");
    await screen.findByTestId("group-tree");
    const note = await within(heading("beta")).findByTestId("doc-not-selected");
    expect(note).toHaveAttribute("role", "note");
    expect(note).toHaveTextContent("Not in your selection: 3 blocks");
    expect(note).toHaveTextContent("Shift");
    expect(within(heading("alpha")).queryByTestId("doc-not-selected")).toBeNull();
  });

  it("a manual grouped after the selection was written is not called unselected while the selection refetch is on its way", async () => {
    const f = installFake({ ids: selectable("alpha") });
    server.use(
      http.get("*/api/scope/selection", () => {
        const out = makeSelectionOut(f.ids, {}, f.docs);
        return HttpResponse.json({ ...out, selection: { ...out.selection, known_docs: ["alpha"] } });
      }),
    );
    renderApp("/scope");
    await screen.findByTestId("group-tree");
    await waitFor(() => expect(heading("beta")).toBeTruthy());
    await new Promise((r) => setTimeout(r, 200));
    expect(within(heading("beta")).queryByTestId("doc-not-selected")).toBeNull();
  });
});
