import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, unwrap } from "../api/client";
import { trackJob, useCancelJob } from "../api/queries";
import type { JobInfo } from "../api/schema";
import { useJobsPolling } from "../hooks/useJobsPolling";

const BTN = "rounded border border-slate-400 px-2 py-0.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";

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
        <pre className="basis-full max-h-40 overflow-auto whitespace-pre-wrap rounded bg-white p-1 text-xs text-slate-800" data-testid="job-log">
          {log.length ? log.join("\n") : "The log is empty."}
        </pre>
      ) : null}
    </>
  );
}

/** Shows running jobs and failed ones; the polling and cache reconciliation live in useJobsPolling. */
export default function JobsBar() {
  const { jobs, failed, dismiss } = useJobsPolling();
  const cancel = useCancelJob();

  if (!jobs.length && !failed.length) return null;
  return (
    <div className="flex flex-col gap-1 text-sm" data-testid="jobs-bar" aria-label="Background jobs" role="region">
      {jobs.map((j) => (
        <div key={j.id} className="flex items-center gap-2" data-testid="job-row">
          <span className="font-medium">{j.kind}</span>
          <span className="text-slate-600">{[j.node, j.doc, j.message].filter(Boolean).join(" / ")}</span>
          <progress className="h-2 w-40" max={1} value={j.progress} aria-label={`${j.kind} progress`} />
          <span className="tabular-nums text-xs text-slate-600">
            {j.units_done}/{j.units_total}
          </span>
          <button type="button" className={BTN} onClick={() => cancel.mutate(j.id)}>
            Cancel
          </button>
        </div>
      ))}
      {failed.map((j) => (
        <div key={j.id} role="alert" className="flex flex-wrap items-center gap-2 rounded bg-red-50 px-2 py-1 text-red-800" data-testid="job-failed">
          <span>
            Job {j.kind} {j.status}: {j.error ?? j.message ?? "no details"}
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
