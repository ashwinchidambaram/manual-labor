import { describe, expect, it } from "vitest";
import type { DocGroups, ScopeBlockRow } from "../api/schema";
import { bid as fbid, makeDocs } from "../test/fixtures";
import { counts } from "../test/verifyFake";
import { docMismatchDetail, docReconcileText, reconcileDoc, reconcileReview, reviewReconcileText } from "./reconcile";

const row = (id: string, type: ScopeBlockRow["type"] = "paragraph"): ScopeBlockRow => ({ id, type, status: "queued", numeric: false });
const bid = (p: number, n: number) => fbid("alpha", p, n);
const alpha = (): DocGroups => makeDocs()[0];
const alphaBlocks = (): ScopeBlockRow[] => [
  ...[bid(1, 1), bid(1, 2), bid(2, 1), bid(2, 2), bid(3, 1), bid(4, 1), bid(4, 2)].map((id) => row(id)),
  row(bid(1, 3), "header"),
  row(bid(4, 3), "footer"),
];

describe("U4 reconcile", () => {
  it("doc identity: parsed = headers/footers + in topics + unassigned", () => {
    const r = reconcileDoc(alphaBlocks(), alpha());
    expect(r).toMatchObject({ parsed: 9, headerFooter: 2, inGroups: 6, unassigned: 1, missing: [], ok: true, view: "topics" });
    expect(docReconcileText(r)).toBe("9 parsed = 2 headers and footers (excluded) + 6 in topics + 1 unassigned");
  });
  it("a parsed block in no group is reported as missing", () => {
    const r = reconcileDoc([...alphaBlocks(), row(bid(5, 1))], alpha());
    expect(r.ok).toBe(false);
    expect(r.missing).toEqual([bid(5, 1)]);
    expect(docMismatchDetail(r)).toContain(bid(5, 1));
  });
  it("a grouped id that was never parsed, and an id in two groups, both fail", () => {
    const blocks = alphaBlocks().filter((b) => b.id !== bid(3, 1));
    expect(reconcileDoc(blocks, alpha()).unknown).toEqual([bid(3, 1)]);
    const d = alpha();
    d.groups.topics[1].block_ids.push(bid(4, 1));
    const r = reconcileDoc(alphaBlocks(), d);
    expect(r.duplicated).toEqual([bid(4, 1)]);
    expect(r.ok).toBe(false);
  });
  it("falls back to sections when topic grouping failed", () => {
    const d = alpha();
    d.groups.topic_status = "failed";
    d.groups.topics = [];
    const r = reconcileDoc(alphaBlocks(), d);
    expect(r.view).toBe("sections");
    expect(r).toMatchObject({ inGroups: 7, unassigned: 0, ok: true });
  });
  it("review identity counts skipped inside to-review and ignores view-filter additions in pending", () => {
    const c = counts({ in_scope: 300, auto_approved: 200, approved: 40, edited: 10, flagged_open: 10, skipped: 3, pending: 75 });
    const r = reconcileReview(c);
    expect(r).toMatchObject({ queued: 40, done: 50, ok: true, skipped: 3 });
    expect(reviewReconcileText(r)).toBe("In scope 300 = 40 to review + 200 auto-approved + 50 done + 10 flagged");
  });
  it("a negative to-review count is not ok", () => {
    expect(reconcileReview(counts({ in_scope: 5, auto_approved: 4, approved: 2 })).ok).toBe(false);
  });
});
