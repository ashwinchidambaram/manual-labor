// Count identities shown on screen (design 12 section 2.5). Pure: the numbers come from API answers only, and an
// identity that fails is reported, never papered over.
import type { DocGroups, ReviewCounts, ScopeBlockRow } from "../api/schema";

export interface DocReconcile {
  parsed: number;
  headerFooter: number;
  /** blocks in a non-catch-all group of the partitioning view */
  inGroups: number;
  unassigned: number;
  /** parsed, not a header/footer, and in no group */
  missing: string[];
  /** in a group but not in the block index */
  unknown: string[];
  /** in more than one group */
  duplicated: string[];
  /** which view partitions the blocks: topics normally, sections when topic grouping failed */
  view: "topics" | "sections";
  ok: boolean;
}

/** parsed = headers/footers (excluded) + in groups + unassigned, with every id accounted for exactly once. */
export function reconcileDoc(blocks: readonly ScopeBlockRow[], doc: DocGroups): DocReconcile {
  const topicsOk = doc.groups.topic_status !== "failed" && doc.groups.topics.length > 0;
  const groups = topicsOk ? doc.groups.topics : doc.groups.structure;
  const index = new Set(blocks.map((b) => b.id));
  const hf = new Set(blocks.filter((b) => b.type === "header" || b.type === "footer").map((b) => b.id));
  const seen = new Map<string, number>();
  let inGroups = 0;
  let unassigned = 0;
  for (const g of groups)
    for (const id of g.block_ids) {
      seen.set(id, (seen.get(id) ?? 0) + 1);
      if (g.is_unassigned) unassigned++;
      else inGroups++;
    }
  const missing = blocks.filter((b) => !hf.has(b.id) && !seen.has(b.id)).map((b) => b.id);
  const unknown = [...seen.keys()].filter((id) => !index.has(id));
  const duplicated = [...seen.entries()].filter(([, n]) => n > 1).map(([id]) => id);
  const parsed = blocks.length;
  const ok = missing.length === 0 && unknown.length === 0 && duplicated.length === 0 && parsed === hf.size + inGroups + unassigned;
  return { parsed, headerFooter: hf.size, inGroups, unassigned, missing, unknown, duplicated, view: topicsOk ? "topics" : "sections", ok };
}

export function docReconcileText(r: DocReconcile): string {
  return `${r.parsed} parsed = ${r.headerFooter} headers and footers (excluded) + ${r.inGroups} in ${r.view} + ${r.unassigned} unassigned`;
}

export function docMismatchDetail(r: DocReconcile): string {
  const parts: string[] = [];
  if (r.missing.length) parts.push(`${r.missing.length} in no group, first ${r.missing[0]}`);
  if (r.unknown.length) parts.push(`${r.unknown.length} grouped but not parsed, first ${r.unknown[0]}`);
  if (r.duplicated.length) parts.push(`${r.duplicated.length} in two groups, first ${r.duplicated[0]}`);
  if (!parts.length) parts.push(`${r.parsed} parsed, ${r.headerFooter + r.inGroups + r.unassigned} accounted for`);
  return parts.join("; ");
}

export interface ReviewReconcile {
  inScope: number;
  /** waiting for a person: the server's own `queued` count, never derived from the others */
  queued: number;
  auto: number;
  done: number;
  flagged: number;
  rejected: number;
  skipped: number;
  /** the independently counted buckets added up */
  sum: number;
  ok: boolean;
}

/**
 * in_scope = queued + auto-approved + approved + edited + flagged + rejected, every term an independent server count
 * (skipped is a view inside queued/auto, pending depends on the view filter). The identity can fail, and then says so.
 */
export function reconcileReview(c: ReviewCounts): ReviewReconcile {
  const done = c.approved + c.edited;
  const sum = c.queued + c.auto_approved + done + c.flagged_open + c.rejected;
  return { inScope: c.in_scope, queued: c.queued, auto: c.auto_approved, done, flagged: c.flagged_open, rejected: c.rejected, skipped: c.skipped, sum, ok: sum === c.in_scope };
}

export function reviewReconcileText(r: ReviewReconcile): string {
  return `In scope ${r.inScope} = ${r.queued} to review + ${r.auto} auto-approved + ${r.done} done + ${r.flagged} flagged + ${r.rejected} rejected`;
}

export function reviewMismatchDetail(r: ReviewReconcile): string {
  return `in scope ${r.inScope}, but to review ${r.queued} + auto-approved ${r.auto} + done ${r.done} + flagged ${r.flagged} + rejected ${r.rejected} = ${r.sum}`;
}

export const MISMATCH = (detail: string): string => `Counts do not add up (${detail}). Nothing was changed; please report this.`;
