// What waits for a person, in one place (design 11 section 17). The export gate's partition of the scope
// (`ExportStatus.counts`) is the one source every screen reads: the step rail, the next-step card, the Verify status
// strip and the Export screen. "To review" is `to_review` only: a block an override covers is "overridden (not
// reviewed)", never "to review", and a block held by a flag is "flagged". Pure, so the words are unit-tested.
import type { ExportStatus, ReviewCounts } from "../api/schema";

export interface ScopeTerms {
  /** where the terms came from: the export gate's partition, or the Verify counts (no override term) */
  source: "export" | "review";
  inScope: number;
  /** waits for a person's review: not covered by an override, not held by a flag */
  toReview: number;
  /** covered by an override: will be exported unreviewed */
  overridden: number;
  auto: number;
  approved: number;
  edited: number;
  /** approved + edited */
  done: number;
  /** held by an open flag no override covers */
  flagged: number;
  rejected: number;
  /** the independently counted buckets added up */
  sum: number;
  ok: boolean;
}

function terms(source: ScopeTerms["source"], c: Omit<ScopeTerms, "source" | "done" | "sum" | "ok">): ScopeTerms {
  const done = c.approved + c.edited;
  const sum = c.toReview + c.overridden + c.auto + done + c.flagged + c.rejected;
  return { source, ...c, done, sum, ok: sum === c.inScope };
}

/** The export gate's partition, or null when the status has none (not loaded, or an older server). */
export function scopeTerms(st: ExportStatus | undefined | null): ScopeTerms | null {
  const c = st?.counts;
  if (!c || typeof c.to_review !== "number" || typeof c.flagged !== "number") return null;
  return terms("export", {
    inScope: c.in_scope,
    toReview: c.to_review,
    overridden: c.overridden,
    auto: c.auto_approved,
    approved: c.approved,
    edited: c.edited,
    flagged: c.flagged,
    rejected: c.rejected,
  });
}

/** The Verify counts as terms: the fallback while the export status is not there. They know nothing of overrides. */
export function reviewTerms(c: ReviewCounts): ScopeTerms {
  return terms("review", {
    inScope: c.in_scope,
    toReview: c.queued,
    overridden: 0,
    auto: c.auto_approved,
    approved: c.approved,
    edited: c.edited,
    flagged: c.flagged_open,
    rejected: c.rejected,
  });
}

/** Blocks waiting for review per the gate: its partition when present, else its raw queued count (older server). */
export function toReviewOf(st: ExportStatus | undefined | null): number {
  return scopeTerms(st)?.toReview ?? st?.queued ?? 0;
}

/** Open flags that hold the export (no override covers them); the Agent step keeps `open_flags`. */
export function blockingFlagsOf(st: ExportStatus | undefined | null): number {
  return st?.flag_blockers ? st.flag_blockers.length : (st?.open_flags ?? 0);
}

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

/** "105 overridden blocks (not reviewed)" */
export const overriddenWords = (n: number): string => `${plural(n, "overridden block")} (not reviewed)`;

/** "In scope 173 = 0 to review + 105 overridden + 60 auto-approved + 8 done + 0 flagged + 0 rejected" */
export function scopeEquation(t: ScopeTerms): string {
  const parts = [`${t.toReview} to review`];
  if (t.overridden > 0) parts.push(`${t.overridden} overridden`);
  parts.push(`${t.auto} auto-approved`, `${t.done} done`, `${t.flagged} flagged`, `${t.rejected} rejected`);
  return `In scope ${t.inScope} = ${parts.join(" + ")}`;
}

export function scopeMismatch(t: ScopeTerms): string {
  const over = t.overridden > 0 ? ` + overridden ${t.overridden}` : "";
  return `in scope ${t.inScope}, but to review ${t.toReview}${over} + auto-approved ${t.auto} + done ${t.done} + flagged ${t.flagged} + rejected ${t.rejected} = ${t.sum}`;
}

/**
 * The terms the Verify strip shows above its list (design 11 section 17). The gate's partition and the list's counts
 * are two reads: when they agree bucket for bucket the gate's terms are shown; when only the scope is the same (a write
 * the gate has not seen yet) the list's buckets are shown with the gate's overrides kept apart from those waiting, so
 * the line still adds up and an overridden block is never called "to review"; when the scope differs (a manual scored
 * between the reads) the list's own counts are shown, so the strip never names blocks the list does not have yet.
 */
export function stripTerms(gate: ScopeTerms | null | undefined, c: ReviewCounts): ScopeTerms {
  const own = reviewTerms(c);
  if (!gate || gate.inScope !== c.in_scope) return own;
  const same =
    gate.auto === own.auto &&
    gate.approved === own.approved &&
    gate.edited === own.edited &&
    gate.rejected === own.rejected &&
    gate.toReview + gate.overridden + gate.flagged === c.queued + c.flagged_open;
  if (same) return gate;
  // a flag override covers a block the list counts as flagged, not queued: until the gate is read again such a block
  // reads as overridden and flagged and "to review" is one low; the line still adds up (accepted, design 11 section 17)
  const overridden = Math.min(gate.overridden, c.queued);
  return terms("review", { ...own, toReview: c.queued - overridden, overridden });
}
