// Module 8 review fixes: selection durability, stale-fetch ordering, focus after view/split changes.
import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { qk } from "../api/queries";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";

const row = (id: string) => document.querySelector<HTMLElement>(`[data-testid=row][data-group-id="${id}"]`)!;
const blocks = () => screen.getByTestId("sum-blocks");
const loaded = async (path = "/scope") => {
  const r = renderApp(path);
  await screen.findByTestId("group-tree");
  await screen.findByTestId("sum-blocks");
  return r;
};

describe("F1 pending changes survive navigation", () => {
  it("click a topic then press 2 at once: the server still gets the change", async () => {
    const f = installFake();
    const { user, router } = await loaded();
    await user.click(row("g-alpha-t001"));
    await user.keyboard("2");
    expect(router.state.location.pathname).toBe("/verify");
    await waitFor(() => expect(f.puts).toHaveLength(1));
    await waitFor(() => expect(f.ids).toHaveLength(3));
  });
});

describe("F2 pending changes survive unload", () => {
  it("pagehide sends the pending change with keepalive", async () => {
    const f = installFake();
    const keepalive: boolean[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.method === "PUT") keepalive.push(request.keepalive);
    });
    const { user } = await loaded();
    await user.click(row("g-alpha-t001"));
    act(() => {
      window.dispatchEvent(new Event("pagehide"));
    });
    await waitFor(() => expect(f.ids).toHaveLength(3));
    expect(keepalive).toContain(true);
  });
  it("beforeunload also flushes, and a later pagehide does not double-send", async () => {
    const f = installFake();
    const { user } = await loaded();
    await user.click(row("g-alpha-t001"));
    await user.click(row("g-alpha-t002"));
    act(() => {
      window.dispatchEvent(new Event("beforeunload"));
      window.dispatchEvent(new Event("pagehide"));
    });
    await waitFor(() => expect(f.ids).toHaveLength(6));
  });
});

describe("F3 stale selection fetch cannot overwrite newer local state", () => {
  it("a GET issued before a toggle and answered after the save is ignored", async () => {
    let release!: () => void;
    const f = installFake();
    const { user, qc } = await loaded();
    f.selGate = new Promise<void>((r) => (release = r));
    void qc.invalidateQueries({ queryKey: qk.selection }); // e.g. a job-finished reconcile
    await waitFor(() => expect(f.selGate).toBeNull()); // the GET is in flight with the old snapshot
    await user.click(row("g-alpha-t001"));
    await waitFor(() => expect(f.ids).toHaveLength(3));
    await act(async () => {
      release();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(blocks()).toHaveTextContent("3");
    expect(row("g-alpha-t001")).toHaveAttribute("data-check", "checked");
    expect(f.ids).toHaveLength(3);
  });
});

describe("F4 focus survives view and split changes", () => {
  const active = () => document.activeElement as HTMLElement;
  it("t keeps focus on a tree row", async () => {
    installFake();
    const { user } = await loaded();
    await waitFor(() => expect(active().getAttribute("data-testid")).toBe("row"));
    await user.keyboard("t");
    await screen.findByRole("tree", { name: "Document structure" });
    await waitFor(() => expect(active().getAttribute("data-testid")).toBe("row"));
  });
  it("t keeps the same group focused when it exists in the new view, else the first row", async () => {
    installFake();
    const { user } = await loaded("/scope?view=structure");
    await waitFor(() => expect(active().getAttribute("data-testid")).toBe("row"));
    await user.keyboard("j");
    const was = active().getAttribute("data-group-id");
    await user.keyboard("t");
    await screen.findByRole("listbox", { name: "Suggested topics" });
    await waitFor(() => expect(active().getAttribute("data-testid")).toBe("row"));
    // structure ids never exist in the topic view: the first row takes focus
    expect(was).not.toBe(active().getAttribute("data-group-id"));
    expect(active()).toBe(document.querySelector("[data-testid=row]"));
  });
  it("s keeps focus on a tree row", async () => {
    installFake();
    const { user } = await loaded();
    await waitFor(() => expect(active().getAttribute("data-testid")).toBe("row"));
    await user.keyboard("s");
    await waitFor(() => expect(screen.getByRole("radio", { name: /per document/ })).toHaveAttribute("aria-checked", "true"));
    expect(active().getAttribute("data-testid")).toBe("row");
  });
  it("does not steal focus when it was elsewhere", async () => {
    installFake();
    const { user } = await loaded();
    await user.keyboard("o");
    await user.keyboard("t");
    await screen.findByRole("tree", { name: "Document structure" });
    expect(active().closest("[data-zone='tree']")).toBeNull();
  });
});
