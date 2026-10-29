import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { client, unwrap } from "../api/client";
import { invalidateAfterJob, useActiveJobs, useCancelJob } from "../api/queries";
import type { JobInfo } from "../api/schema";

const BTN = "rounded border border-slate-400 px-2 py-0.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";

/** Polls only while a job runs (useActiveJobs.refetchInterval); reconciles caches when jobs end. */
export default function JobsBar() {
  const qc = useQueryClient();
  const { data: jobs = [] } = useActiveJobs();
  const cancel = useCancelJob();
  const prev = useRef<Map<string, JobInfo>>(new Map());
  const [failed, setFailed] = useState<JobInfo[]>([]);

  useEffect(() => {
    const now = new Map(jobs.map((j) => [j.id, j]));
    const gone = [...prev.current.keys()].filter((id) => !now.has(id));
    prev.current = now;
    for (const id of gone) {
      void (async () => {
        try {
          const j = unwrap(await client.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }));
          if (j.status === "done") invalidateAfterJob(qc);
          else if (j.status === "failed" || j.status === "interrupted" || j.status === "cancelled")
            setFailed((f) => [...f.filter((x) => x.id !== j.id), j]);
        } catch {
          /* job record unreadable: nothing to reconcile */
        }
      })();
    }
  }, [jobs, qc]);

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
        <div key={j.id} role="alert" className="flex items-center gap-2 rounded bg-red-50 px-2 py-1 text-red-800" data-testid="job-failed">
          <span>
            Job {j.kind} {j.status}: {j.error ?? j.message ?? "no details"}
          </span>
          <button type="button" className={BTN} onClick={() => setFailed((f) => f.filter((x) => x.id !== j.id))}>
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
