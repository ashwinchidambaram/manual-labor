import { describe, expect, it } from "vitest";
import type { DocGroups, ScopeBlockRow } from "../api/schema";
import { bid as fbid, makeDocs } from "../test/fixtures";
import { counts } from "../test/verifyFake";
import { docMismatchDetail, docReconcileText, reconcileDoc, reconcileReview, reviewMismatchDetail, reviewReconcileText } from "./reconcile";

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
    expect(docReconcileText(r)).toBe("9 blocks found = 6 in topics + 1 not placed + 2 page headers and footers, left out");
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
  it("review line: to review is the server's independent queued count, rejected is its own bucket", () => {
    const c = counts({ in_scope: 300, queued: 38, auto_approved: 200, approved: 40, edited: 10, flagged_open: 10, rejected: 2, skipped: 3, pending: 75 });
    const r = reconcileReview(c);
    expect(r).toMatchObject({ queued: 38, done: 50, rejected: 2, ok: true, skipped: 3, sum: 300 });
    expect(reviewReconcileText(r)).toBe("In scope 300 = 38 to review + 200 auto-approved + 50 done + 10 flagged + 2 rejected");
  });
  it("to review is never derived by subtraction: a server queued count that disagrees fails the identity", () => {
    // in_scope - others would give 40; the server says 41, so the parts add up to 301
    const r = reconcileReview(counts({ in_scope: 300, queued: 41, auto_approved: 200, approved: 40, edited: 10, flagged_open: 10, rejected: 0 }));
    expect(r.queued).toBe(41);
    expect(r.ok).toBe(false);
    expect(reviewMismatchDetail(r)).toBe("in scope 300, but to review 41 + auto-approved 200 + done 50 + flagged 10 + rejected 0 = 301");
  });
  it("parts that add up to less than in scope also fail", () => {
    expect(reconcileReview(counts({ in_scope: 5, queued: 1, auto_approved: 2, rejected: 0 })).ok).toBe(false);
  });
});
