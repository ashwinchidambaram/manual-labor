import { describe, expect, it } from "vitest";
import type { QueueItem, ReviewActionOut } from "../api/schema";
import { EMPTY_COUNTS, EMPTY_CURSOR, initialState, nextOffset, queueReducer, type QueueEvent, type QueueState } from "./queueReducer";

const item = (n: number, over: Partial<QueueItem> = {}): QueueItem => ({
  block_id: `b-doc-p001-${String(n).padStart(2, "0")}`,
  doc_id: "doc",
  page: 1,
  type: "paragraph",
  confidence: n / 100,
  status: "queued",
  has_numeric_spec: false,
  reasons: [],
  stale_doc: false,
  excerpt: "",
  ...over,
});
const ids = (s: QueueState) => s.items.map((i) => i.block_id.slice(-2));
const load = (n: number, cursor = EMPTY_CURSOR): QueueState =>
  queueReducer(initialState, {
    type: "loaded",
    items: Array.from({ length: n }, (_, i) => item(i + 1)),
    total: n,
    counts: EMPTY_COUNTS,
    docs: [],
    cursor,
    replace: true,
  });
const out = (next: QueueItem | null, trail: string[] = []): ReviewActionOut => ({
  action_id: 1,
  next,
  cursor: { ...EMPTY_CURSOR, current_block_id: next?.block_id ?? null, trail },
  counts: { ...EMPTY_COUNTS, approved: 1 },
});
const act = (s: QueueState, kind: "approve" | "skip" | "flag" | "edit" | "back", rid: string): QueueState =>
  queueReducer(s, { type: "act", kind, blockId: s.currentId, rid });

describe("VU6 queueReducer", () => {
  it("loads, picks the first item as current and appends without duplicates", () => {
    let s = load(3);
    expect(s.currentId).toBe(item(1).block_id);
    s = queueReducer(s, { type: "loaded", items: [item(3), item(4)], total: 4, counts: EMPTY_COUNTS, docs: [], cursor: EMPTY_CURSOR, replace: false });
    expect(ids(s)).toEqual(["01", "02", "03", "04"]);
    expect(s.currentId).toBe(item(1).block_id);
  });
  it("uses the cursor's current block on a replace", () => {
    const s = load(3, { ...EMPTY_CURSOR, current_block_id: item(2).block_id });
    expect(s.currentId).toBe(item(2).block_id);
  });
  it("approve, edit and flag remove the block; skip keeps it", () => {
    for (const k of ["approve", "edit", "flag"] as const) {
      const s = act(load(3), k, "r1");
      expect(ids(s), k).toEqual(["02", "03"]);
      expect(s.currentId).toBe(item(2).block_id);
      expect(s.total).toBe(2);
    }
    const s = act(load(3), "skip", "r1");
    expect(ids(s)).toEqual(["01", "02", "03"]);
    expect(s.currentId).toBe(item(2).block_id);
  });
  it("predicts by the server's order when the current block is not listed (after back)", () => {
    let s = load(4);
    s = act(s, "skip", "r1"); // 01 stays; current 02
    s = act(s, "approve", "r2"); // current 03
    s = queueReducer(s, { type: "ack", rid: "r1", out: out(item(2)) });
    s = queueReducer(s, { type: "ack", rid: "r2", out: out(item(3), ["01", "02"]) });
    // 02 was approved; go back to it, approve again: the next is 03 (not the skipped 01 at the head)
    s = queueReducer(s, { type: "browse", id: item(2).block_id });
    expect(s.pinned?.block_id).toBe(item(2).block_id);
    s = act(s, "approve", "r3");
    expect(s.currentId).toBe(item(3).block_id);
  });
  it("the server `next` wins on the last ack", () => {
    let s = act(load(3), "approve", "r1");
    expect(s.currentId).toBe(item(2).block_id);
    s = queueReducer(s, { type: "ack", rid: "r1", out: out(item(3), [item(1).block_id]) });
    expect(s.currentId).toBe(item(3).block_id);
    expect(s.counts.approved).toBe(1);
    expect(s.inflight).toBe(0);
    expect(s.snapshots).toEqual([]);
  });
  it("keeps the optimistic position while later actions are in flight", () => {
    let s = act(load(4), "approve", "r1");
    s = act(s, "approve", "r2");
    expect(s.currentId).toBe(item(3).block_id);
    s = queueReducer(s, { type: "ack", rid: "r1", out: out(item(2)) });
    expect(s.currentId).toBe(item(3).block_id);
    s = queueReducer(s, { type: "ack", rid: "r2", out: out(item(3)) });
    expect(s.currentId).toBe(item(3).block_id);
  });
  it("an ack whose next is not listed pins it", () => {
    let s = act(load(2), "approve", "r1");
    const far = item(50);
    s = queueReducer(s, { type: "ack", rid: "r1", out: out(far) });
    expect(s.currentId).toBe(far.block_id);
    expect(s.pinned?.block_id).toBe(far.block_id);
  });
  it("fail restores the snapshot and drops the later ones", () => {
    let s = load(4);
    const before = s;
    s = act(s, "approve", "r1");
    s = act(s, "approve", "r2");
    s = queueReducer(s, { type: "fail", rid: "r1" });
    expect(s.items).toEqual(before.items);
    expect(s.currentId).toBe(before.currentId);
    expect(s.snapshots).toEqual([]);
    expect(s.inflight).toBe(0);
  });
  it("back goes to the end of the trail, or says there is nothing to go back to", () => {
    let s = load(3);
    s = queueReducer(s, { type: "act", kind: "back", blockId: null, rid: "r0" });
    expect(s.notice).toBe("Nothing to go back to");
    expect(s.currentId).toBe(item(1).block_id);
    s = act(s, "approve", "r1"); // trail now holds 01
    s = queueReducer(s, { type: "act", kind: "back", blockId: null, rid: "r2" });
    expect(s.currentId).toBe(item(1).block_id);
    expect(s.pinned?.block_id).toBe(item(1).block_id);
  });
  it("the next page offset is the number of pending items still held", () => {
    let s = load(5);
    s = act(s, "approve", "r1");
    expect(nextOffset(s)).toBe(4);
  });
  it("an empty queue has no current block", () => {
    const s = load(0);
    expect(s.currentId).toBeNull();
    const e: QueueEvent = { type: "act", kind: "approve", blockId: null, rid: "x" };
    expect(queueReducer(s, e).currentId).toBeNull();
  });
});
