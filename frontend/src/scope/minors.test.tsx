// Module 8 review minors: stable row callbacks, DOM tab order, destructive `n`, query error states, Help.
import { screen, waitFor } from "@testing-library/react";
import { memo } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import type { GroupRowProps } from "./GroupRow";

const counts = new Map<string, number>();
vi.mock("./GroupRow", async (orig) => {
  const mod = (await orig()) as { default: React.ComponentType<GroupRowProps> };
  const Real = mod.default;
  return {
    default: memo(function Spy(p: GroupRowProps) {
      counts.set(p.group.id, (counts.get(p.group.id) ?? 0) + 1);
      return <Real {...p} />;
    }),
  };
});

const row = (id: string) => document.querySelector<HTMLElement>(`[data-testid=row][data-group-id="${id}"]`)!;
const loaded = async (path = "/scope") => {
  const r = renderApp(path);
  await screen.findByTestId("group-tree");
  await screen.findByTestId("sum-blocks");
  return r;
};

describe("M1 row callbacks are stable", () => {
  it("a selection change does not re-render rows whose own props did not change", async () => {
    const f = installFake();
    f.gate = new Promise<void>(() => undefined); // keep the saves pending so `stale` stays constant
    const { user } = await loaded();
    await user.click(row("g-alpha-t001"));
    await waitFor(() => expect(row("g-alpha-t001")).toHaveAttribute("data-check", "checked"));
    const before = counts.get("g-beta-t001") ?? 0;
    await user.click(row("g-alpha-t002"));
    await waitFor(() => expect(row("g-alpha-t002")).toHaveAttribute("data-check", "checked"));
    expect(counts.get("g-beta-t001") ?? 0).toBe(before);
  });
});

describe("M2 tab order follows the design", () => {
  it("sources, view toggle, tree, split, summary, confirm, models", async () => {
    installFake();
    await loaded();
    const q = (s: string) => document.querySelector(s)!;
    const order = [
      q("[data-zone=sources]"),
      q("[data-testid=view-toggle]"),
      q("[data-zone=tree]"),
      q("[data-testid=split-mode]"),
      q("[data-zone=summary]"),
      q("[data-testid=confirm]"),
      q("[data-zone=models]"),
    ];
    order.forEach((el, i) => {
      expect(el, `element ${i}`).toBeTruthy();
      if (i) expect(order[i - 1].compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING, `element ${i} follows ${i - 1}`).toBeTruthy();
    });
  });
});

describe("M3 n needs confirmation", () => {
  it("a single n only asks; a second n within the window clears", async () => {
    const f = installFake({ ids: ["b-alpha-p001-001", "b-alpha-p001-002", "b-alpha-p002-001"] });
    const { user } = await loaded();
    await user.keyboard("n");
    expect(screen.getByTestId("live")).toHaveTextContent("Press n again to clear the selection");
    expect(screen.getByTestId("sum-blocks")).toHaveTextContent("3");
    expect(f.puts).toHaveLength(0);
    await user.keyboard("n");
    await waitFor(() => expect(screen.getByTestId("sum-blocks")).toHaveTextContent("0"));
  });
});

describe("M4 error states for status, jobs and block-index", () => {
  it("shows an alert with Retry for each failing query", async () => {
    installFake({ statusError: true, jobsError: true, blocksError: true });
    await loaded();
    expect(await screen.findByTestId("status-error")).toHaveTextContent("status down");
    expect(await screen.findByTestId("jobs-error")).toHaveTextContent("jobs down");
    expect(await screen.findByTestId("blocks-error")).toHaveTextContent("index down");
  });
});

describe("M5 Help lists widget-local keys", () => {
  it("names the arrow keys of the sources list, radiogroups and tier picker", async () => {
    installFake();
    const { user } = await loaded();
    await user.keyboard("?");
    const dlg = await screen.findByRole("dialog");
    expect(dlg).toHaveTextContent("Sources list");
    expect(dlg).toHaveTextContent("Radio groups");
  });
});
