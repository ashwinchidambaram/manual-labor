import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { client, unwrap } from "../api/client";
import { trackJob, useCancelJob, useSources } from "../api/queries";
import type { JobInfo } from "../api/schema";
import { useJobsPolling } from "../hooks/useJobsPolling";
import { jobLogLines } from "./jobLog";
import { stepSentence, type FileOf } from "./jobStep";
import { usePublishedHeight } from "./publishHeight";

const BTN = "min-h-[1.75rem] rounded-md border border-line-strong bg-raised px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";

/** "What now" for a failed job (design 12 section 2.6): retry the same plan where that is safe, or read its log. */
function FailedHelp({ job, onRetried }: { job: JobInfo; onRetried: () => void }) {
  const qc = useQueryClient();
  const [log, setLog] = useState<string[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const plan = job.plan as { to?: unknown };
  const canRetry = (job.kind === "run" && typeof plan.to === "string") || job.kind === "export";
  const retry = async (): Promise<void> => {
    try {
      const next =
        job.kind === "export"
          ? unwrap(await client.POST("/api/export", { body: { request_id: crypto.randomUUID() } }))
          : unwrap(await client.POST("/api/jobs", { body: job.plan as { to: string; allow_reparse: boolean } }));
      trackJob(qc, next);
      onRetried();
    } catch (e) {
      setMsg(`Retry not started: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  const seeLog = async (): Promise<void> => {
    try {
      const rows = unwrap(await client.GET("/api/jobs/{job_id}/log", { params: { path: { job_id: job.id }, query: { limit: 20 } } }));
      setLog(jobLogLines(rows));
    } catch (e) {
      setMsg(`Log unavailable: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  return (
    <>
      <span className="text-xs">What now:</span>
      {canRetry ? (
        <button type="button" className={BTN} onClick={() => void retry()}>
          Retry
        </button>
      ) : null}
      <button type="button" className={BTN} onClick={() => void seeLog()} aria-expanded={log !== null}>
        See log
      </button>
      {msg ? <span className="text-xs">{msg}</span> : null}
      {log ? (
        <ol className="basis-full max-h-40 list-none overflow-auto rounded-lg bg-raised p-2 text-xs text-ink" data-testid="job-log">
          {log.length ? log.map((l, i) => <li key={i}>{l}</li>) : <li>The log is empty.</li>}
        </ol>
      ) : null}
    </>
  );
}

const SCORING = new Set(["score", "clean", "score2"]);
const READING = new Set(["ingest", "parse", "figures", "group"]);

/**
 * A job in words (design 13 voice rules): what it is doing and what Cancel stops. The pipeline counts its work in
 * steps (one stage of one document each); `stepSentence` names the current one. An unknown kind keeps its own name.
 */
export function jobWords(j: Pick<JobInfo, "kind" | "plan">): { what: string; cancel: string } {
  const to = typeof (j.plan as { to?: unknown } | undefined)?.to === "string" ? ((j.plan as { to: string }).to as string) : null;
  if (j.kind === "export" || (j.kind === "run" && (to === "assemble" || to === "export"))) return { what: "Building the export", cancel: "Cancel the export" };
  if (j.kind === "agent") return { what: "Agent pass on your flags", cancel: "Cancel the agent pass" };
  if (j.kind === "ingest_run") return { what: "Reading the new manuals", cancel: "Cancel reading" };
  if (j.kind === "run" && to && SCORING.has(to)) return { what: "Scoring your selection", cancel: "Cancel scoring" };
  if (j.kind === "run" && to && READING.has(to)) return { what: "Reading your manuals", cancel: "Cancel reading" };
  return { what: j.kind.replace(/_/g, " "), cancel: "Cancel" };
}

/** A slug -> file name lookup over the Sources list (the slug while that list is loading). */
export function useFileOf(): FileOf {
  const sources = useSources();
  const names = new Map((sources.data ?? []).map((s) => [s.slug, s.filename] as const));
  return (slug) => names.get(slug) ?? slug;
}

/**
 * Shows running jobs and failed ones; the polling and cache reconciliation live in useJobsPolling. Sticky at the top
 * of the screen column while a job runs, so the step stays in view while the reader scrolls (first-use report D).
 * The bar's value is the server's `progress` (finished steps plus the step's own count); a step that reports no count
 * says "working, no estimate" and the bar stands still (design 13 section 2.5.6).
 *
 * On a short window (200 percent zoom) each job is one line that never wraps: the step sentence is cut to fit (whole in
 * its title) and, when also narrow, the job's name is left to the progress bar's label. The bar's height is published
 * as `--jobs-bar`; Verify's page strip gives that much of its height back (design 13 section 8.3).
 */
export default function JobsBar() {
  const { jobs, failed, dismiss } = useJobsPolling();
  if (!jobs.length && !failed.length) return null;
  return <Bar jobs={jobs} failed={failed} dismiss={dismiss} />;
}

function Bar({ jobs, failed, dismiss }: ReturnType<typeof useJobsPolling>) {
  const cancel = useCancelJob();
  const fileOf = useFileOf();
  const ref = useRef<HTMLDivElement>(null);
  // published while shown, so sticky and capped content below the bar can make room (design 13 section 8.3)
  usePublishedHeight(ref, "--jobs-bar");
  return (
    <div
      ref={ref}
      className="sticky top-0 z-20 flex shrink-0 flex-col gap-1 border-b border-line bg-sunk px-4 py-2 text-sm short:py-1 wide:px-8"
      data-testid="jobs-bar"
      aria-label="Background jobs"
      role="region"
    >
      {jobs.map((j) => {
        const w = jobWords(j);
        const step = stepSentence(j, fileOf);
        const running = j.status === "running" && (j.units_total ?? 0) > 0;
        return (
          <div key={j.id} className="flex flex-wrap items-center gap-x-2.5 gap-y-1 short:flex-nowrap" data-testid="job-row" data-status={j.status}>
            <span className="shrink-0 font-medium text-ink short-narrow:hidden">{w.what}</span>
            <progress className="h-2 w-32 shrink-0 accent-[var(--act)] short:w-20" max={1} value={j.progress} aria-label={`${w.what}: progress`} />
            <span className="min-w-0 text-xs tabular-nums text-ink short:flex-1 short:truncate" data-testid="job-step" title={step.text}>
              {step.text}
            </span>
            {running && !step.estimate ? (
              <span className="shrink-0 text-xs text-muted short:whitespace-nowrap" data-testid="job-no-estimate">
                working, no estimate
              </span>
            ) : null}
            <button type="button" className={`${BTN} shrink-0 short:min-h-[1.5rem] short:whitespace-nowrap`} onClick={() => cancel.mutate(j.id)}>
              {w.cancel}
            </button>
          </div>
        );
      })}
      {failed.map((j) => (
        <div key={j.id} role="alert" className="flex flex-wrap items-center gap-2 rounded-lg bg-fail-wash px-3 py-1.5 text-ink" data-testid="job-failed">
          <span>
            {jobWords(j).what} {j.status}: {j.error ?? j.message ?? "no details were reported"}
          </span>
          <FailedHelp job={j} onRetried={() => dismiss(j.id)} />
          <button type="button" className={BTN} onClick={() => dismiss(j.id)}>
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
