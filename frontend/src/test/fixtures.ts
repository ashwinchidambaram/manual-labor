// Small typed factories for component/unit tests (2 docs, nested sections, 3 topics + Unassigned).
import type {
  CoverageReport,
  DocGroups,
  Group,
  GroupCoverage,
  GroupsFile,
  JobInfo,
  ProjectInfo,
  ScopeBlocks,
  ScopeModels,
  SelectionOut,
  SourceInfo,
} from "../api/schema";
import { buildGroupsIndex } from "../scope/derive";
import recorded from "./recorded.json";

export const PARAMS = (recorded.groups[0].groups as unknown as GroupsFile).params;

export const bid = (slug: string, page: number, n: number): string => `b-${slug}-p${String(page).padStart(3, "0")}-${String(n).padStart(3, "0")}`;

export function makeGroup(over: Partial<Group> & Pick<Group, "id" | "doc_id" | "view" | "title" | "block_ids">): Group {
  return {
    block_count: over.block_ids.length,
    cohesion: null,
    figure_count: 0,
    is_unassigned: false,
    level: 1,
    page_ranges: [{ start: 1, end: 1 }],
    parent_id: null,
    section_ids: [],
    section_number: null,
    slug: over.id,
    ...over,
  };
}

function groupsFile(doc: string, structure: Group[], topics: Group[]): GroupsFile {
  return {
    algo_version: "t",
    doc_id: doc,
    embedding_dim: 0,
    embedding_model: "m",
    fingerprint: "0".repeat(64),
    grouping_model: "mock",
    learning_snapshot: "baseline",
    overlap: [],
    overrides_applied: 0,
    overrides_stale: [],
    params: PARAMS,
    stragglers: [],
    structure,
    title_sources: {},
    topic_error: null,
    topic_status: "ok",
    topics,
    unassigned: [],
  };
}

export function makeDocs(): DocGroups[] {
  const a = (p: number, n: number) => bid("alpha", p, n);
  const alphaS: Group[] = [
    makeGroup({ id: "g-alpha-s001", doc_id: "alpha", view: "structure", title: "Safety", section_number: "1.", block_ids: [a(1, 1), a(1, 2)] }),
    makeGroup({ id: "g-alpha-s002", doc_id: "alpha", view: "structure", title: "Tools", section_number: "1.1", level: 2, parent_id: "g-alpha-s001", block_ids: [a(2, 1), a(2, 2), a(3, 1)], page_ranges: [{ start: 2, end: 3 }] }),
    makeGroup({ id: "g-alpha-s003", doc_id: "alpha", view: "structure", title: "Drive", section_number: "2.", block_ids: [a(4, 1), a(4, 2)] }),
  ];
  const alphaT: Group[] = [
    makeGroup({ id: "g-alpha-t000", doc_id: "alpha", view: "topic", title: "Unassigned blocks", is_unassigned: true, slug: "unassigned", block_ids: [a(4, 2)] }),
    makeGroup({ id: "g-alpha-t001", doc_id: "alpha", view: "topic", title: "Intro", cohesion: 0.8, section_ids: ["g-alpha-s001"], block_ids: [a(1, 1), a(1, 2), a(2, 1)], page_ranges: [{ start: 1, end: 2 }] }),
    makeGroup({ id: "g-alpha-t002", doc_id: "alpha", view: "topic", title: "Details", cohesion: 0.2, figure_count: 1, section_ids: ["g-alpha-s002", "g-alpha-s003"], block_ids: [a(2, 2), a(3, 1), a(4, 1)], page_ranges: [{ start: 2, end: 4 }] }),
  ];
  const b = (p: number, n: number) => bid("beta", p, n);
  const betaS: Group[] = [
    makeGroup({ id: "g-beta-s001", doc_id: "beta", view: "structure", title: "Beta doc", block_ids: [b(1, 1), b(1, 2), b(2, 1)], page_ranges: [{ start: 1, end: 2 }] }),
  ];
  const betaT: Group[] = [
    makeGroup({ id: "g-beta-t000", doc_id: "beta", view: "topic", title: "Unassigned blocks", is_unassigned: true, block_ids: [] }),
    makeGroup({ id: "g-beta-t001", doc_id: "beta", view: "topic", title: "Beta topic", cohesion: 0.3, block_ids: [b(1, 1), b(1, 2), b(2, 1)], page_ranges: [{ start: 1, end: 2 }] }),
  ];
  const mk = (doc: string, s: Group[], t: Group[]): DocGroups => ({
    doc_id: doc,
    groups: groupsFile(doc, s, t),
    coverage: { doc_id: doc, selected: 0, selectable: 0, structure: [], topics: [] },
  });
  return [mk("alpha", alphaS, alphaT), mk("beta", betaS, betaT)];
}

export function makeBlocks(): ScopeBlocks[] {
  const row = (id: string, over: Partial<ScopeBlocks["blocks"][number]> = {}) => ({
    id,
    type: "paragraph" as const,
    status: "queued" as const,
    numeric: false,
    ...over,
  });
  const a = (p: number, n: number) => bid("alpha", p, n);
  const b = (p: number, n: number) => bid("beta", p, n);
  return [
    {
      doc_id: "alpha",
      blocks: [row(a(1, 1)), row(a(1, 2), { status: "auto_approved" }), row(a(2, 1), { numeric: true }), row(a(2, 2), { type: "figure" }), row(a(3, 1)), row(a(4, 1)), row(a(4, 2))],
    },
    { doc_id: "beta", blocks: [row(b(1, 1)), row(b(1, 2)), row(b(2, 1), { numeric: true })] },
  ];
}

function cov(g: Group, own: number, subSel: number | null, subTotal: number | null): GroupCoverage {
  return {
    group_id: g.id,
    view: g.view,
    selected: own,
    total: g.block_ids.length,
    fraction: g.block_ids.length ? own / g.block_ids.length : null,
    subtree_selected: subSel,
    subtree_total: subTotal,
    subtree_fraction: subTotal ? (subSel ?? 0) / subTotal : null,
  };
}

/** Server-shaped coverage computed from a selection (test double for coverage(), 04 section 4). */
export function coverageFor(ids: ReadonlySet<string>, docs: DocGroups[]): CoverageReport[] {
  const idx = buildGroupsIndex(docs);
  return docs.map((d) => {
    const sel = (g: Group) => g.block_ids.filter((x) => ids.has(x)).length;
    const sub = (g: Group) => {
      const all = idx.subtree.get(g.id) ?? g.block_ids;
      return [all.filter((x) => ids.has(x)).length, all.length] as const;
    };
    return {
      doc_id: d.doc_id,
      selected: [...ids].filter((x) => x.startsWith(`b-${d.doc_id}-`)).length,
      selectable: d.groups.structure.reduce((n, g) => n + g.block_ids.length, 0),
      structure: d.groups.structure.map((g) => cov(g, sel(g), ...sub(g))),
      topics: d.groups.topics.map((g) => cov(g, sel(g), sel(g), g.block_ids.length)),
    };
  });
}

export function makeSelectionOut(ids: string[] = [], over: Partial<SelectionOut["selection"]> = {}, docs = makeDocs()): SelectionOut {
  const set = new Set(ids);
  const blocks = makeBlocks();
  const meta = new Map(blocks.flatMap((d) => d.blocks.map((b) => [b.id, b] as const)));
  const picked = ids.map((i) => meta.get(i)!).filter(Boolean);
  const topicsHit = docs.flatMap((d) => d.groups.topics.filter((t) => t.block_ids.some((x) => set.has(x))));
  const docsHit = new Set(ids.map((i) => i.split("-")[1]));
  return {
    selection: { block_ids: ids, article_split: "per_topic", active_view: "topic", ...over },
    dropped: [],
    coverage: coverageFor(set, docs),
    summary: {
      docs: docsHit.size,
      articles_per_topic: topicsHit.length,
      articles_per_document: docsHit.size,
      articles: over.article_split === "per_document" ? docsHit.size : topicsHit.length,
      blocks: ids.length,
      figures: picked.filter((p) => p.type === "figure").length,
      pages: new Set(ids.map((i) => i.split("-p")[0] + "-p" + i.split("-p")[1].split("-")[0])).size,
      review_load: {
        queued: picked.filter((p) => p.status === "queued").length,
        numeric_queued: picked.filter((p) => p.status === "queued" && p.numeric).length,
        threshold: 0.85,
      },
    },
  };
}

export const makeSources = (): SourceInfo[] => [
  { slug: "alpha", filename: "alpha.pdf", kind: "born_digital_pdf", pages: 4, ocr_warning: null, nodes: [{ node: "parse", state: "fresh" }, { node: "group", state: "fresh" }] },
  { slug: "beta", filename: "beta.pdf", kind: "scanned_pdf", pages: 2, ocr_warning: "2 page(s) without a text layer; OCR text is less reliable", nodes: [{ node: "parse", state: "fresh" }, { node: "clean", state: "stale" }] },
];

export const makeProject = (): ProjectInfo =>
  ({
    name: "demo",
    root: "/tmp/demo",
    config: { threshold: 0.85, article_split: "per_topic" },
    learning: {},
    mock: true,
    tool_version: "0",
  }) as unknown as ProjectInfo;

export const makeJob = (over: Partial<JobInfo> = {}): JobInfo => ({
  id: "j1",
  kind: "run",
  plan: {},
  status: "running",
  progress: 0.5,
  units_done: 1,
  units_total: 2,
  node: "group",
  doc: "alpha",
  message: "grouping",
  created_at: "2026-01-01T00:00:00Z",
  ...over,
});

export const makeModels = (probe = true): ScopeModels => {
  const ref = { provider: "mock", model: "mock-1", api_base: null, api_key_env: null };
  const tier = (m: string, fits = true) => ({ approx_gb: 2, est_tokens_per_s: null, fits, model: m, note: null, present: false, provider: "ollama", pull_command: `ollama pull ${m}`, speed_class: "ok" as const });
  const row = (task: "cleanup" | "grouping" | "vision" | "verifier" | "embeddings") => ({ task, small: tier(`${task}-s`), medium: tier(`${task}-m`), large: tier(`${task}-l`, false), api: tier(`${task}-api`) });
  return {
    models: { cleanup: ref, grouping: ref, vision: ref, verifier: null, embeddings: ref, metadata: null, agent: null },
    probe: probe
      ? ({
          ram_gb: 16,
          gpu: null,
          effective_model_memory_gb: 10,
          ollama: { reachable: false, installed: true, models: [], host: "h", version: null },
        } as unknown as ScopeModels["probe"])
      : null,
    suggestions: probe
      ? {
          default_tier: "small",
          default_reason: "16 GB RAM",
          pull_commands: { small: ["ollama pull cleanup-s"] },
          rows: (["cleanup", "grouping", "vision", "verifier", "embeddings"] as const).map(row),
        }
      : null,
  };
};
