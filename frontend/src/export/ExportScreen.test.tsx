import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { ExportStatus, ExportSummary } from "../api/schema";
import { stepStates } from "../onboarding/StepNav";
import { BLOCKER_LIMIT } from "./ExportScreen";
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
  it("an override needs a reason and records one override per listed blocker, never a blanket one", async () => {
    const f = installFake({ exportStatus: locked() });
    const bodies: { reason: string; target_id?: string | null; flag_id?: string | null; request_id?: string }[] = [];
    server.use(
      http.post("*/api/export/override", async ({ request }) => {
        const b = (await request.json()) as (typeof bodies)[number];
        bodies.push(b);
        const st = f.exportStatus;
        f.exportStatus = locked({
          blockers: (st.blockers ?? []).filter((x) => x !== b.target_id),
          overrides: [...(st.overrides ?? []), { reason: b.reason, at: "2026-10-29T10:00:00Z", target_id: b.target_id ?? null, flag_id: null }],
        });
        return HttpResponse.json(f.exportStatus);
      }),
    );
    const { user } = renderApp("/export");
    await screen.findByTestId("export-locked");
    expect(screen.getByTestId("override-form")).toHaveTextContent("one override for each of the 2 blocks listed above");
    expect(screen.getByTestId("override-form")).toHaveTextContent("a flag raised on it after you record the override blocks the export again, and a block that starts blocking later is not covered");
    await user.click(screen.getByTestId("override-submit"));
    expect(screen.getByRole("alert")).toHaveTextContent("Please write why");
    expect(bodies).toEqual([]);
    await user.type(screen.getByTestId("override-reason"), "vendor deadline");
    await user.click(screen.getByTestId("override-submit"));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies.map((b) => b.target_id)).toEqual(["b-doc-p001-01", "b-doc-p001-02"]);
    expect(bodies.every((b) => b.reason === "vendor deadline" && b.flag_id == null)).toBe(true);
    expect(new Set(bodies.map((b) => b.request_id)).size).toBe(2);
    expect(await screen.findByTestId("overrides")).toHaveTextContent("vendor deadline");
    expect(screen.getByTestId("overrides")).toHaveTextContent("b-doc-p001-01");
    expect(screen.getByTestId("overrides")).not.toHaveTextContent("every block blocking");
    expect(screen.getByTestId("overrides")).toHaveTextContent("recorded in manifest.json");
    expect(screen.getByTestId("export-ready")).toHaveTextContent("Overrides cover every remaining block");
  });
  it("a retry after a failed override resends the same request ids, so nothing is recorded twice", async () => {
    installFake({ exportStatus: locked() });
    const ids: string[] = [];
    let n = 0;
    server.use(
      http.post("*/api/export/override", async ({ request }) => {
        const b = (await request.json()) as { target_id: string; request_id: string };
        ids.push(`${b.target_id} ${b.request_id}`);
        n++;
        if (n === 2) return HttpResponse.json({ detail: "store busy", code: "internal" }, { status: 500 });
        return HttpResponse.json(locked());
      }),
    );
    const { user } = renderApp("/export");
    await screen.findByTestId("export-locked");
    await user.type(screen.getByTestId("override-reason"), "deadline");
    await user.click(screen.getByTestId("override-submit"));
    expect(await screen.findByText(/Override not recorded for b-doc-p001-02: store busy/)).toBeInTheDocument();
    await user.click(screen.getByTestId("override-submit"));
    await waitFor(() => expect(ids).toHaveLength(4));
    expect(ids[2]).toBe(ids[0]);
    expect(ids[3]).toBe(ids[1]);
  });
  it("a 422 on one blocker does not stop the others from being recorded", async () => {
    installFake({ exportStatus: locked({ blockers: ["b-doc-p001-01", "b-doc-p001-02", "b-doc-p001-03"] }) });
    const sent: string[] = [];
    server.use(
      http.post("*/api/export/override", async ({ request }) => {
        const b = (await request.json()) as { target_id: string };
        sent.push(b.target_id);
        if (b.target_id === "b-doc-p001-01") return HttpResponse.json({ detail: "unknown block", code: "unknown_target" }, { status: 422 });
        return HttpResponse.json(locked({ blockers: ["b-doc-p001-01", "b-doc-p001-02", "b-doc-p001-03"] }));
      }),
    );
    const { user } = renderApp("/export");
    await screen.findByTestId("export-locked");
    await user.type(screen.getByTestId("override-reason"), "deadline");
    await user.click(screen.getByTestId("override-submit"));
    expect(await screen.findByText(/Override refused for b-doc-p001-01 \(unknown block\)\. 2 of 3 recorded\./)).toBeInTheDocument();
    expect(sent).toEqual(["b-doc-p001-01", "b-doc-p001-02", "b-doc-p001-03"]);
  });
  it("blocks that no longer block after refreshing the status are skipped", async () => {
    const f = installFake({ exportStatus: locked() });
    const sent: string[] = [];
    let gets = 0;
    server.use(
      http.get("*/api/export/status", () => {
        gets++;
        // the screen loaded both blockers; by the time the form is sent, the first was approved elsewhere
        return HttpResponse.json(gets === 1 ? f.exportStatus : locked({ blockers: ["b-doc-p001-02"] }));
      }),
      http.post("*/api/export/override", async ({ request }) => {
        const b = (await request.json()) as { target_id: string };
        sent.push(b.target_id);
        return HttpResponse.json(locked({ blockers: [] }));
      }),
    );
    const { user } = renderApp("/export");
    await screen.findByTestId("export-locked");
    expect(screen.getAllByTestId("blocker-link")).toHaveLength(2);
    await user.type(screen.getByTestId("override-reason"), "deadline");
    await user.click(screen.getByTestId("override-submit"));
    await waitFor(() => expect(sent).toEqual(["b-doc-p001-02"]));
  });
  it("'first N listed' appears only when the server's list is at its limit", async () => {
    installFake({ exportStatus: locked({ queued: 3, open_flags: 2 }) });
    const r = renderApp("/export");
    expect(await screen.findByTestId("blocker-count")).toHaveTextContent("(2 blocks)");
    r.unmount();
    const many = Array.from({ length: BLOCKER_LIMIT }, (_, i) => `b-doc-p${String(i + 1).padStart(3, "0")}-01`);
    installFake({ exportStatus: locked({ queued: 30, open_flags: 0, blockers: many }) });
    renderApp("/export");
    expect(await screen.findByTestId("blocker-count")).toHaveTextContent(`(first ${BLOCKER_LIMIT} listed by the server)`);
  });
  it("a cut-off list says its groups count only the listed blocks, never a section total; the banner keeps the true total", async () => {
    const many = Array.from({ length: BLOCKER_LIMIT }, (_, i) => `b-doc-p${String(i + 1).padStart(3, "0")}-01`);
    installFake({ exportStatus: locked({ queued: 30, open_flags: 0, blockers: many }) });
    renderApp("/export");
    expect(await screen.findByTestId("blocker-groups-note")).toHaveTextContent(`Of the first ${BLOCKER_LIMIT} the server lists, grouped by section:`);
    const groups = await within(screen.getByTestId("blocker-list")).findAllByRole("listitem");
    for (const g of groups) expect(g).toHaveTextContent(new RegExp(`\\d+ of these ${BLOCKER_LIMIT}`));
    expect(screen.getByTestId("reason-queued")).toHaveTextContent("30 blocks");
  });
  it("a complete list counts each group in blocks", async () => {
    installFake({ exportStatus: locked({ queued: 3, open_flags: 2 }) });
    renderApp("/export");
    expect(await screen.findByTestId("blocker-groups-note")).toHaveTextContent("Grouped by the section they are in.");
    expect((await within(screen.getByTestId("blocker-list")).findAllByRole("listitem"))[0]).toHaveTextContent("2 blocks");
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
    expect(stepStates("/export", undefined).export).toEqual({ short: "here", long: "Step 4 of 4. You are here.", done: false });
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
