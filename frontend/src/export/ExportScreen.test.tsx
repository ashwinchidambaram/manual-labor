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
  review: { blocks: 64, approved: 20, auto_approved: 40, edited: 4, numbers_verified: 6, overrides: 0, total_blocks: 64, left_out: {} },
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
    expect(screen.getByTestId("override-form")).toHaveTextContent("one override for each of the 2 blocks still to review");
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
    expect(await screen.findByText(/Override refused for b-doc-p001-01 \(unknown block\)\. Recorded 2 of 3\./)).toBeInTheDocument();
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
  it("groups the blockers by the section the titles lookup names, asking only for the listed ids", async () => {
    const ids = ["b-doc-p001-01", "b-doc-p001-02", "b-doc-p003-01"];
    installFake({ exportStatus: locked({ queued: 3, open_flags: 0, blockers: ids }) });
    const asked: string[][] = [];
    server.use(
      http.get("*/api/verify/titles", ({ request }) => {
        asked.push(new URL(request.url).searchParams.getAll("ids"));
        const row = (block_id: string, page: number, section_title: string) => ({ block_id, doc_id: "doc", page, type: "paragraph", section_title });
        return HttpResponse.json([row(ids[0], 1, "2 Safety"), row(ids[1], 1, "2 Safety"), row(ids[2], 3, "3 Install")]);
      }),
    );
    renderApp("/export");
    const groups = await within(await screen.findByTestId("blocker-list")).findAllByRole("listitem");
    await waitFor(() => expect(groups[0]).toHaveTextContent("2 Safety"));
    const items = within(screen.getByTestId("blocker-list")).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("2 blocks");
    expect(items[1]).toHaveTextContent("3 Install");
    expect(asked).toEqual([ids]);
  });
  it("a complete list counts each group in blocks", async () => {
    installFake({ exportStatus: locked({ queued: 3, open_flags: 2 }) });
    renderApp("/export");
    expect(await screen.findByTestId("blocker-groups-note")).toHaveTextContent("Grouped by the section they are in.");
    expect((await within(screen.getByTestId("blocker-list")).findAllByRole("listitem"))[0]).toHaveTextContent("2 blocks");
  });
  it("unlocked: Export starts a job; a 409 renders the locked view from the refusal body", async () => {
    const f = installFake();
    server.use(
      http.post("*/api/export", () => {
        // the gate closed since the screen read it: the server's status says so too, and the screen rereads it
        f.exportStatus = locked({ open_flags: 1, queued: 0, blockers: ["b-doc-p002-01"] });
        return HttpResponse.json({ detail: "export is locked", code: "export_locked", open_flags: 1, queued: 0, blockers: ["b-doc-p002-01"] }, { status: 409 });
      }),
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

// Second first-use report C3 (design 11 section 18): the server lists 20 blockers at a time; one click with one reason
// overrides every unflagged blocker in successive rounds, never a flagged one, shows progress and keeps the reason.
describe("U10c override the remaining blocks in one decision", () => {
  const ids = Array.from({ length: 46 }, (_, i) => `b-doc-p${String(i + 1).padStart(3, "0")}-01`);
  const flaggedId = ids[5];
  const flag = { flag_id: "flag-000009", block_id: flaggedId, category: "wrong_text" as const, note: "check the 2.5 L line" };

  /** A server that covers each overridden block and lists the first 20 still blocking, as the real one does. */
  function paginatedServer(hold?: (n: number) => Promise<void> | undefined) {
    const covered = new Set<string>();
    const statusNow = (): ExportStatus => {
      const blocking = ids.filter((id) => !covered.has(id));
      const toReview = blocking.filter((id) => id !== flaggedId).length;
      return locked({
        open_flags: 1,
        queued: ids.length - 1,
        blockers: blocking.slice(0, BLOCKER_LIMIT),
        flag_blockers: [flag],
        counts: { in_scope: 60, auto_approved: 14, approved: 0, edited: 0, rejected: 0, overridden: covered.size, blocking: blocking.length, to_review: toReview, flagged: 1 },
      });
    };
    const f = installFake({ exportStatus: statusNow() });
    const bodies: { reason: string; target_id?: string | null; flag_id?: string | null; request_id: string }[] = [];
    server.use(
      http.get("*/api/export/status", () => HttpResponse.json(statusNow())),
      http.post("*/api/export/override", async ({ request }) => {
        const b = (await request.json()) as (typeof bodies)[number];
        bodies.push(b);
        await hold?.(bodies.length);
        // the server refuses a block override on a flagged block (design 11 section 14)
        if (b.target_id === flaggedId) return HttpResponse.json({ detail: `${flaggedId} has an open flag`, code: "invalid" }, { status: 422 });
        covered.add(String(b.target_id));
        f.exportStatus = statusNow();
        return HttpResponse.json(f.exportStatus);
      }),
    );
    return { f, bodies, covered };
  }

  it("one click, one reason: all 45 unflagged blocks are overridden across three pages of blockers, never the flagged one", async () => {
    const { bodies, covered } = paginatedServer();
    const { user } = renderApp("/export");
    const form = await screen.findByTestId("override-form");
    expect(within(form).getByTestId("override-submit")).toHaveTextContent("Override the remaining 45 with this reason");
    expect(form).toHaveTextContent("1 flagged block is left out");
    await user.type(within(form).getByTestId("override-reason"), "vendor deadline");
    await user.click(within(form).getByTestId("override-submit"));
    await waitFor(() => expect(covered.size).toBe(45));
    expect(bodies.some((b) => b.target_id === flaggedId)).toBe(false);
    expect(bodies).toHaveLength(45);
    expect(bodies.every((b) => b.reason === "vendor deadline" && b.flag_id == null)).toBe(true);
    expect(new Set(bodies.map((b) => b.request_id)).size).toBe(45);
    // progress, then the outcome, both said; the reason stays until the person clears it
    await waitFor(() => expect(screen.getByTestId("override-progress")).toHaveTextContent("Recorded 45 of 45"));
    expect(within(form).getByTestId("override-reason")).toHaveValue("vendor deadline");
    // nothing unflagged is left: the button says so, and only the flag still blocks, in its own box
    await waitFor(() => expect(within(form).getByTestId("override-submit")).toBeDisabled());
    expect(within(form).getByTestId("override-submit")).toHaveTextContent("Nothing left to override");
    expect(within(screen.getByTestId("flag-overrides")).getByTestId("flag-override")).toHaveTextContent(flaggedId);
    expect(screen.getByTestId("export-reconcile")).toHaveTextContent("60 blocks in scope = 14 auto-approved + 0 approved by you + 0 edited by you + 45 overridden + 0 to review + 1 flagged");
  });

  it("shows progress while the rounds run", async () => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((r) => (release = r));
    // the 25th override (in the second page of blockers) waits until the test has read the progress
    const { covered } = paginatedServer((n) => (n === 25 ? held : undefined));
    const { user } = renderApp("/export");
    await user.type(await screen.findByTestId("override-reason"), "pilot");
    await user.click(screen.getByTestId("override-submit"));
    const bar = await screen.findByRole("progressbar", { name: /Recording overrides/ });
    await waitFor(() => expect(bar).toHaveAttribute("value", "24"));
    expect(bar).toHaveAttribute("max", "45");
    expect(screen.getByTestId("override-progress")).toHaveTextContent("Recorded 24 of 45");
    expect(screen.getByTestId("override-submit")).toBeDisabled();
    release();
    await waitFor(() => expect(covered.size).toBe(45));
  });
});

describe("U10d the one-click run says when it could not finish", () => {
  const id = (n: number) => `b-doc-p${String(n).padStart(3, "0")}-01`;
  it("blocks reviewed elsewhere during the run are said to need no override, not left as a short tally", async () => {
    const covered = new Set<string>();
    const approved = new Set<string>();
    const statusNow = (): ExportStatus => {
      // a flagged block stays, so the form (and its message) stays on screen after the run
      const ids = [id(1), id(2), id(3)].filter((b) => !covered.has(b) && !approved.has(b));
      const flag = { flag_id: "flag-000001", block_id: id(9), category: "wrong_text" as const, note: null };
      return locked({ open_flags: 1, queued: ids.length, blockers: [...ids, id(9)], flag_blockers: [flag], counts: { in_scope: 11, auto_approved: 7, approved: approved.size, edited: 0, rejected: 0, overridden: covered.size, blocking: ids.length + 1, to_review: ids.length, flagged: 1 } });
    };
    installFake({ exportStatus: statusNow() });
    server.use(
      http.get("*/api/export/status", () => HttpResponse.json(statusNow())),
      http.post("*/api/export/override", async ({ request }) => {
        covered.add(((await request.json()) as { target_id: string }).target_id);
        approved.add(id(3)); // a colleague approved the third block in Verify meanwhile
        return HttpResponse.json(statusNow());
      }),
    );
    const { user } = renderApp("/export");
    await user.type(await screen.findByTestId("override-reason"), "pilot");
    await user.click(screen.getByTestId("override-submit"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Recorded 2 of 3. 1 block no longer needed an override: reviewed or changed meanwhile.");
    expect([...covered]).toEqual([id(1), id(2)]);
  });
  it("when the first page of blockers is all flags, it says the rest cannot be reached instead of stopping quietly", async () => {
    // 21 flagged blocks come first in reading order, then 5 unflagged: the server lists only the first 20
    const all = Array.from({ length: 26 }, (_, i) => id(i + 1));
    const flags = all.slice(0, 21).map((b, i) => ({ flag_id: `flag-0000${String(i).padStart(2, "0")}`, block_id: b, category: "wrong_text" as const, note: null }));
    const st = locked({
      open_flags: 21,
      queued: 5,
      blockers: all.slice(0, BLOCKER_LIMIT),
      flag_blockers: flags,
      counts: { in_scope: 40, auto_approved: 14, approved: 0, edited: 0, rejected: 0, overridden: 0, blocking: 26, to_review: 5, flagged: 21 },
    });
    installFake({ exportStatus: st });
    const posted: string[] = [];
    server.use(http.post("*/api/export/override", async ({ request }) => (posted.push(((await request.json()) as { target_id: string }).target_id), HttpResponse.json(st))));
    const { user } = renderApp("/export");
    await user.type(await screen.findByTestId("override-reason"), "pilot");
    await user.click(screen.getByTestId("override-submit"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Recorded 0 of 5. 5 blocks still to review are not listed yet: the server lists blockers 20 at a time and the first ones are flagged. Decide on the flags below, then press the button again.");
    expect(posted).toEqual([]);
  });
  it("covers no more blocks than the button named: a block that starts blocking during the run is left for a new decision", async () => {
    const covered = new Set<string>();
    let extra = false;
    const statusNow = (): ExportStatus => {
      const ids = [id(1), id(2), id(3), ...(extra ? [id(4)] : [])].filter((b) => !covered.has(b));
      return locked({ open_flags: 0, queued: 3, blockers: ids, flag_blockers: [], counts: { in_scope: 10, auto_approved: 7 - (extra ? 1 : 0), approved: 0, edited: 0, rejected: 0, overridden: covered.size, blocking: ids.length, to_review: ids.length, flagged: 0 } });
    };
    installFake({ exportStatus: statusNow() });
    const posted: string[] = [];
    server.use(
      http.get("*/api/export/status", () => HttpResponse.json(statusNow())),
      http.post("*/api/export/override", async ({ request }) => {
        const b = ((await request.json()) as { target_id: string }).target_id;
        posted.push(b);
        covered.add(b);
        extra = true; // a manual finished scoring: one more block blocks now
        return HttpResponse.json(statusNow());
      }),
    );
    const { user } = renderApp("/export");
    expect(await screen.findByTestId("override-submit")).toHaveTextContent("Override the remaining 3 with this reason");
    await user.type(screen.getByTestId("override-reason"), "pilot");
    await user.click(screen.getByTestId("override-submit"));
    await waitFor(() => expect(screen.getByTestId("override-progress")).toHaveTextContent("Recorded 3 of 3."));
    expect(posted).toEqual([id(1), id(2), id(3)]);
    expect(screen.getByRole("alert")).toHaveTextContent("1 block still to review is not covered (it started blocking after you pressed the button)");
    expect(screen.getByTestId("override-submit")).toHaveTextContent("Override the remaining block with this reason");
  });
});

// Browser-run findings of 2026-10-30 (design 11 section 14): a batch of block overrides never includes a flagged block,
// every count reconciles on screen, and after an export the result is on top.
describe("U10b export: flags need their own decision, counts reconcile, the last export on top", () => {
  const counts = { in_scope: 160, auto_approved: 51, approved: 7, edited: 1, rejected: 0, overridden: 80, blocking: 21, to_review: 20, flagged: 1 };
  const flagged = { flag_id: "flag-000001", block_id: "b-doc-p001-02", category: "wrong_text" as const, note: "digit unclear" };
  const doneSummary: ExportSummary = {
    ...summary,
    articles: 20,
    review: { blocks: 160, auto_approved: 51, approved: 7, edited: 1, overrides: 101, numbers_verified: 7, total_blocks: 184, left_out: { header_footer: 24 } },
  };

  it("a batch leaves a flagged block out and says so; the flag gets its own override", async () => {
    const f = installFake({
      exportStatus: locked({ open_flags: 1, queued: 2, blockers: ["b-doc-p001-01", "b-doc-p001-02", "b-doc-p001-03"], flag_blockers: [flagged], counts }),
    });
    const bodies: { reason: string; target_id?: string | null; flag_id?: string | null }[] = [];
    server.use(
      http.post("*/api/export/override", async ({ request }) => {
        const b = (await request.json()) as (typeof bodies)[number];
        bodies.push(b);
        return HttpResponse.json(f.exportStatus);
      }),
    );
    const { user } = renderApp("/export");
    const form = await screen.findByTestId("override-form");
    expect(within(form).getByTestId("override-submit")).toHaveTextContent("Override the remaining 20 with this reason");
    expect(form).toHaveTextContent("1 flagged block is left out");
    await user.type(within(form).getByTestId("override-reason"), "pilot");
    await user.click(within(form).getByTestId("override-submit"));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies.map((b) => b.target_id)).toEqual(["b-doc-p001-01", "b-doc-p001-03"]);

    const flags = screen.getByTestId("flag-overrides");
    const item = within(flags).getByTestId("flag-override");
    expect(item).toHaveTextContent("b-doc-p001-02");
    expect(item).toHaveTextContent("Wrong text");
    expect(item).toHaveTextContent("digit unclear");
    // named by its block: every flag's button has its own name (review 2 L2)
    const btn = within(item).getByRole("button", { name: "Export b-doc-p001-02 despite its flag" });
    await user.click(btn);
    expect(within(item).getByRole("alert")).toHaveTextContent("Please write why");
    expect(bodies).toHaveLength(2);
    await user.type(within(item).getByRole("textbox"), "checked on paper");
    await user.click(btn);
    await waitFor(() => expect(bodies).toHaveLength(3));
    expect(bodies[2]).toMatchObject({ flag_id: "flag-000001", target_id: null, reason: "checked on paper" });
  });

  it("the locked view reconciles the scope: every block in exactly one count", async () => {
    installFake({ exportStatus: locked({ open_flags: 1, queued: 20, flag_blockers: [flagged], counts }) });
    renderApp("/export");
    const line = await screen.findByTestId("export-reconcile");
    expect(line).toHaveTextContent("160 blocks in scope = 51 auto-approved + 7 approved by you + 1 edited by you + 80 overridden + 20 to review + 1 flagged");
  });

  it("after an export that spent its overrides: the last export is on top, the new lock below it", async () => {
    installFake({ exportStatus: locked({ open_flags: 1, queued: 100, summary: doneSummary, counts: { ...counts, overridden: 0, blocking: 101, to_review: 100, flagged: 1 } }) });
    renderApp("/export");
    const top = await screen.findByTestId("export-summary");
    const lock = screen.getByTestId("export-locked");
    expect(top.compareDocumentPosition(lock) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(top).getByTestId("export-download")).toHaveAttribute("href", "/api/export/download");
    expect(within(top).getByTestId("summary-reconcile")).toHaveTextContent(
      "160 blocks exported = 51 auto-approved + 7 approved by you + 1 edited by you + 101 overridden",
    );
    expect(within(top).getByTestId("summary-left-out")).toHaveTextContent("184 parsed blocks = 160 exported + 24 left out (24 page headers and footers)");
    expect(within(lock).getByRole("heading", { name: "A new export is locked" })).toBeInTheDocument();
    expect(lock).toHaveTextContent("used up its 101 overrides");
  });

  it("after an export with nothing blocking: the last export on top, then Export again", async () => {
    installFake({ exportStatus: { ...locked({ blockers: [], open_flags: 0, queued: 0 }), unlocked: true, summary: doneSummary } });
    renderApp("/export");
    const top = await screen.findByTestId("export-summary");
    const ready = screen.getByTestId("export-ready");
    expect(top.compareDocumentPosition(ready) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(ready).getByRole("heading", { name: /Ready to export again/ })).toBeInTheDocument();
    expect(screen.queryByTestId("export-locked")).toBeNull();
  });

  it("clicking Export: when the job is done the result is on top with its download, the spent lock below", async () => {
    const f = installFake({ exportStatus: { ...locked({ blockers: [], open_flags: 0, queued: 0, counts: { ...counts, overridden: 101, blocking: 0, to_review: 0, flagged: 0 } }), unlocked: false } });
    server.use(
      http.post("*/api/export", () => {
        // the server after the export: the summary is recorded and the overrides are spent (design 11 P3)
        f.exportStatus = locked({ open_flags: 1, queued: 100, summary: doneSummary, counts: { ...counts, overridden: 0, blocking: 101, to_review: 100, flagged: 1 } });
        return HttpResponse.json(makeJob({ id: "exp2", kind: "export", status: "queued" }), { status: 202 });
      }),
    );
    f.jobById = { exp2: makeJob({ id: "exp2", kind: "export", status: "done" }) };
    const { user } = renderApp("/export");
    expect(await screen.findByText(/Overrides cover every remaining block/)).toBeInTheDocument();
    await user.click(screen.getByTestId("export-start"));
    const top = await screen.findByTestId("export-summary");
    expect(within(top).getByTestId("export-fresh")).toHaveTextContent("Export finished");
    // announced through the screen's live region, which was mounted before the export (review 2 L1)
    expect(screen.getByTestId("export-live")).toHaveTextContent("Export finished. Download the zip below.");
    const lock = await screen.findByTestId("export-locked");
    expect(top.compareDocumentPosition(lock) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(lock).getByRole("heading", { name: "A new export is locked" })).toBeInTheDocument();
  });

  it("before any export: the gate is on top and no summary is shown", async () => {
    installFake({ exportStatus: locked({ counts }) });
    renderApp("/export");
    expect(await screen.findByRole("heading", { name: "Export is locked" })).toBeInTheDocument();
    expect(screen.queryByTestId("export-summary")).toBeNull();
  });
});

// Third first-use report (design 11 section 20.11): the "Last export" box describes review markers only for an export
// that has them, and says how the blocks on screen reconcile with the markers (figure blocks have none); the reason box
// keeps the reason until an export uses the overrides up, then is empty.
describe("U20 export: markers described only when the export has them; the reason box is cleared after an export", () => {
  const review = { blocks: 160, auto_approved: 51, approved: 7, edited: 1, overrides: 101, numbers_verified: 7, total_blocks: 184, left_out: { header_footer: 24 } };
  const markers = {
    paragraphs: { auto_approved: 47, approved: 6, edited: 1, overridden: 101 },
    figures: { auto_approved: 4, approved: 1, edited: 0, overridden: 0 },
  };
  const old: ExportSummary = { ...summary, review };

  it("an export recorded before markers: the old sentence, nothing about markers", async () => {
    installFake({ exportStatus: { ...locked({ blockers: [], open_flags: 0, queued: 0 }), unlocked: true, summary: old } });
    renderApp("/export");
    const top = await screen.findByTestId("export-summary");
    expect(top).toHaveTextContent("The 101 overridden blocks went out unreviewed, with machine-cleaned text; manifest.json lists each one with its reason.");
    expect(top).not.toHaveTextContent("ml:");
    expect(within(top).queryByTestId("summary-markers")).toBeNull();
    expect(within(top).queryByRole("alert")).toBeNull();
  });

  it("an export with markers: every paragraph's marker, the figure blocks without one, and the numbers reconcile", async () => {
    installFake({ exportStatus: { ...locked({ blockers: [], open_flags: 0, queued: 0 }), unlocked: true, summary: { ...old, markers } } });
    renderApp("/export");
    const top = await screen.findByTestId("export-summary");
    expect(within(top).getByTestId("summary-markers")).toHaveTextContent(
      "In the articles, each of the 155 paragraphs starts with an invisible ml: comment on the line above it naming who checked it: 47 auto-approved, 6 approved, 1 edited, 101 overridden. The 5 figure blocks have none (4 auto-approved, 1 approved, 0 edited, 0 overridden); each article's review file lists every block with the start of its text.",
    );
    // the per-status addition is said, not left to the reader (review of design 11 section 20.11)
    expect(within(top).getByTestId("summary-markers-sum")).toHaveTextContent(
      "Exported blocks = paragraphs + figure blocks: 51 auto-approved = 47 + 4, 7 approved = 6 + 1, 1 edited = 1 + 0, 101 overridden = 101 + 0.",
    );
    expect(within(top).queryByRole("alert")).toBeNull();
  });

  it("an export without figure blocks says so instead of counting zeros", async () => {
    const none = { paragraphs: { auto_approved: 51, approved: 7, edited: 1, overridden: 101 }, figures: { auto_approved: 0, approved: 0, edited: 0, overridden: 0 } };
    installFake({ exportStatus: { ...locked({ blockers: [], open_flags: 0, queued: 0 }), unlocked: true, summary: { ...old, markers: none } } });
    renderApp("/export");
    const line = await screen.findByTestId("summary-markers");
    expect(line).toHaveTextContent("each of the 160 paragraphs");
    expect(line).toHaveTextContent("There are no figure blocks; each article's review file lists every block with the start of its text.");
    expect(line).not.toHaveTextContent("0 figure blocks");
    expect(screen.queryByTestId("summary-markers-sum")).toBeNull();
  });

  it("markers that do not add up to the exported blocks raise the alert", async () => {
    const off = { ...markers, figures: { ...markers.figures, auto_approved: 3 } };
    installFake({ exportStatus: { ...locked({ blockers: [], open_flags: 0, queued: 0 }), unlocked: true, summary: { ...old, markers: off } } });
    renderApp("/export");
    const top = await screen.findByTestId("export-summary");
    expect(within(top).getByRole("alert")).toHaveTextContent("These counts do not add up");
  });

  it("the reason survives the form closing, and an export clears it, as the label says", async () => {
    const counts = { in_scope: 4, auto_approved: 2, approved: 0, edited: 0, rejected: 0, overridden: 0, blocking: 2, to_review: 2, flagged: 0 };
    const covered = { ...counts, overridden: 2, blocking: 0, to_review: 0 };
    const f = installFake({ exportStatus: locked({ open_flags: 0, queued: 2, counts }) });
    server.use(
      http.post("*/api/export/override", () => {
        f.exportStatus = { ...locked({ blockers: [], open_flags: 0, queued: 2, counts: covered }), unlocked: false };
        return HttpResponse.json(f.exportStatus);
      }),
      http.post("*/api/export", () => {
        f.exportStatus = locked({ open_flags: 0, queued: 2, counts, summary: { ...old, markers } });
        return HttpResponse.json(makeJob({ id: "exp3", kind: "export", status: "queued" }), { status: 202 });
      }),
    );
    f.jobById = { exp3: makeJob({ id: "exp3", kind: "export", status: "done" }) };
    const { user, qc } = renderApp("/export");
    const form = await screen.findByTestId("override-form");
    expect(form).toHaveTextContent("cleared after an export, which uses up the overrides");
    expect(form).not.toHaveTextContent("until you clear it");
    await user.type(within(form).getByTestId("override-reason"), "pilot");
    await user.click(within(form).getByTestId("override-submit"));
    expect(await screen.findByText(/Overrides cover every remaining block/)).toBeInTheDocument();
    expect(screen.queryByTestId("override-form")).toBeNull();
    // a block starts blocking again before any export: the form comes back with the reason still in it
    f.exportStatus = locked({ open_flags: 0, queued: 2, counts });
    await qc.invalidateQueries({ queryKey: ["export", "status"] });
    expect(await screen.findByTestId("override-reason")).toHaveValue("pilot");
    // covered again, then exported: the export uses the overrides up and the box is empty
    f.exportStatus = { ...locked({ blockers: [], open_flags: 0, queued: 2, counts: covered }), unlocked: false };
    await qc.invalidateQueries({ queryKey: ["export", "status"] });
    await user.click(await screen.findByTestId("export-start"));
    await screen.findByTestId("export-fresh");
    expect(await screen.findByTestId("override-reason")).toHaveValue("");
  });
});
