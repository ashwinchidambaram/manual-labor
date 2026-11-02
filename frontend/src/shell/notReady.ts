// The documents the export gate cannot see yet, in words (design 11 section 20.17). One source for the Export screen,
// the step rail and the next-step card, so they name the same files and agree on which ones a running job will bring
// in. A document counts as "being processed" only while a queued or running job will take it to score2 (CLAUDE.md:
// never claim work that is not happening). Pure, so the words are unit-tested.
import type { ExportStatus, JobInfo, SourceInfo } from "../api/schema";
import { notReadyOf } from "./scopeTerms";

export interface NotReady {
  /** display names (file names when known) of documents that need a run nobody has started */
  waiting: string[];
  /** display names of documents a queued or running job takes to score2 */
  processing: string[];
}

/** A queued or running pipeline job that takes this document to score2, after which the gate can see it. */
export function readiesDoc(j: Pick<JobInfo, "kind" | "plan">, slug: string): boolean {
  if (j.kind !== "run") return false;
  const p = j.plan as { to?: unknown; docs?: unknown } | undefined;
  if (p?.to !== "score2") return false;
  return !Array.isArray(p.docs) || p.docs.includes(slug);
}

export function notReadyParts(st: ExportStatus | undefined | null, jobs?: JobInfo[] | null, sources?: SourceInfo[] | null): NotReady {
  const fileOf = new Map((sources ?? []).map((s) => [s.slug, s.filename]));
  const out: NotReady = { waiting: [], processing: [] };
  for (const slug of notReadyOf(st)) {
    const name = fileOf.get(slug) ?? slug;
    ((jobs ?? []).some((j) => readiesDoc(j, slug)) ? out.processing : out.waiting).push(name);
  }
  return out;
}

export const notReadyCount = (p: NotReady): number => p.waiting.length + p.processing.length;

/** "a.pdf, b.pdf have not been through scoring and cleanup with this version yet." ("" when none) */
export function waitingWords(p: NotReady): string {
  const n = p.waiting.length;
  return n ? `${p.waiting.join(", ")} ${n === 1 ? "has" : "have"} not been through scoring and cleanup with this version yet.` : "";
}

/** "a.pdf is being processed. Export opens when the run has finished and its blocks are reviewed." ("" when none) */
export function processingWords(p: NotReady): string {
  const n = p.processing.length;
  return n ? `${p.processing.join(", ")} ${n === 1 ? "is" : "are"} being processed. Export opens when the run has finished and its blocks are reviewed.` : "";
}
