import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { ApiError, client, unwrap } from "../api/client";
import { SOURCES_CHANGED, invalidateAfterJob, useActiveJobs } from "../api/queries";
import type { JobInfo } from "../api/schema";

export interface JobsPolling {
  jobs: JobInfo[];
  /** jobs that ended failed, interrupted or cancelled, until dismissed */
  failed: JobInfo[];
  dismiss: (id: string) => void;
}

/**
 * Polls only while a job runs (useActiveJobs.refetchInterval). When a job leaves the active list its record is
 * read once and the caches are reconciled (invalidateAfterJob plus `extra`) whatever its outcome: a failed job
 * changed things too (a manual it added, a stage it marked failed), and a screen must not stay stale under its
 * banner (design 07 section 20). Anything but `done` is reported in `failed`. When the manuals change (one was
 * removed), each failed job is read again and one whose row is gone (it was about that manual only) is dropped.
 */
export function useJobsPolling(extra: readonly QueryKey[] = []): JobsPolling {
  const qc = useQueryClient();
  const { data } = useActiveJobs();
  // a merged row is shown by the job it was folded into (design 07 section 18)
  const jobs = (data ?? []).filter((j) => j.status !== "merged");
  const prev = useRef<Map<string, JobInfo>>(new Map());
  const extraRef = useRef(extra);
  extraRef.current = extra;
  const [failed, setFailed] = useState<JobInfo[]>([]);

  useEffect(() => {
    const now = new Map((data ?? []).map((j) => [j.id, j]));
    const gone = [...prev.current.keys()].filter((id) => !now.has(id));
    prev.current = now;
    for (const id of gone) {
      void (async () => {
        try {
          const j = unwrap(await client.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }));
          if (j.status === "done" || j.status === "failed" || j.status === "interrupted" || j.status === "cancelled")
            invalidateAfterJob(qc, extraRef.current);
          if (j.status === "failed" || j.status === "interrupted" || j.status === "cancelled")
            setFailed((f) => [...f.filter((x) => x.id !== j.id), j]);
        } catch {
          /* job record unreadable: nothing to reconcile */
        }
      })();
    }
  }, [data, qc]);

  const failedRef = useRef<JobInfo[]>(failed);
  failedRef.current = failed;
  useEffect(() => {
    const recheck = (): void => {
      for (const j of failedRef.current)
        void (async () => {
          try {
            unwrap(await client.GET("/api/jobs/{job_id}", { params: { path: { job_id: j.id } } }));
          } catch (e) {
            if (e instanceof ApiError && e.status === 404) setFailed((f) => f.filter((x) => x.id !== j.id));
          }
        })();
    };
    window.addEventListener(SOURCES_CHANGED, recheck);
    return () => window.removeEventListener(SOURCES_CHANGED, recheck);
  }, []);

  return { jobs, failed, dismiss: (id) => setFailed((f) => f.filter((x) => x.id !== id)) };
}

/** One job's record, polled every second while it is queued, running or merged into a job that is (it then ends with it). */
export function useJobWatch(id: string | null) {
  return useQuery({
    queryKey: ["jobs", "watch", id] as const,
    enabled: id !== null,
    queryFn: async () => unwrap(await client.GET("/api/jobs/{job_id}", { params: { path: { job_id: id! } } })),
    staleTime: 0,
    refetchInterval: (q) => (q.state.data && !["queued", "running", "merged"].includes(q.state.data.status) ? false : 1000),
  });
}
