import { describe, expect, it } from "vitest";
import type { DocGroups, Group } from "../api/schema";
import recorded from "../test/recorded.json";
import { bid, makeDocs, makeGroup } from "../test/fixtures";
import {
  buildBlockIndex,
  buildGroupsIndex,
  buildTree,
  checkState,
  collapseAction,
  coverageLabel,
  defaultExpanded,
  expandAction,
  lowCohesion,
  moveCursor,
  parseBlockId,
  smartToggle,
  summaryFrom,
  visibleRows,
} from "./derive";

describe("U2 parseBlockId", () => {
  it("parses valid ids", () => {
    expect(parseBlockId("b-clean-p003-012")).toEqual({ slug: "clean", page: 3, n: 12 });
    expect(parseBlockId("b-my-doc-2-p010-001")).toEqual({ slug: "my-doc-2", page: 10, n: 1 });
  });
  it("rejects figure ids and malformed strings", () => {
    for (const bad of ["FIG-clean-p001-001", "b-clean-p1", "b--p001-001", "b-Clean-p001-001", "", "b-clean-pxx-001"])
      expect(parseBlockId(bad), bad).toBeNull();
  });
});

describe("U6 summaryFrom equals the server summary (recorded from the mock project)", () => {
  const docs = recorded.groups as unknown as DocGroups[];
  const idx = buildBlockIndex(recorded.blocks as never);
  for (const sc of recorded.scenarios) {
    it(sc.name, () => {
      const got = summaryFrom(new Set(sc.block_ids), idx, docs, recorded.threshold, sc.split as "per_topic");
      expect(got).toEqual(sc.summary);
    });
  }
  it("counts the Unassigned topic as an article and pages distinct per document", () => {
    const d = makeDocs();
    const un = bid("alpha", 4, 2); // only in Unassigned
    const det = bid("alpha", 4, 1); // only in Details, same page
    const row = (id: string) => ({ id, type: "paragraph" as const, status: "queued" as const, numeric: false });
    const meta = buildBlockIndex([{ doc_id: "alpha", blocks: [row(un), row(det)] }]);
    expect(summaryFrom(new Set([un]), meta, d, 0.85, "per_topic")).toMatchObject({ articles_per_topic: 1 });
    const s = summaryFrom(new Set([un, det]), meta, d, 0.85, "per_topic");
    expect(s).toMatchObject({ docs: 1, articles_per_topic: 2, pages: 1, blocks: 2 });
  });
});

describe("U7 smartToggle", () => {
  it("selects unless fully selected", () => {
    expect(smartToggle(checkState(0, 5))).toBe("select_group");
    expect(smartToggle(checkState(2, 5))).toBe("select_group");
    expect(smartToggle(checkState(5, 5))).toBe("deselect_group");
    expect(checkState(0, 0)).toBe("unchecked");
  });
});

describe("U8 lowCohesion", () => {
  const g = (c: number | null, un = false): Group => makeGroup({ id: "g-x-t001", doc_id: "x", view: "topic", title: "t", block_ids: [], cohesion: c, is_unassigned: un });
  it("is strict at the threshold and never fires for null or Unassigned", () => {
    const p = { low_cohesion: 0.3 };
    expect(lowCohesion(g(0.29), p)).toBe(true);
    expect(lowCohesion(g(0.3), p)).toBe(false);
    expect(lowCohesion(g(null), p)).toBe(false);
    expect(lowCohesion(g(0.01, true), p)).toBe(false);
    expect(lowCohesion(g(0.4), { low_cohesion: 0.5 })).toBe(true);
  });
});

describe("U9 coverageLabel", () => {
  it("formats", () => {
    expect(coverageLabel(0)).toBe("none");
    expect(coverageLabel(1)).toBe("all");
    expect(coverageLabel(0.617)).toBe("62%");
    expect(coverageLabel(null)).toBe("n/a");
  });
});

describe("U10 buildTree", () => {
  const docs = makeDocs();
  it("nests by parent_id in file order", () => {
    const roots = buildTree(docs[0].groups.structure);
    expect(roots.map((r) => r.group.id)).toEqual(["g-alpha-s001", "g-alpha-s003"]);
    expect(roots[0].children.map((c) => c.group.id)).toEqual(["g-alpha-s002"]);
    expect(roots[0].children[0].parent).toBe(roots[0]);
  });
  it("treats unknown parents as roots and breaks cycles", () => {
    const a = makeGroup({ id: "a", doc_id: "x", view: "structure", title: "a", block_ids: [], parent_id: "zzz" });
    const b = makeGroup({ id: "b", doc_id: "x", view: "structure", title: "b", block_ids: [], parent_id: "c" });
    const c = makeGroup({ id: "c", doc_id: "x", view: "structure", title: "c", block_ids: [], parent_id: "b" });
    const roots = buildTree([a, b, c]);
    expect(roots.map((r) => r.group.id)).toContain("a");
    const seen = new Set<string>();
    const walk = (n: (typeof roots)[number]): void => {
      expect(seen.has(n.group.id)).toBe(false);
      seen.add(n.group.id);
      n.children.forEach(walk);
    };
    roots.forEach(walk);
    expect(seen.size).toBe(3);
  });
  it("only expands roots that have children by default", () => {
    expect([...defaultExpanded(docs)]).toEqual(["g-alpha-s001"]);
  });
});

describe("U11 cursor navigation", () => {
  const docs = makeDocs();
  const open = new Set(["g-alpha-s001"]);
  const rows = visibleRows(docs, "structure", open);
  it("lists only visible rows", () => {
    expect(rows.map((r) => r.group.id)).toEqual(["g-alpha-s001", "g-alpha-s002", "g-alpha-s003", "g-beta-s001"]);
    expect(visibleRows(docs, "structure", new Set()).map((r) => r.group.id)).toEqual(["g-alpha-s001", "g-alpha-s003", "g-beta-s001"]);
    expect(rows[1]).toMatchObject({ depth: 2, parentId: "g-alpha-s001", posInSet: 1, setSize: 1 });
  });
  it("moves and clamps", () => {
    expect(moveCursor(rows, "g-alpha-s001", 1)).toBe("g-alpha-s002");
    expect(moveCursor(rows, "g-alpha-s001", -1)).toBe("g-alpha-s001");
    expect(moveCursor(rows, "g-beta-s001", 1)).toBe("g-beta-s001");
    expect(moveCursor(rows, null, 1)).toBe("g-alpha-s001");
    expect(moveCursor([], null, 1)).toBeNull();
  });
  it("expand/collapse semantics", () => {
    expect(expandAction(rows, "g-alpha-s003", open)).toBeNull();
    expect(expandAction(rows, "g-alpha-s001", open)).toEqual({ move: "g-alpha-s002" });
    expect(expandAction(rows, "g-alpha-s001", new Set())).toEqual({ expand: "g-alpha-s001" });
    expect(collapseAction(rows, "g-alpha-s001", open)).toEqual({ collapse: "g-alpha-s001" });
    expect(collapseAction(rows, "g-alpha-s002", open)).toEqual({ move: "g-alpha-s001" });
    expect(collapseAction(rows, "g-alpha-s003", open)).toBeNull();
  });
  it("topic rows put Unassigned first", () => {
    const d = makeDocs();
    d[0].groups.topics.reverse();
    const t = visibleRows(d, "topic", new Set());
    expect(t[0].group.is_unassigned).toBe(true);
  });
  it("groups index covers subtree and selectable ids", () => {
    const idx = buildGroupsIndex(docs);
    expect(idx.subtree.get("g-alpha-s001")).toHaveLength(5);
    expect(idx.own.get("g-alpha-s001")).toHaveLength(2);
    expect(idx.selectable.size).toBe(10);
  });
});
