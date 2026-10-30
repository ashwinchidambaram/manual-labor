import { render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { makeQueryClient } from "../queryClient";
import AppShell from "../shell/AppShell";
import { ComingSoon } from "../shell/Stubs";
import { bid, makeJob, makeModels } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";

const a = (p: number, n: number) => bid("alpha", p, n);
const loaded = async (path = "/scope") => {
  const r = renderApp(path);
  await screen.findByTestId("group-tree");
  await screen.findByTestId("sum-blocks");
  return r;
};

describe("C1 SourcesList", () => {
  it("shows ready / processing / failed chips, OCR warning only when set, scanned badge", async () => {
    const f = installFake();
    f.sources = [
      f.sources[0],
      f.sources[1],
      { ...f.sources[0], slug: "gamma", filename: "gamma.pdf", nodes: [{ node: "parse", state: "failed" }] },
    ];
    await loaded();
    const rows = screen.getAllByTestId("source-row");
    expect(within(rows[0]).getByTestId("source-chip")).toHaveTextContent("Ready");
    expect(within(rows[0]).queryByTestId("ocr-warning")).toBeNull();
    expect(within(rows[0]).queryByTestId("scanned-badge")).toBeNull();
    expect(within(rows[1]).getByTestId("source-chip")).toHaveTextContent("Processing clean");
    expect(within(rows[1]).getByTestId("ocr-warning")).toHaveTextContent("OCR: 2 page(s) without a text layer");
    expect(within(rows[1]).getByTestId("scanned-badge")).toHaveTextContent("Scanned PDF");
    expect(within(rows[2]).getByTestId("source-chip")).toHaveTextContent("Failed: parse");
    expect(rows[0]).toHaveTextContent("4 pages");
    expect(screen.getByRole("button", { name: "Re-run" })).toBeInTheDocument();
  });
  it("lists unregistered files and uploads multipart, showing the job", async () => {
    const f = installFake();
    f.status = { project: "demo", docs: [], unregistered_sources: ["new.pdf"] };
    f.jobPolls = [[makeJob({ id: "upload", kind: "ingest_run" })]];
    const { user } = await loaded();
    expect(await screen.findByTestId("unregistered")).toHaveTextContent("new.pdf: Not ingested");
    await user.upload(screen.getByTestId("upload-input"), new File(["%PDF-1"], "new.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(f.uploads).toBe(1));
    expect(await screen.findByTestId("job-row")).toHaveTextContent("run");
  });
  it("arrow keys move between source rows", async () => {
    installFake();
    const { user } = await loaded();
    await user.keyboard("o");
    expect(document.activeElement).toHaveAttribute("data-source", "alpha");
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toHaveAttribute("data-source", "beta");
  });
});

describe("C6 SelectionSummary", () => {
  it("renders every number, the estimated wording and a live region", async () => {
    installFake({ ids: [a(2, 1), a(2, 2)] });
    await loaded();
    expect(screen.getByTestId("sum-blocks")).toHaveTextContent("2");
    expect(screen.getByTestId("sum-figures")).toHaveTextContent("1");
    expect(screen.getByTestId("sum-pages")).toHaveTextContent("1");
    expect(screen.getByTestId("sum-docs")).toHaveTextContent("1");
    expect(screen.getByTestId("sum-queued")).toHaveTextContent("2");
    expect(screen.getByTestId("sum-numeric")).toHaveTextContent("1");
    expect(screen.getByTestId("selection-summary")).toHaveTextContent(/Estimated review/);
    expect(screen.getByTestId("selection-summary").querySelector("[aria-live=polite]")).not.toBeNull();
  });
  it("shows zeros when nothing is selected and follows the PUT result", async () => {
    installFake();
    const { user } = await loaded();
    expect(screen.getByTestId("sum-blocks")).toHaveTextContent("0");
    expect(screen.getByTestId("sum-articles")).toHaveTextContent("0");
    await user.keyboard("j{Space}");
    await waitFor(() => expect(screen.getByTestId("sum-blocks")).toHaveTextContent("3"));
    expect(screen.getByTestId("sum-articles")).toHaveTextContent("1");
  });
});

describe("C7 SplitModeControl", () => {
  it("shows counts per mode and a hint in the structure view", async () => {
    installFake({ ids: [a(1, 1), a(2, 2), "b-beta-p001-001"] });
    await loaded();
    const per = screen.getByRole("radio", { name: /per topic \(3\)/ });
    expect(per).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: /per document \(2\)/ })).toBeInTheDocument();
    expect(screen.queryByTestId("split-hint")).toBeNull();
    expect(screen.getByTestId("sum-articles")).toHaveTextContent("3");
  });
  it("s cycles, the arrow keys move the radio, and the structure hint appears", async () => {
    const f = installFake({ ids: [a(1, 1), "b-beta-p001-001"] });
    const { user } = await loaded("/scope?view=structure");
    expect(screen.getByTestId("split-hint")).toBeInTheDocument();
    await user.keyboard("s");
    expect(screen.getByTestId("sum-articles")).toHaveTextContent("2");
    await waitFor(() => expect(f.split).toBe("per_document"));
    screen.getByRole("radio", { name: /per document/ }).focus();
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("radio", { name: /per topic/ })).toHaveAttribute("aria-checked", "true");
  });
});

describe("C8 ModelPanel", () => {
  it("shows tasks, hardware, the suggested tier and its pull commands", async () => {
    installFake();
    await loaded();
    const panel = await screen.findByTestId("model-panel");
    for (const t of ["cleanup", "grouping", "vision", "verifier", "embeddings"]) expect(within(panel).getByTestId(`model-${t}`)).toBeInTheDocument();
    expect(within(panel).getByTestId("model-cleanup")).toHaveTextContent("mock/mock-1");
    expect(within(panel).getByTestId("model-verifier")).toHaveTextContent("not set");
    expect(within(panel).queryByTestId("model-agent")).toBeNull();
    expect(within(panel).getByTestId("hardware")).toHaveTextContent("16 GB RAM");
    expect(within(panel).getByTestId("default-tier")).toHaveTextContent("small");
    expect(within(panel).getByTestId("pull-commands")).toHaveTextContent("ollama pull cleanup-s");
    expect(within(panel).getByRole("radio", { name: /small/ })).toHaveAttribute("aria-checked", "true");
    await userClick(within(panel).getByRole("radio", { name: /large/ }));
    expect(within(panel).getByTestId("tier-table")).toHaveTextContent("cleanup-l");
    expect(within(panel).queryByTestId("pull-commands")).toBeNull();
  });
  it("applies a tier and reports the stale stages", async () => {
    const f = installFake();
    const { user } = await loaded();
    await user.click(await screen.findByTestId("apply-tier"));
    expect(await screen.findByTestId("apply-result")).toHaveTextContent("Applied small: 2 stages will re-run.");
    expect(f.applied).toEqual(["small"]);
  });
  it("shows the 422 detail", async () => {
    const f = installFake();
    f.applyTier = { status: 422, body: { detail: "tier large does not fit", code: "tier_unfit" } };
    const { user } = await loaded();
    await user.click(await screen.findByTestId("apply-tier"));
    expect(await screen.findByTestId("apply-error")).toHaveTextContent("tier large does not fit");
  });
  it("offers a hardware probe when none exists", async () => {
    const f = installFake({ models: makeModels(false) });
    const { user } = await loaded();
    await user.click(await screen.findByRole("button", { name: "Run hardware probe" }));
    await waitFor(() => expect(f.probes).toBe(1));
    expect(await screen.findByTestId("hardware")).toBeInTheDocument();
  });
});

async function userClick(el: HTMLElement) {
  const { default: ue } = await import("@testing-library/user-event");
  await ue.setup().click(el);
}

describe("C9 JobsBar", () => {
  it("polls while a job runs, stops when idle, and reconciles caches when it finishes", async () => {
    const f = installFake();
    const job = makeJob({ id: "j1" });
    f.jobPolls = [[job], [job], []];
    f.jobById = { j1: makeJob({ id: "j1", status: "done" }) };
    await loaded();
    const bar = await screen.findByTestId("jobs-bar");
    const prog = within(bar).getByRole("progressbar", { hidden: true }) as HTMLProgressElement;
    expect(prog.value).toBe(0.5);
    expect(bar).toHaveTextContent("1/2");
    await waitFor(() => expect(screen.queryByTestId("jobs-bar")).toBeNull(), { timeout: 5000 });
    const polls = f.requests.length;
    expect(polls).toBe(3);
    expect(f.log.filter((l) => l === "GET /api/scope/groups").length).toBeGreaterThanOrEqual(2); // refetched after done
    await new Promise((r) => setTimeout(r, 2300));
    expect(f.requests.length).toBe(polls); // no polling while idle
  }, 15000);
  it("shows a failed job with Dismiss", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "j2" })], []];
    f.jobById = { j2: makeJob({ id: "j2", status: "failed", error: "parser crashed" }) };
    const { user } = await loaded();
    const alert = await screen.findByTestId("job-failed", undefined, { timeout: 5000 });
    expect(alert).toHaveTextContent("parser crashed");
    await user.click(within(alert).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("job-failed")).toBeNull();
    expect(f.log).not.toContain("GET /api/sources/x");
  }, 15000);
  it("cancel posts to the job", async () => {
    const f = installFake();
    f.jobPolls = [[makeJob({ id: "j3" })]];
    const { user } = await loaded();
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(f.log).toContain("POST /api/jobs/j3/cancel"));
  });
});

describe("C13 ConfirmButton", () => {
  it("is disabled with a reason at 0 blocks and g announces it", async () => {
    const f = installFake();
    const { user, router } = await loaded();
    expect(screen.getByTestId("confirm")).toBeDisabled();
    expect(screen.getByTestId("confirm-reason")).toHaveTextContent("Nothing selected");
    await user.keyboard("g");
    expect(screen.getByTestId("live")).toHaveTextContent("Nothing selected");
    expect(f.confirms).toBe(0);
    expect(router.state.location.pathname).toBe("/scope");
  });
  it("posts the confirmation after the selection is saved and goes to /verify", async () => {
    const f = installFake({ ids: [a(1, 1)] });
    const { user, router } = await loaded();
    await user.keyboard("nn"); // pending PUT must be flushed before confirming
    await user.keyboard("a");
    await user.click(screen.getByTestId("confirm"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/verify"));
    expect(f.confirms).toBe(1);
    const lastPut = f.log.lastIndexOf("PUT /api/scope/selection");
    expect(lastPut).toBeGreaterThan(-1);
    expect(f.log.indexOf("POST /api/scope/confirm")).toBeGreaterThan(lastPut);
    expect(f.ids).toHaveLength(10);
  });
  it("g confirms from the keyboard", async () => {
    const f = installFake({ ids: [a(1, 1)] });
    const { user, router } = await loaded();
    await user.keyboard("g");
    await waitFor(() => expect(router.state.location.pathname).toBe("/verify"));
    expect(f.confirms).toBe(1);
  });
});

describe("C14 ErrorBoundary", () => {
  it("renders a fallback and the nav still works", async () => {
    installFake();
    function Bomb(): JSX.Element {
      throw new Error("kaboom");
    }
    const router = createMemoryRouter(
      [{ element: <AppShell />, children: [{ path: "/boom", element: <Bomb /> }, { path: "/verify", element: <ComingSoon name="Verify" /> }] }],
      { initialEntries: ["/boom"] },
    );
    const { default: ue } = await import("@testing-library/user-event");
    const user = ue.setup();
    const spy = (await import("vitest")).vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <QueryClientProvider client={makeQueryClient({ retry: false })}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("error-boundary")).toHaveTextContent("kaboom");
    await user.click(screen.getByRole("link", { name: "Verify" }));
    expect(screen.getByTestId("stub-verify")).toBeInTheDocument();
    expect(screen.queryByTestId("error-boundary")).toBeNull();
    spy.mockRestore();
  });
});
