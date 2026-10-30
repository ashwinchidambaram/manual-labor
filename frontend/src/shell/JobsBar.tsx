import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, unwrap } from "../api/client";
import { trackJob, useCancelJob } from "../api/queries";
import type { JobInfo } from "../api/schema";
import { useJobsPolling } from "../hooks/useJobsPolling";

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
      setLog(rows.map((r) => (typeof r.message === "string" ? r.message : JSON.stringify(r))));
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
        <pre className="basis-full max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-raised p-2 font-mono text-2xs text-ink" data-testid="job-log">
          {log.length ? log.join("\n") : "The log is empty."}
        </pre>
      ) : null}
    </>
  );
}

const SCORING = new Set(["score", "clean", "score2"]);
const READING = new Set(["ingest", "parse", "figures", "group"]);

/**
 * A job in words (design 13 voice rules): what it is doing and what Cancel stops. The pipeline counts its work in
 * steps (one stage of one document each), so progress is "N of M steps"; an unknown kind keeps its own name.
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

/** "2 of 5 steps"; before the job has counted its work, "starting" (never "0/0"). */
export function jobProgress(done: number, total: number): string {
  return total > 0 ? `${done} of ${total} step${total === 1 ? "" : "s"}` : "starting";
}

/** Shows running jobs and failed ones; the polling and cache reconciliation live in useJobsPolling. */
export default function JobsBar() {
  const { jobs, failed, dismiss } = useJobsPolling();
  const cancel = useCancelJob();

  if (!jobs.length && !failed.length) return null;
  return (
    <div className="flex shrink-0 flex-col gap-1 border-b border-line bg-sunk px-4 py-2 text-sm wide:px-8" data-testid="jobs-bar" aria-label="Background jobs" role="region">
      {jobs.map((j) => {
        const w = jobWords(j);
        return (
          <div key={j.id} className="flex flex-wrap items-center gap-x-2.5 gap-y-1" data-testid="job-row">
            <span className="font-medium text-ink">{w.what}</span>
            <progress className="h-2 w-32 accent-[var(--act)]" max={1} value={j.progress} aria-label={`${w.what}: progress`} />
            <span className="tabular-nums text-xs text-muted">{jobProgress(j.units_done ?? 0, j.units_total ?? 0)}</span>
            {j.doc ? <span className="text-xs text-muted">now on {j.doc}</span> : null}
            <button type="button" className={BTN} onClick={() => cancel.mutate(j.id)}>
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
