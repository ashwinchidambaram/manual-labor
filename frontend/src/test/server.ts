import { http, HttpResponse, delay } from "msw";
import { setupServer } from "msw/node";
import type { CalibrationReport, DocGroups, ExportStatus, Flag, GuideState, JobInfo, ProjectStatus, Proposal, ScopeBlocks, ScopeModels, SelectionOp, SelectionOut, SourceInfo } from "../api/schema";
import { buildGroupsIndex } from "../scope/derive";
import { reduce } from "../scope/selectionReducer";
import { installVerifyFake } from "./verifyFake";
import { coverageFor, makeBlocks, makeDocs, makeJob, makeModels, makeProject, makeSelectionOut, makeSources } from "./fixtures";

export const server = setupServer();

export interface Fake {
  docs: DocGroups[];
  blocks: ScopeBlocks[];
  sources: SourceInfo[];
  models: ScopeModels;
  ids: string[];
  view: "structure" | "topic";
  split: "per_topic" | "per_document";
  puts: SelectionOp[];
  /** when set, every PUT waits for it */
  gate: Promise<void> | null;
  failPut: { status: number; detail: string } | null;
  /** queue of answers for GET /api/jobs?status=...; the last repeats */
  jobPolls: JobInfo[][];
  jobGets: number;
  jobById: Record<string, JobInfo>;
  confirms: number;
  uploads: number;
  applyTier: { status: number; body: Record<string, unknown> } | null;
  applied: string[];
  probes: number;
  status: ProjectStatus;
  requests: string[];
  /** every request, as `METHOD /path` */
  log: string[];
  groupsError: boolean;
  /** when set, the next GET /api/scope/selection answers with the state at request time, after this resolves */
  selGate: Promise<void> | null;
  confirmFail: { status: number; detail: string } | null;
  statusError: boolean;
  jobsError: boolean;
  blocksError: boolean;
  /** module 12: guide flag (null = the endpoint answers 500), export gate, agent data */
  guide: GuideState | null;
  guidePuts: boolean[];
  exportStatus: ExportStatus;
  flags: Flag[];
  proposals: Proposal[];
  calibration: CalibrationReport | null;
}

export function installFake(over: Partial<Fake> = {}): Fake {
  const f: Fake = {
    docs: makeDocs(),
    blocks: makeBlocks(),
    sources: makeSources(),
    models: makeModels(),
    ids: [],
    view: "topic",
    split: "per_topic",
    puts: [],
    gate: null,
    failPut: null,
    jobPolls: [[]],
    jobGets: 0,
    jobById: {},
    confirms: 0,
    uploads: 0,
    applyTier: null,
    applied: [],
    probes: 0,
    status: { project: "demo", docs: [] },
    requests: [],
    log: [],
    groupsError: false,
    selGate: null,
    confirmFail: null,
    statusError: false,
    jobsError: false,
    blocksError: false,
    guide: { seen: true, seen_at: "2026-10-29T00:00:00Z", version: 1 },
    guidePuts: [],
    exportStatus: { unlocked: true, open_flags: 0, queued: 0, blockers: [], overrides: [], summary: null, zip_path: null },
    flags: [],
    proposals: [],
    calibration: null,
    ...over,
  };
  server.events.on("request:start", ({ request }) => {
    f.log.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  const out = (): SelectionOut => {
    const base = makeSelectionOut(f.ids, { active_view: f.view, article_split: f.split }, f.docs);
    return { ...base, coverage: coverageFor(new Set(f.ids), f.docs) };
  };
  server.use(
    http.get("*/api/project", () => HttpResponse.json(makeProject())),
    http.get("*/api/sources", () => HttpResponse.json(f.sources)),
    http.get("*/api/status", () => (f.statusError ? HttpResponse.json({ detail: "status down", code: "internal" }, { status: 500 }) : HttpResponse.json(f.status))),
    http.get("*/api/scope/groups", () => (f.groupsError ? HttpResponse.json({ detail: "boom", code: "internal" }, { status: 500 }) : HttpResponse.json(f.docs))),
    http.get("*/api/scope/blocks", () => (f.blocksError ? HttpResponse.json({ detail: "index down", code: "internal" }, { status: 500 }) : HttpResponse.json(f.blocks))),
    http.get("*/api/scope/selection", async () => {
      const snap = out();
      if (f.selGate) {
        const g = f.selGate;
        f.selGate = null;
        await g;
      }
      return HttpResponse.json(snap);
    }),
    http.get("*/api/scope/summary", () => HttpResponse.json(out().summary)),
    http.get("*/api/scope/models", () => HttpResponse.json(f.models)),
    http.put("*/api/scope/selection", async ({ request }) => {
      const op = (await request.json()) as SelectionOp;
      f.puts.push(op);
      if (f.gate) await f.gate;
      if (f.failPut) return HttpResponse.json({ detail: f.failPut.detail, code: "boom" }, { status: f.failPut.status });
      const next = reduce({ ids: new Set(f.ids), split: f.split, view: f.view }, op, buildGroupsIndex(f.docs));
      f.ids = [...next.ids];
      f.view = next.view;
      f.split = next.split;
      return HttpResponse.json(out());
    }),
    http.get("*/api/jobs", ({ request }) => {
      f.requests.push(new URL(request.url).search);
      if (f.jobsError) return HttpResponse.json({ detail: "jobs down", code: "internal" }, { status: 500 });
      const body = f.jobPolls.length > 1 ? f.jobPolls.shift()! : f.jobPolls[0];
      return HttpResponse.json(body);
    }),
    http.get("*/api/jobs/:id", ({ params }) => {
      f.jobGets++;
      const j = f.jobById[String(params.id)];
      return j ? HttpResponse.json(j) : HttpResponse.json({ detail: "gone", code: "not_found" }, { status: 404 });
    }),
    http.post("*/api/jobs/:id/cancel", () => HttpResponse.json(makeJob({ status: "cancelled" }))),
    http.post("*/api/jobs", () => HttpResponse.json(makeJob({ id: "rerun" }), { status: 202 })),
    http.post("*/api/scope/confirm", () => {
      f.confirms++;
      if (f.confirmFail) return HttpResponse.json({ detail: f.confirmFail.detail, code: "confirm_failed" }, { status: f.confirmFail.status });
      return HttpResponse.json(makeJob({ id: "confirm", plan: { to: "score2" } }), { status: 202 });
    }),
    http.post("*/api/sources", () => {
      f.uploads++;
      return HttpResponse.json(makeJob({ id: "upload", kind: "ingest_run" }), { status: 202 });
    }),
    http.post("*/api/probe", async () => {
      f.probes++;
      f.models = makeModels(true);
      await delay(0);
      return HttpResponse.json({ probe: f.models.probe, suggestions: f.models.suggestions });
    }),
    http.post("*/api/config/apply-tier", async ({ request }) => {
      const body = (await request.json()) as { tier: string };
      f.applied.push(body.tier);
      if (f.applyTier) return HttpResponse.json(f.applyTier.body, { status: f.applyTier.status });
      return HttpResponse.json({ models: f.models.models, stale: [{ node: "clean", state: "stale" }, { node: "score2", state: "stale" }] });
    }),
  );
  server.use(
    http.get("*/api/ui/guide", () => (f.guide ? HttpResponse.json(f.guide) : HttpResponse.json({ detail: "no meta", code: "internal" }, { status: 500 }))),
    http.put("*/api/ui/guide", async ({ request }) => {
      const { seen } = (await request.json()) as { seen: boolean };
      f.guidePuts.push(seen);
      if (!f.guide) return HttpResponse.json({ detail: "no meta", code: "internal" }, { status: 500 });
      f.guide = { seen, seen_at: seen ? "2026-10-29T00:00:01Z" : null, version: 1 };
      return HttpResponse.json(f.guide);
    }),
    http.get("*/api/export/status", () => HttpResponse.json(f.exportStatus)),
    http.get("*/api/flags", () => HttpResponse.json(f.flags)),
    http.get("*/api/agent/items", () => HttpResponse.json([])),
    http.get("*/api/agent/proposals", () => HttpResponse.json(f.proposals)),
    http.get("*/api/calibration", () =>
      f.calibration ? HttpResponse.json(f.calibration) : HttpResponse.json({ detail: "the calibration service is not available", code: "no_calibration" }, { status: 503 }),
    ),
  );
  installVerifyFake(); // an empty review queue, so navigating to /verify from other tests is harmless
  return f;
}
