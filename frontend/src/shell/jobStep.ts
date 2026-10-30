// A running job's step in plain words (design 13 section 2.5.6): which step of how many, what it is doing, on which
// manual, and how far it is when the worker counts it (pages, blocks, topics: design 07 section 4.1). Nothing here
// estimates: a step without a count says "working, no estimate", and nothing moves that the server did not move.
import type { JobInfo } from "../api/schema";

type Job = Pick<JobInfo, "kind" | "plan" | "status" | "units_done" | "units_total" | "node" | "doc"> &
  Partial<Pick<JobInfo, "step_done" | "step_total" | "step_unit" | "files">>;

/** A file name for a document slug (the Sources list), or the slug itself. */
export type FileOf = (slug: string) => string;

/** What a stage does to one manual; `{f}` is the file name. Project steps have no file. */
const STEP: Record<string, string> = {
  ingest: "Adding {f}",
  parse: "Reading {f}",
  figures: "Finding figures in {f}",
  score: "Scoring {f}",
  group: "Grouping {f} into topics",
  clean: "Cleaning up the text of {f}",
  score2: "Scoring the cleaned text of {f}",
  assemble: "Assembling the articles",
  export: "Building the export",
};

/** What a stage is doing to a manual, without the file (first-use report E: "Processing clean" read as a verdict). */
export const STAGE_WORDS: Readonly<Record<string, string>> = {
  ingest: "Adding the file",
  parse: "Reading",
  figures: "Finding figures",
  score: "Scoring",
  group: "Grouping into topics",
  clean: "Cleaning up text",
  score2: "Scoring the cleaned text",
};

const UNIT: Record<string, [string, string]> = { block: ["block", "blocks"], topic: ["topic", "topics"], page: ["page", "pages"] };

/** Jobs that read or score manuals (they change what Verify and Export can show); not export or agent jobs. */
export function isPipelineJob(j: Pick<JobInfo, "kind" | "plan">): boolean {
  if (j.kind === "ingest_run") return true;
  if (j.kind !== "run") return false;
  const to = (j.plan as { to?: unknown } | undefined)?.to;
  return typeof to === "string" && to !== "assemble" && to !== "export";
}

/** True when the job belongs to the reading half (it stops at topics), for "reading finished" vs "scoring finished". */
export function isReadingJob(j: Pick<JobInfo, "kind" | "plan">): boolean {
  const to = (j.plan as { to?: unknown } | undefined)?.to;
  return j.kind === "ingest_run" || (j.kind === "run" && (to === "parse" || to === "figures" || to === "group"));
}

/** "Step 3 of 4", or null before the job has counted its steps. */
export function stepPosition(j: Job): string | null {
  const total = j.units_total ?? 0;
  if (j.status !== "running" || total <= 0) return null;
  return `Step ${Math.min(total, (j.units_done ?? 0) + 1)} of ${total}`;
}

/** The inner count: "page 4 of 6", "40 of 87 blocks"; null when the step reports none. */
export function stepCount(j: Job): string | null {
  const done = j.step_done;
  const total = j.step_total;
  const unit = j.step_unit;
  if (done == null || total == null || !unit || total <= 0) return null;
  if (unit === "page") return `page ${done} of ${total}`;
  const [one, many] = UNIT[unit] ?? [unit, unit];
  return `${done} of ${total} ${total === 1 ? one : many}`;
}

/** What the job is doing now, with the manual's file name: "Finding figures in x200.pdf". */
export function stepDoing(j: Job, fileOf: FileOf): string | null {
  const files = j.files ?? [];
  if (j.status === "queued") return files.length ? `Waiting to start: ${files.join(", ")}` : "Waiting for the job before it to finish";
  if (j.node && j.doc !== null && j.doc !== undefined && (j.units_total ?? 0) > 0) {
    const tpl = STEP[j.node] ?? `${j.node.replace(/_/g, " ")} {f}`;
    return tpl.replace("{f}", j.doc ? fileOf(j.doc) : "").trim();
  }
  if (files.length) return `Adding ${files.join(", ")}`;
  return null;
}

/** The whole sentence for a running step: "Step 3 of 4: Finding figures in x200.pdf, page 4 of 6". */
export function stepSentence(j: Job, fileOf: FileOf): { text: string; estimate: boolean } {
  const pos = stepPosition(j);
  const doing = stepDoing(j, fileOf);
  const count = j.status === "running" ? stepCount(j) : null;
  const head = [pos, doing].filter(Boolean).join(": ");
  if (!head) return { text: "Starting", estimate: false };
  return { text: count ? `${head}, ${count}` : head, estimate: count !== null };
}
