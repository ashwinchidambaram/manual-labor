import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { invalidateAfterJob, qk } from "../api/queries";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { ToastProvider, useToast } from "./Toast";

function Pusher() {
  const t = useToast();
  return (
    <button type="button" onClick={() => t.error("Disk full")}>
      boom
    </button>
  );
}

describe("S6 Toast", () => {
  it("shows an error toast as an alert with Dismiss", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Pusher />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: "boom" }));
    const t = screen.getByTestId("toast");
    expect(t).toHaveAttribute("role", "alert");
    expect(t).toHaveTextContent("Disk full");
    await user.click(within(t).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("toast")).toBeNull();
  });
  it("a failing confirm is shown as a visible toast, not only in the live region", async () => {
    const f = installFake({ ids: ["b-alpha-p001-001"] });
    f.confirmFail = { status: 500, detail: "queue is full" };
    const { user } = renderApp("/scope");
    await screen.findByTestId("group-tree");
    await waitFor(() => expect(screen.getByTestId("confirm")).toBeEnabled());
    await user.click(screen.getByTestId("confirm"));
    const toast = await screen.findByTestId("toast");
    expect(toast).toHaveTextContent("queue is full");
    expect(screen.getByTestId("live")).toHaveTextContent("Could not confirm scope");
  });
});

describe("S4 invalidateAfterJob", () => {
  it("also invalidates the verify, rail, docFigures and pageBlocks prefixes plus caller extras", async () => {
    const qc = new QueryClient();
    const keys = [["verify", "queue"], ["rail", "b1"], ["docFigures", "d"], ["pageBlocks", "d", 1], ["mine", 1], qk.sources];
    for (const k of keys) qc.setQueryData(k, 1);
    invalidateAfterJob(qc, [["mine"]]);
    for (const k of keys) expect(qc.getQueryState(k)?.isInvalidated, JSON.stringify(k)).toBe(true);
    qc.setQueryData(["unrelated"], 1);
    expect(qc.getQueryState(["unrelated"])?.isInvalidated).toBe(false);
  });
  it("useJobWatch polls one job until it ends", async () => {
    const { useJobWatch } = await import("../hooks/useJobsPolling");
    const f = installFake();
    f.jobById = { w1: makeJob({ id: "w1", status: "running" }) };
    const { QueryClientProvider } = await import("@tanstack/react-query");
    const qc = new QueryClient();
    let seen = "";
    function W() {
      seen = useJobWatch("w1").data?.status ?? "";
      return null;
    }
    render(
      <QueryClientProvider client={qc}>
        <W />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(seen).toBe("running"));
    f.jobById = { w1: makeJob({ id: "w1", status: "done" }) };
    await act(async () => {});
    await waitFor(() => expect(seen).toBe("done"), { timeout: 4000 });
    const gets = f.jobGets;
    await new Promise((r) => setTimeout(r, 1500));
    expect(f.jobGets).toBe(gets);
  }, 10000);
});
