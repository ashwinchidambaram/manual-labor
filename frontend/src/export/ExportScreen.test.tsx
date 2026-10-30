import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { ExportStatus, ExportSummary } from "../api/schema";
import { stepStates } from "../onboarding/StepNav";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake, server } from "../test/server";

const locked = (over: Partial<ExportStatus> = {}): ExportStatus => ({
  unlocked: false,
  open_flags: 2,
  queued: 3,
  blockers: ["b-doc-p001-01", "b-doc-p001-02"],
  overrides: [],
  summary: null,
  zip_path: null,
  ...over,
});
const summary: ExportSummary = {
  articles: 7,
  figures: 3,
  pages_covered: 12,
  docs: 2,
  review: { approved: 20, auto_approved: 40, edited: 4, numbers_verified: 6, overrides: 0 },
  warnings: [],
  zip_bytes: 20480,
  zip_sha256: "ab".repeat(32),
  generated_at: "2026-10-29T10:00:00Z",
};

describe("U10 ExportScreen", () => {
  it("locked: the gate's counts, the blockers as links, and why", async () => {
    installFake({ exportStatus: locked() });
    renderApp("/export");
    const view = await screen.findByTestId("export-locked");
    expect(within(view).getByRole("heading", { name: "Export is locked" })).toBeInTheDocument();
    expect(within(view).getByTestId("reason-flags")).toHaveTextContent("2 open flags");
    expect(within(view).getByTestId("reason-queued")).toHaveTextContent("3 blocks still to review");
    expect(within(view).getAllByTestId("blocker-link").map((a) => a.textContent)).toEqual(["b-doc-p001-01", "b-doc-p001-02"]);
    expect(view).toHaveTextContent("Why: the export only contains text a person or the checks have accepted");
    expect(screen.queryByTestId("export-start")).toBeNull();
  });
  it("a blocker link puts the cursor on that block, keeping the sort, and opens Verify", async () => {
    installFake({ exportStatus: locked() });
    const puts: unknown[] = [];
    server.use(
      http.get("*/api/verify/cursor", () => HttpResponse.json({ sort: "by_page", view_threshold: null, doc_filter: null, current_block_id: null, trail: [] })),
      http.put("*/api/verify/cursor", async ({ request }) => {
        const b = await request.json();
        puts.push(b);
        return HttpResponse.json({ ...(b as object), trail: [] });
      }),
    );
    const { user, router } = renderApp("/export");
    await user.click((await screen.findAllByTestId("blocker-link"))[1]);
    await waitFor(() => expect(router.state.location.pathname).toBe("/verify"));
    expect(puts[0]).toMatchObject({ current_block_id: "b-doc-p001-02", sort: "by_page" });
  });
  it("an override needs a reason and posts it; the answer replaces the status", async () => {
    const f = installFake({ exportStatus: locked() });
    const bodies: { reason: string }[] = [];
    server.use(
      http.post("*/api/export/override", async ({ request }) => {
        bodies.push((await request.json()) as { reason: string });
        f.exportStatus = locked({ blockers: [], overrides: [{ reason: "vendor deadline", at: "2026-10-29T10:00:00Z", target_id: null, flag_id: null }] });
        return HttpResponse.json(f.exportStatus);
      }),
    );
    const { user } = renderApp("/export");
    await screen.findByTestId("export-locked");
    await user.click(screen.getByTestId("override-submit"));
    expect(screen.getByRole("alert")).toHaveTextContent("Please write why");
    expect(bodies).toEqual([]);
    await user.type(screen.getByTestId("override-reason"), "vendor deadline");
    await user.click(screen.getByTestId("override-submit"));
    await waitFor(() => expect(bodies[0]).toMatchObject({ reason: "vendor deadline" }));
    expect(await screen.findByTestId("overrides")).toHaveTextContent("vendor deadline");
    expect(screen.getByTestId("overrides")).toHaveTextContent("recorded in manifest.json");
    expect(screen.getByTestId("export-ready")).toHaveTextContent("Overrides cover every remaining block");
  });
  it("unlocked: Export starts a job; a 409 renders the locked view from the refusal body", async () => {
    installFake();
    server.use(
      http.post("*/api/export", () =>
        HttpResponse.json({ detail: "export is locked", code: "export_locked", open_flags: 1, queued: 0, blockers: ["b-doc-p002-01"] }, { status: 409 }),
      ),
    );
    const { user } = renderApp("/export");
    await user.click(await screen.findByTestId("export-start"));
    const view = await screen.findByTestId("export-locked");
    expect(within(view).getByTestId("reason-flags")).toHaveTextContent("1 open flag");
    expect(within(view).getByTestId("blocker-link")).toHaveTextContent("b-doc-p002-01");
  });
  it("Export posts and tracks the job; the last export's summary and download are shown", async () => {
    const f = installFake({ exportStatus: { ...locked({ blockers: [], open_flags: 0, queued: 0 }), unlocked: true, summary } });
    let posted = 0;
    server.use(http.post("*/api/export", () => (posted++, HttpResponse.json(makeJob({ id: "exp1", kind: "export", status: "queued" }), { status: 202 }))));
    f.jobById = { exp1: makeJob({ id: "exp1", kind: "export", status: "running" }) };
    const { user } = renderApp("/export");
    const s = await screen.findByTestId("export-summary");
    expect(s).toHaveTextContent("Articles7");
    expect(s).toHaveTextContent("Numbers verified by you6");
    expect(screen.getByTestId("export-sha")).toHaveTextContent("ab".repeat(32));
    expect(screen.getByTestId("export-download")).toHaveAttribute("href", "/api/export/download");
    await user.click(screen.getByTestId("export-start"));
    await waitFor(() => expect(posted).toBe(1));
    expect(await screen.findByText(/Building the export/)).toBeInTheDocument();
  });
});

describe("U10 step indicator states", () => {
  it("come from the export gate only", () => {
    const s = stepStates("/scope", locked());
    expect(s.scope.short).toBe("here");
    expect(s.verify.short).toBe("3 to review");
    expect(s.agent.short).toBe("2 open flags");
    expect(s.export.short).toBe("locked: 2 open flags");
    expect(s.export.long).toBe("Step 4 of 4. Locked: 2 open flags, 3 to review.");
    expect(stepStates("/export", undefined).export).toEqual({ short: "here", long: "Step 4 of 4. You are here." });
    expect(stepStates("/scope", locked({ blockers: [], open_flags: 0, queued: 0, unlocked: true })).export.short).toBe("ready");
  });
  it("the nav keeps the link names and shows the Export state", async () => {
    installFake({ exportStatus: locked() });
    renderApp("/scope");
    const nav = screen.getByRole("navigation", { name: "Screens" });
    for (const n of ["Scope", "Verify", "Agent", "Export"]) expect(within(nav).getByRole("link", { name: n })).toBeInTheDocument();
    await waitFor(() => expect(within(nav).getByTestId("step-short-export")).toHaveTextContent("locked: 2 open flags"));
    expect(within(nav).getByRole("link", { name: "Export" })).toHaveAccessibleDescription("Step 4 of 4. Locked: 2 open flags, 3 to review.");
  });
});
