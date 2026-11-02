// Removing a manual from Scope (design 08 section 11): the confirmation states what is lost in the server's counts,
// is refused while a job could touch the manual, and the screen recounts afterwards.
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { SourceRemoval } from "../api/schema";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";
import { removalSentences } from "./RemoveManualDialog";

const preview = (over: Partial<SourceRemoval> = {}): SourceRemoval => ({
  doc_id: "alpha",
  filename: "alpha.pdf",
  blocks: 75,
  selected_blocks: 12,
  decisions: 3,
  flags: 1,
  open_flags: 1,
  proposals: 0,
  blocked_by: null,
  removed: false,
  ...over,
});

describe("what the confirmation says", () => {
  it("names the blocks, the selection, the decisions and the open flags", () => {
    expect(removalSentences(preview())).toEqual([
      "The file and everything read from it are deleted: 75 blocks, 12 of them in your selection.",
      "3 decisions and 1 open flag on its blocks stay in the decision log but no longer count.",
      "Adding the same file again brings back the decisions whose text has not changed.",
    ]);
  });
  it("leaves zeros out and uses the singular", () => {
    expect(removalSentences(preview({ selected_blocks: 0, decisions: 0, open_flags: 0, flags: 0 }))).toEqual([
      "The file and everything read from it are deleted: 75 blocks.",
    ]);
    expect(removalSentences(preview({ blocks: 0, selected_blocks: 0, decisions: 1, open_flags: 0 }))).toEqual([
      "The file and everything read from it are deleted.",
      "1 decision on its blocks stays in the decision log but no longer counts.",
      "Adding the same file again brings back the decisions whose text has not changed.",
    ]);
    expect(removalSentences(preview({ decisions: 0, open_flags: 2 }))[1]).toBe("2 open flags on its blocks stay in the decision log but no longer count.");
  });
});

describe("removing a manual from its card", () => {
  it("confirms with the counts, sends DELETE with a request id and refetches the manuals", async () => {
    const f = installFake();
    const deletes: string[] = [];
    server.use(
      http.get("*/api/sources/:slug/removal", () => HttpResponse.json(preview())),
      http.delete("*/api/sources/:slug", ({ request, params }) => {
        deletes.push(`${String(params.slug)}?${new URL(request.url).searchParams.has("request_id")}`);
        f.sources = f.sources.filter((s) => s.slug !== "alpha");
        return HttpResponse.json(preview({ removed: true }));
      }),
    );
    const { user } = renderApp("/scope");
    const rows = await screen.findAllByTestId("source-row");
    await user.click(within(rows[0]).getByTestId("source-remove"));
    const dlg = await screen.findByTestId("remove-dialog");
    expect(dlg).toHaveAccessibleName("Remove alpha.pdf?");
    expect(await within(dlg).findByText(/3 decisions and 1 open flag/)).toBeInTheDocument();
    expect(within(dlg).getByRole("button", { name: "Keep it" })).toHaveFocus();
    await user.click(within(dlg).getByTestId("remove-confirm"));
    await waitFor(() => expect(deletes).toEqual(["alpha?true"]));
    await waitFor(() => expect(screen.queryByTestId("remove-dialog")).toBeNull());
    await waitFor(() => expect(screen.getAllByTestId("source-row")).toHaveLength(1));
  });
  it("Keep it and Escape change nothing", async () => {
    installFake();
    let deleted = 0;
    server.use(
      http.get("*/api/sources/:slug/removal", () => HttpResponse.json(preview())),
      http.delete("*/api/sources/:slug", () => (deleted++, HttpResponse.json(preview({ removed: true })))),
    );
    const { user } = renderApp("/scope");
    const rows = await screen.findAllByTestId("source-row");
    await user.click(within(rows[0]).getByTestId("source-remove"));
    await user.click(await screen.findByRole("button", { name: "Keep it" }));
    expect(screen.queryByTestId("remove-dialog")).toBeNull();
    await user.click(within(screen.getAllByTestId("source-row")[0]).getByTestId("source-remove"));
    await screen.findByTestId("remove-dialog");
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("remove-dialog")).toBeNull();
    expect(deleted).toBe(0);
  });
  it("says why and keeps the button disabled while a job could touch the manual", async () => {
    installFake();
    server.use(http.get("*/api/sources/:slug/removal", () => HttpResponse.json(preview({ blocked_by: "A job is running. Remove the manual when it has finished." }))));
    const { user } = renderApp("/scope");
    const rows = await screen.findAllByTestId("source-row");
    await user.click(within(rows[0]).getByTestId("source-remove"));
    expect(await screen.findByTestId("remove-blocked")).toHaveTextContent("A job is running");
    expect(screen.getByTestId("remove-confirm")).toBeDisabled();
  });
  it("a 409 from the server is shown, not swallowed, and a second try sends the same request id", async () => {
    installFake();
    const ids: string[] = [];
    server.use(
      http.get("*/api/sources/:slug/removal", () => HttpResponse.json(preview())),
      http.delete("*/api/sources/:slug", ({ request }) => {
        ids.push(new URL(request.url).searchParams.get("request_id") ?? "");
        return HttpResponse.json({ detail: "A job waiting to run will read this manual.", code: "job_active" }, { status: 409 });
      }),
    );
    const { user } = renderApp("/scope");
    const rows = await screen.findAllByTestId("source-row");
    await user.click(within(rows[0]).getByTestId("source-remove"));
    await within(await screen.findByTestId("remove-dialog")).findByText(/3 decisions/);
    await user.click(screen.getByTestId("remove-confirm"));
    expect(await screen.findByTestId("remove-error")).toHaveTextContent("A job waiting to run will read this manual.");
    await user.click(screen.getByTestId("remove-confirm"));
    await waitFor(() => expect(ids).toHaveLength(2));
    expect(ids[0]).not.toBe("");
    expect(ids[1]).toBe(ids[0]);
  });
});
