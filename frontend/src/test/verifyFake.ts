// MSW handlers and factories for the Verify screen (design 09 section 6, S9).
import { http, HttpResponse } from "msw";
import type {
  AttachOut,
  BlockDetail,
  Cursor,
  DiffOp,
  DocFigure,
  DocReadiness,
  FigureRailItem,
  FigureRecord,
  PageBlock,
  QueueItem,
  QueuePage,
  ReviewActionIn,
  ReviewActionOut,
  ReviewCounts,
} from "../api/schema";
import { cmpItems } from "../verify/queueReducer";
import { server } from "./server";
import { makeJob } from "./fixtures";

export const vid = (n: number, page = 1): string => `b-doc-p${String(page).padStart(3, "0")}-${String(n).padStart(2, "0")}`;

export function makeQueueItem(n: number, over: Partial<QueueItem> = {}): QueueItem {
  return {
    block_id: vid(n),
    doc_id: "doc",
    page: 1,
    type: "paragraph",
    confidence: Math.round(n * 1e3) / 1e4,
    status: "queued",
    has_numeric_spec: false,
    reasons: ["ocr_mean"],
    stale_doc: false,
    ...over,
  };
}

export function makeQueuePage(n: number, over: Partial<QueuePage> = {}): QueuePage {
  const items = Array.from({ length: n }, (_, i) => makeQueueItem(i + 1));
  return { items, total: n, counts: counts({ pending: n, in_scope: n }), docs: [ready("doc")], cursor: cursor(), ...over };
}

export const ready = (id: string): DocReadiness => ({ doc_id: id, state: "ready", stale: false, waiting_for: null });
export const cursor = (over: Partial<Cursor> = {}): Cursor => ({ sort: "worst_first", view_threshold: null, doc_filter: null, current_block_id: null, trail: [], ...over });
export const counts = (over: Partial<ReviewCounts> = {}): ReviewCounts => ({ pending: 0, auto_approved: 0, approved: 0, edited: 0, flagged_open: 0, skipped: 0, in_scope: 0, ...over });

export const op = (o: DiffOp["op"], allowed: boolean, raw: string, clean: string): DiffOp => ({
  op: o,
  allowed,
  raw,
  clean,
  raw_start: 0,
  raw_end: raw.length,
  clean_start: 0,
  clean_end: clean.length,
});

export function makeRecord(id: string, over: Partial<FigureRecord> = {}): FigureRecord {
  return {
    articles: [],
    attach_rule: "proximity",
    bbox: [50, 60, 250, 260],
    caption_original: `Caption of ${id}`,
    confidence: 0.9,
    description_generated: null,
    extraction: "native",
    file: `${id}.png`,
    height: 200,
    id,
    page: 1,
    phash: "abc123",
    product_model: null,
    review: "queued",
    source_doc: "doc",
    svg: null,
    tags: [],
    width: 200,
    ...over,
  };
}

export function makeRailItem(fid: string, article: string, rule = "caption_ref", over: Partial<FigureRailItem> = {}): FigureRailItem {
  return {
    figure_id: fid,
    block_id: `b-doc-p001-${fid.slice(-2)}`,
    record: makeRecord(fid),
    image_url: `/api/figures/${fid}/image`,
    attachment: { article_id: article, rule, confidence: 0.9, anchor_block_id: null },
    status: "queued",
    ...over,
  };
}

export function makeBlockDetail(item: QueueItem, over: Partial<BlockDetail> = {}, blockOver: Partial<BlockDetail["block"]> = {}): BlockDetail {
  const text = `Text of ${item.block_id} set to 0.25 mm.`;
  return {
    block: {
      id: item.block_id,
      doc_id: item.doc_id,
      page: item.page,
      bbox: [72, 100, 300, 140],
      type: item.type,
      reading_order: 0,
      raw_text: text,
      raw_source: "pymupdf",
      raw_text_by_parser: {},
      order_by_parser: {},
      clean_text: text,
      confidence: item.confidence ?? null,
      signals: [],
      status: item.status,
      has_numeric_spec: item.has_numeric_spec,
      numbers_verified: false,
      numeric_tokens: [],
      figure_id: item.type === "figure" ? "FIG-doc-p001-01" : null,
      faithfulness: { passed: true, alignment_ratio: 1, violations: [], diff: [op("equal", true, text, text)], numeric_variants: [] },
      ...blockOver,
    } as BlockDetail["block"],
    article_ids: ["doc--a"],
    page: { doc_id: item.doc_id, page: item.page, width: 612, height: 792, render_url: `/api/docs/${item.doc_id}/pages/${item.page}.png`, source_url: `/api/docs/${item.doc_id}/source` },
    why: [{ kind: "signal", name: "ocr_mean", value: 0.6, critical: false, detail: "mean over 12 words" }],
    parser_texts: {},
    learning: { provenance: "baseline", learned_rules: [], few_shot: [] },
    history: [],
    figures: [],
    flags: [],
    ...over,
  };
}

export interface VerifyFake {
  items: QueueItem[];
  total: number | null;
  counts: ReviewCounts;
  docs: DocReadiness[];
  cursor: Cursor;
  details: Record<string, BlockDetail>;
  detailErrors: Record<string, { status: number; detail: string }>;
  pageBlocks: Record<string, PageBlock[]>;
  rail: Record<string, FigureRailItem[]>;
  docFigures: DocFigure[];
  actions: ReviewActionIn[];
  cursors: Record<string, unknown>[];
  queueReqs: string[];
  attaches: { fid: string; article_id: string; anchor: string | null | undefined }[];
  detaches: { fid: string; article_id: string }[];
  bboxes: { fid: string; bbox: number[] }[];
  disables: string[];
  /** when set, every action waits for it */
  actionGate: Promise<void> | null;
  /** per request-order failure/conflict: called with the action, may return an error response */
  actionHook: ((a: ReviewActionIn, n: number) => { status: number; body: Record<string, unknown> } | null) | null;
  /** queue answers (in order, the last repeats); when empty the live item list is served */
  queueHook: ((search: URLSearchParams) => QueuePage | null) | null;
}

export function installVerifyFake(over: Partial<VerifyFake> = {}): VerifyFake {
  const f: VerifyFake = {
    items: [],
    total: null,
    counts: counts(),
    docs: [ready("doc")],
    cursor: cursor(),
    details: {},
    detailErrors: {},
    pageBlocks: {},
    rail: {},
    docFigures: [],
    actions: [],
    cursors: [],
    queueReqs: [],
    attaches: [],
    detaches: [],
    bboxes: [],
    disables: [],
    actionGate: null,
    actionHook: null,
    queueHook: null,
    ...over,
  };
  const detailOf = (id: string): BlockDetail | undefined => {
    const it = f.items.find((i) => i.block_id === id);
    return f.details[id] ?? (it ? makeBlockDetail(it) : undefined);
  };
  const page = (offset: number, limit: number): QueuePage => ({
    items: f.items.slice(offset, offset + limit),
    total: f.total ?? f.items.length,
    counts: { ...f.counts, pending: f.total ?? f.items.length },
    docs: f.docs,
    cursor: f.cursor,
  });
  let actionN = 0;
  server.use(
    http.get("*/api/verify/queue", ({ request }) => {
      const u = new URL(request.url);
      f.queueReqs.push(u.search);
      const hooked = f.queueHook?.(u.searchParams);
      if (hooked) return HttpResponse.json(hooked);
      return HttpResponse.json(page(Number(u.searchParams.get("offset") ?? 0), Number(u.searchParams.get("limit") ?? 200)));
    }),
    http.get("*/api/verify/cursor", () => HttpResponse.json(f.cursor)),
    http.put("*/api/verify/cursor", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      f.cursors.push(body);
      f.cursor = { ...f.cursor, sort: body.sort as Cursor["sort"], view_threshold: (body.view_threshold as number | null) ?? null, current_block_id: (body.current_block_id as string | null) ?? null };
      return HttpResponse.json(f.cursor);
    }),
    http.get("*/api/verify/blocks/:id", ({ params }) => {
      const id = String(params.id);
      const err = f.detailErrors[id];
      if (err) return HttpResponse.json({ detail: err.detail, code: "x" }, { status: err.status });
      const d = detailOf(id);
      return d ? HttpResponse.json(d) : HttpResponse.json({ detail: "gone", code: "not_found" }, { status: 404 });
    }),
    http.post("*/api/verify/actions", async ({ request }) => {
      const a = (await request.json()) as ReviewActionIn;
      f.actions.push(a);
      const n = actionN++;
      if (f.actionGate) await f.actionGate;
      const bad = f.actionHook?.(a, n);
      if (bad) return HttpResponse.json(bad.body, { status: bad.status });
      const sort = f.cursor.sort;
      let next: QueueItem | null = null;
      const x = f.items.find((i) => i.block_id === a.block_id) ?? null;
      let trail = f.cursor.trail ?? [];
      let status: ReviewActionOut["block_status"] = null;
      if (a.kind === "back") {
        const id = trail[trail.length - 1];
        trail = trail.slice(0, -1);
        next = f.items.find((i) => i.block_id === id) ?? (id ? { ...makeQueueItem(Number(id.slice(-2))), status: "approved" } : null);
      } else if (x) {
        if (a.kind !== "skip") f.items = f.items.filter((i) => i.block_id !== x.block_id);
        next = f.items.find((i) => i.block_id !== x.block_id && cmpItems(sort, i, x) > 0) ?? f.items[0] ?? null;
        trail = [...trail, x.block_id];
        status = a.kind === "approve" ? "approved" : a.kind === "edit" ? "edited" : a.kind === "flag" ? "flagged" : x.status;
      }
      f.cursor = { ...f.cursor, current_block_id: next?.block_id ?? null, trail };
      f.counts = { ...f.counts, approved: f.counts.approved + (a.kind === "approve" ? 1 : 0) };
      const out: ReviewActionOut = { action_id: actionN, next, cursor: f.cursor, counts: { ...f.counts, pending: f.items.length }, block_status: status };
      return HttpResponse.json(out);
    }),
    http.get("*/api/docs/:slug/pages/:page/blocks", ({ params }) => HttpResponse.json(f.pageBlocks[`${params.slug}:${params.page}`] ?? [])),
    http.get("*/api/articles/:id/figures", ({ params }) => HttpResponse.json(f.rail[String(params.id)] ?? [])),
    http.get("*/api/docs/:slug/figures", () => HttpResponse.json(f.docFigures)),
    http.post("*/api/figures/:fid/attach", async ({ params, request }) => {
      const b = (await request.json()) as { article_id: string; anchor_block_id?: string | null };
      f.attaches.push({ fid: String(params.fid), article_id: b.article_id, anchor: b.anchor_block_id });
      const job = makeJob({ id: `job-a${f.attaches.length}`, status: "running" });
      return HttpResponse.json({ override: { seq: 1, op: "attach", figure_id: String(params.fid), article_id: b.article_id }, job } satisfies AttachOut, { status: 202 });
    }),
    http.post("*/api/figures/:fid/detach", async ({ params, request }) => {
      const b = (await request.json()) as { article_id: string };
      f.detaches.push({ fid: String(params.fid), article_id: b.article_id });
      const job = makeJob({ id: `job-d${f.detaches.length}`, status: "running" });
      return HttpResponse.json({ override: { seq: 2, op: "detach", figure_id: String(params.fid), article_id: b.article_id }, job } satisfies AttachOut, { status: 202 });
    }),
    http.put("*/api/figures/:fid/bbox", async ({ params, request }) => {
      const b = (await request.json()) as { bbox: number[] };
      f.bboxes.push({ fid: String(params.fid), bbox: b.bbox });
      const job = makeJob({ id: `job-b${f.bboxes.length}`, status: "running" });
      return HttpResponse.json({ job }, { status: 202 });
    }),
    http.post("*/api/learning/items/:id/disable", ({ params }) => {
      f.disables.push(String(params.id));
      return HttpResponse.json({ id: "snap", created_at: "2026-01-01T00:00:00Z", origin: "project", counts: {}, active: true });
    }),
  );
  return f;
}

/** Make a queue of `n` items with details whose first/last selected fields can be overridden. */
export function seedQueue(f: VerifyFake, n: number): void {
  f.items = Array.from({ length: n }, (_, i) => makeQueueItem(i + 1));
  f.counts = counts({ pending: n, in_scope: n });
}
