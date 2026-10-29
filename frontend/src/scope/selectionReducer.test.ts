import { describe, expect, it } from "vitest";
import type { SelectionOp } from "../api/schema";
import { bid, makeDocs } from "../test/fixtures";
import { buildGroupsIndex } from "./derive";
import { reduce, type SelState } from "./selectionReducer";

const idx = buildGroupsIndex(makeDocs());
const base: SelState = { ids: new Set(), split: "per_topic", view: "topic" };
const op = (o: Partial<SelectionOp> & Pick<SelectionOp, "op">): SelectionOp => ({ block_ids: [], subtree: false, request_id: "r", ...o });
const a = (p: number, n: number) => bid("alpha", p, n);

describe("U3 select / deselect", () => {
  it("adds, removes, is idempotent and drops unknown ids", () => {
    const s1 = reduce(base, op({ op: "select", block_ids: [a(1, 1), a(1, 1), "b-zzz-p001-001"] }), idx);
    expect([...s1.ids]).toEqual([a(1, 1)]);
    const s2 = reduce(s1, op({ op: "select", block_ids: [a(1, 1)] }), idx);
    expect(s2.ids).toBe(s1.ids); // no change keeps the instance
    const s3 = reduce(s2, op({ op: "deselect", block_ids: [a(1, 1), a(9, 9)] }), idx);
    expect(s3.ids.size).toBe(0);
    expect(s1.ids.size).toBe(1); // never mutates
  });
});

describe("U4 group ops", () => {
  it("subtree selects descendants; deselect is the inverse; leaf equals own blocks", () => {
    const sub = reduce(base, op({ op: "select_group", group_id: "g-alpha-s001", subtree: true }), idx);
    expect(sub.ids.size).toBe(5);
    expect(reduce(sub, op({ op: "deselect_group", group_id: "g-alpha-s001", subtree: true }), idx).ids.size).toBe(0);
    const own = reduce(base, op({ op: "select_group", group_id: "g-alpha-s001", subtree: false }), idx);
    expect(own.ids.size).toBe(2);
    const leaf = reduce(base, op({ op: "select_group", group_id: "g-alpha-s002", subtree: true }), idx);
    expect([...leaf.ids].sort()).toEqual([a(2, 1), a(2, 2), a(3, 1)]);
  });
  it("topic rows use their own blocks and empty groups are a no-op", () => {
    const t = reduce(base, op({ op: "select_group", group_id: "g-alpha-t002" }), idx);
    expect(t.ids.size).toBe(3);
    expect(reduce(base, op({ op: "select_group", group_id: "g-beta-t000" }), idx)).toBe(base);
    expect(reduce(base, op({ op: "select_group", group_id: "nope" }), idx)).toBe(base);
  });
});

describe("U5 set_view / set_split", () => {
  it("keep the very same ids instance", () => {
    const s = reduce(base, op({ op: "select", block_ids: [a(1, 1)] }), idx);
    const v = reduce(s, op({ op: "set_view", view: "structure" }), idx);
    expect(v.ids).toBe(s.ids);
    expect(v.view).toBe("structure");
    const p = reduce(v, op({ op: "set_split", split: "per_document" }), idx);
    expect(p.ids).toBe(s.ids);
    expect(p.split).toBe("per_document");
  });
});
