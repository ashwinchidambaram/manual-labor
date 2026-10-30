// Live counts must not depend on the order in which the block index and the user's first click arrive.
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";

const row = (id: string) => document.querySelector<HTMLElement>(`[data-testid=row][data-group-id="${id}"]`)!;
const blocks = () => screen.getByTestId("sum-blocks");

describe("live counts when the block index arrives late", () => {
  it("a click made before the block index loaded still shows its count before the server answers", async () => {
    const f = installFake();
    let releaseBlocks!: () => void;
    const blocksHeld = new Promise<void>((r) => (releaseBlocks = r));
    server.use(
      http.get("*/api/scope/blocks", async () => {
        await blocksHeld;
        return HttpResponse.json(f.blocks);
      }),
    );
    // the PUT never answers during the test: the count must come from the client
    f.gate = new Promise<void>(() => undefined);
    const { user } = renderApp("/scope");
    await screen.findByTestId("group-tree");
    await screen.findByTestId("sum-blocks");
    expect(blocks()).toHaveTextContent("0");

    await user.click(row("g-alpha-t001")); // a topic with 3 blocks
    await waitFor(() => expect(row("g-alpha-t001")).toHaveAttribute("data-check", "checked"));
    expect(blocks()).toHaveTextContent("0"); // nothing to count with yet, and that is honest

    releaseBlocks();
    await waitFor(() => expect(blocks()).toHaveTextContent("3"));
    // the PUT reaches the server (and is held there): the count above came from the client
    await waitFor(() => expect(f.puts.length).toBeGreaterThan(0));
    expect(blocks()).toHaveTextContent("3");
  });
});
