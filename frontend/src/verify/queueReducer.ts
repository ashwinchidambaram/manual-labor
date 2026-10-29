// Optimistic queue state (design 09 section 3.2). Pure: the screen dispatches, the server `next` always wins.
import type { Cursor, DocReadiness, QueueItem, ReviewActionOut, ReviewCounts } from "../api/schema";

export type ActKind = "approve" | "edit" | "flag" | "skip" | "back";

export interface QueueState {
  items: QueueItem[];
  /** total pending on the server for this view */
  total: number;
  currentId: string | null;
  /** the current block when it is not in `items` (reached by back, click-to-jump or reload) */
  pinned: QueueItem | null;
  cursor: Cursor;
  counts: ReviewCounts;
  docs: DocReadiness[];
  inflight: number;
  /** state before each unacknowledged action, oldest first */
  snapshots: { rid: string; before: Omit<QueueState, "snapshots" | "seen" | "notice"> }[];
  /** every item ever listed, so `back` can pin a block that already left the queue */
  seen: Record<string, QueueItem>;
  /** short message for the live region */
  notice: string | null;
}

export const EMPTY_COUNTS: ReviewCounts = { pending: 0, auto_approved: 0, approved: 0, edited: 0, flagged_open: 0, skipped: 0, in_scope: 0 };
export const EMPTY_CURSOR: Cursor = { sort: "worst_first", view_threshold: null, doc_filter: null, current_block_id: null, trail: [] };

export const initialState: QueueState = {
  items: [],
  total: 0,
  currentId: null,
  pinned: null,
  cursor: EMPTY_CURSOR,
  counts: EMPTY_COUNTS,
  docs: [],
  inflight: 0,
  snapshots: [],
  seen: {},
  notice: null,
};

export type QueueEvent =
  | { type: "loaded"; items: QueueItem[]; total: number; counts: ReviewCounts; docs: DocReadiness[]; cursor: Cursor; replace: boolean }
  | { type: "act"; kind: ActKind; blockId: string | null; rid: string }
  | { type: "ack"; rid: string; out: ReviewActionOut }
  | { type: "fail"; rid: string }
  | { type: "browse"; id: string }
  | { type: "jump"; item: QueueItem }
  | { type: "pin"; item: QueueItem }
  | { type: "clearNotice" };

type Before = QueueState["snapshots"][number]["before"];
const snap = (s: QueueState): Before => ({
  items: s.items,
  total: s.total,
  currentId: s.currentId,
  pinned: s.pinned,
  cursor: s.cursor,
  counts: s.counts,
  docs: s.docs,
  inflight: s.inflight,
});

const remember = (seen: Record<string, QueueItem>, items: QueueItem[]): Record<string, QueueItem> => {
  const out = { ...seen };
  for (const it of items) out[it.block_id] = it;
  return out;
};

function withCurrent(s: QueueState, id: string | null, pinned?: QueueItem | null): QueueState {
  if (id === null) return { ...s, currentId: null, pinned: null };
  const listed = s.items.find((i) => i.block_id === id);
  if (listed) return { ...s, currentId: id, pinned: null };
  const p = pinned ?? s.pinned;
  return { ...s, currentId: id, pinned: p && p.block_id === id ? p : (s.seen[id] ?? null) };
}

const idKey = (id: string): [string, number, number] => {
  const m = /^b-(.+)-p(\d+)-(\d+)$/.exec(id);
  return m ? [m[1], Number(m[2]), Number(m[3])] : [id, 0, 0];
};
function cmpId(a: string, b: string): number {
  const x = idKey(a);
  const y = idKey(b);
  return x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : x[1] - y[1] || x[2] - y[2];
}
/** The server's queue order (07 section 5.3): worst first = (confidence, id); by page = id. */
export function cmpItems(sort: Cursor["sort"], a: QueueItem, b: QueueItem): number {
  if (sort === "by_page") return cmpId(a.block_id, b.block_id);
  return (a.confidence ?? -1) - (b.confidence ?? -1) || cmpId(a.block_id, b.block_id);
}

/** The item the server will answer as `next` after `x`: the first pending item that sorts after it, else the first. */
export function nextAfter(items: QueueItem[], x: QueueItem | null, sort: Cursor["sort"] = "worst_first"): QueueItem | null {
  if (items.length === 0) return null;
  if (x === null) return items[0];
  return items.find((i) => i.block_id !== x.block_id && cmpItems(sort, i, x) > 0) ?? items[0];
}

export function queueReducer(s: QueueState, e: QueueEvent): QueueState {
  switch (e.type) {
    case "loaded": {
      const items = e.replace
        ? e.items
        : [...s.items, ...e.items.filter((n) => !s.items.some((o) => o.block_id === n.block_id))];
      const seen = remember(s.seen, items);
      const wanted = e.replace ? (e.cursor.current_block_id ?? s.currentId) : s.currentId;
      let next: QueueState = { ...s, items, total: e.total, counts: e.counts, docs: e.docs, cursor: e.cursor, seen };
      // a current block that is not listed (approved earlier, then `back`) is kept: the screen fetches and pins it
      next = withCurrent(next, wanted ?? items[0]?.block_id ?? null);
      return next;
    }
    case "act": {
      const snapshots = [...s.snapshots, { rid: e.rid, before: snap(s) }];
      if (e.kind === "back") {
        const trail = s.cursor.trail ?? [];
        const target = trail[trail.length - 1];
        if (!target) return { ...s, snapshots, inflight: s.inflight + 1, notice: "Nothing to go back to" };
        const pinned = s.seen[target] ?? s.items.find((i) => i.block_id === target) ?? null;
        const base: QueueState = { ...s, snapshots, inflight: s.inflight + 1, cursor: { ...s.cursor, trail: trail.slice(0, -1) } };
        return withCurrent(base, target, pinned);
      }
      const x = e.blockId;
      const leaves = e.kind !== "skip";
      const xi = (x && (s.items.find((i) => i.block_id === x) ?? s.seen[x] ?? s.pinned)) || null;
      const items = leaves ? s.items.filter((i) => i.block_id !== x) : s.items;
      const predicted = nextAfter(items, xi, s.cursor.sort);
      const nextItem = predicted && predicted.block_id !== x ? predicted : (items[0] ?? null);
      const base: QueueState = {
        ...s,
        snapshots,
        inflight: s.inflight + 1,
        items,
        total: leaves && s.items.some((i) => i.block_id === x) ? Math.max(0, s.total - 1) : s.total,
        cursor: x ? { ...s.cursor, trail: [...(s.cursor.trail ?? []), x].slice(-50) } : s.cursor,
      };
      return withCurrent(base, nextItem?.block_id ?? null, nextItem);
    }
    case "ack": {
      const snapshots = s.snapshots.filter((x) => x.rid !== e.rid);
      const nextItem = e.out.next ?? null;
      // later actions are still in flight: the optimistic position is ahead of this answer, keep it
      if (snapshots.length > 0)
        return { ...s, snapshots, inflight: Math.max(0, s.inflight - 1), counts: e.out.counts, seen: nextItem ? { ...s.seen, [nextItem.block_id]: nextItem } : s.seen };
      let base: QueueState = {
        ...s,
        snapshots,
        inflight: Math.max(0, s.inflight - 1),
        cursor: e.out.cursor,
        counts: e.out.counts,
        seen: nextItem ? { ...s.seen, [nextItem.block_id]: nextItem } : s.seen,
      };
      // the acked block's own item (its new status) replaces a pinned copy
      base = withCurrent(base, nextItem?.block_id ?? null, nextItem);
      if (nextItem && base.pinned && base.pinned.block_id === nextItem.block_id) base = { ...base, pinned: nextItem };
      return base;
    }
    case "fail": {
      const i = s.snapshots.findIndex((x) => x.rid === e.rid);
      if (i < 0) return { ...s, inflight: Math.max(0, s.inflight - 1) };
      const before = s.snapshots[i].before;
      return { ...s, ...before, snapshots: [], inflight: 0 };
    }
    case "browse":
      return { ...withCurrent(s, e.id), cursor: s.cursor };
    case "jump": {
      const seen = { ...s.seen, [e.item.block_id]: e.item };
      return withCurrent({ ...s, seen }, e.item.block_id, e.item);
    }
    case "pin": {
      const seen = { ...s.seen, [e.item.block_id]: e.item };
      return { ...s, seen, pinned: s.currentId === e.item.block_id ? e.item : s.pinned };
    }
    case "clearNotice":
      return { ...s, notice: null };
  }
}

/** Offset of the next page: the number of items still pending (acted items are gone server-side too). */
export const nextOffset = (s: QueueState): number => s.items.length;
