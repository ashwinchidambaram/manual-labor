// Why the review totals moved (first-use report C/D, 2026-10-30): when a reading or scoring job finishes, the review
// estimate can change (107 -> 109 to check). The summary says so in one line, from the server's counts before and
// after the job: "2 more blocks queued after scoring finished (2 fewer cleared by the checks)".
import { useEffect, useRef, useState } from "react";
import { useActiveJobs } from "../api/queries";
import type { JobInfo, ReviewCounts } from "../api/schema";
import { isPipelineJob, isReadingJob } from "../shell/jobStep";

/** Counts after a job ended that still explain it; later moves are the reviewer's own (design 09 section 12). */
export const CHANGE_WINDOW_MS = 15_000;

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

/**
 * Blocks that need a person: in scope minus those the checks cleared. A reviewer's decision moves a block between
 * "queued" and "approved", "edited", "flagged" or "rejected", all inside this number, so it changes only when a job
 * re-scores or adds blocks.
 */
export const needsPerson = (c: ReviewCounts): number => c.in_scope - c.auto_approved;

/** The one-line reason, or null when the estimate did not move. `what` is "scoring" or "reading". */
export function reviewChangeNote(before: ReviewCounts, after: ReviewCounts, what: string): string | null {
  const d = needsPerson(after) - needsPerson(before);
  if (d === 0) return null;
  const head = d > 0 ? `${plural(d, "more block")} queued after ${what} finished` : `${plural(-d, "fewer block")} to review after ${what} finished`;
  const dScope = after.in_scope - before.in_scope;
  const dAuto = after.auto_approved - before.auto_approved;
  const why = [
    dScope > 0 ? `${dScope} more in scope` : dScope < 0 ? `${-dScope} fewer in scope` : "",
    dAuto < 0 ? `${-dAuto} fewer cleared by the checks` : dAuto > 0 ? `${dAuto} more cleared by the checks` : "",
  ].filter(Boolean);
  return `${head}${why.length ? ` (${why.join(", ")})` : ""}.`;
}

/**
 * The note for the Verify summary. While a pipeline job is active the latest server counts are remembered; when the
 * last one ends, counts that arrive within CHANGE_WINDOW_MS are compared with them. The note stays until the next
 * job starts.
 */
export function useReviewChangeNote(counts: ReviewCounts | null): string | null {
  const active = useActiveJobs();
  const jobs: JobInfo[] = (active.data ?? []).filter(isPipelineJob);
  const busy = jobs.length > 0;
  const what = jobs.some(isReadingJob) ? "reading" : "scoring";
  const during = useRef<{ counts: ReviewCounts; what: string } | null>(null);
  const [ended, setEnded] = useState<{ before: ReviewCounts; what: string; at: number } | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (busy) {
      if (counts) during.current = { counts, what };
      setEnded(null);
      setNote(null);
    } else if (during.current) {
      setEnded({ before: during.current.counts, what: during.current.what, at: Date.now() });
      during.current = null;
    }
  }, [busy, counts, what]);

  useEffect(() => {
    if (!ended || !counts || Date.now() - ended.at > CHANGE_WINDOW_MS) return;
    setNote(reviewChangeNote(ended.before, counts, ended.what));
  }, [ended, counts]);

  return note;
}
