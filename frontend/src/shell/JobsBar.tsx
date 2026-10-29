import { useCancelJob } from "../api/queries";
import { useJobsPolling } from "../hooks/useJobsPolling";

const BTN = "rounded border border-slate-400 px-2 py-0.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";

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
        <div key={j.id} role="alert" className="flex items-center gap-2 rounded bg-red-50 px-2 py-1 text-red-800" data-testid="job-failed">
          <span>
            Job {j.kind} {j.status}: {j.error ?? j.message ?? "no details"}
          </span>
          <button type="button" className={BTN} onClick={() => dismiss(j.id)}>
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
