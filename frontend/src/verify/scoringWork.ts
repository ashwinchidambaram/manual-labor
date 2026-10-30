// What Verify says about scoring that is still going on (first-use report C9, design 09 section 12): read from the
// active jobs (server truth), never from an empty list. Only a job that is queued or running counts as work.
import type { JobInfo } from "../api/schema";
import { isPipelineJob, isReadingJob, stepCount, stepDoing, type FileOf } from "../shell/jobStep";

/** The pipeline job Verify reports on: the running one, else the first queued one; null when none. */
export function scoringJob(jobs: readonly JobInfo[]): JobInfo | null {
  const mine = jobs.filter((j) => isPipelineJob(j) && (j.status === "running" || j.status === "queued"));
  return mine.find((j) => j.status === "running") ?? mine[0] ?? null;
}

/**
 * Is a queued or running pipeline job going to prepare document `slug`? A job without a `docs` list covers every
 * document (an upload, a confirm); one with a list covers those only.
 */
export function beingScored(jobs: readonly JobInfo[]): (slug: string) => boolean {
  const mine = jobs.filter((j) => isPipelineJob(j) && (j.status === "running" || j.status === "queued"));
  const all = mine.some((j) => !Array.isArray((j.plan as { docs?: unknown }).docs));
  const some = new Set(mine.flatMap((j) => ((j.plan as { docs?: unknown }).docs as string[] | undefined) ?? []));
  return (slug) => all || some.has(slug);
}

/**
 * "Scoring in progress, 40 of 87 blocks scored in pump.pdf", or the step it is on, with its count or "no estimate". A job
 * that only reads manuals (an upload) is "Reading in progress": it puts no block in the list.
 */
export function scoringWords(j: JobInfo, fileOf: FileOf): string {
  const head = isReadingJob(j) ? "Reading in progress" : "Scoring in progress";
  if (j.status !== "running") return `${head}, waiting to start`;
  const total = j.units_total ?? 0;
  if (total <= 0) {
    const doing = stepDoing(j, fileOf);
    return doing ? `${head}, ${doing[0].toLowerCase()}${doing.slice(1)}` : `${head}, starting`;
  }
  const isScore = j.node === "score" || j.node === "score2";
  if (isScore && j.step_unit === "block" && j.step_done != null && j.step_total != null && j.doc)
    return `${head}, ${j.step_done} of ${j.step_total} blocks scored in ${fileOf(j.doc)}`;
  const pos = `step ${Math.min(total, (j.units_done ?? 0) + 1)} of ${total}`;
  const doing = stepDoing(j, fileOf);
  const count = stepCount(j);
  return `${head}, ${pos}${doing ? `: ${doing}` : ""}${count ? `, ${count}` : " (working, no estimate)"}`;
}
