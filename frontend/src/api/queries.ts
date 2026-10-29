// All TanStack Query wrappers live here (design 08 section 1.2): one place for keys and fetchers.
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { client, unwrap } from "./client";
import type { ApplyTierOut, JobInfo, ProbeOut, Tier } from "./schema";

export const qk = {
  project: ["project"] as const,
  sources: ["sources"] as const,
  status: ["status"] as const,
  groups: ["groups"] as const,
  selection: ["selection"] as const,
  summary: ["summary"] as const,
  models: ["models"] as const,
  jobs: ["jobs", "active"] as const,
  blocks: ["block-index"] as const,
};

export const useProject = () =>
  useQuery({
    queryKey: qk.project,
    queryFn: async () => unwrap(await client.GET("/api/project")),
    staleTime: Infinity,
    refetchInterval: (q) => (q.state.error ? 3000 : false),
  });

export const useSources = () =>
  useQuery({ queryKey: qk.sources, queryFn: async () => unwrap(await client.GET("/api/sources")), staleTime: 0 });

export const useStatus = () =>
  useQuery({ queryKey: qk.status, queryFn: async () => unwrap(await client.GET("/api/status")), staleTime: 0 });

export const useGroups = () =>
  useQuery({
    queryKey: qk.groups,
    queryFn: async () => unwrap(await client.GET("/api/scope/groups", { params: { query: {} } })),
    staleTime: Infinity,
  });

export const useBlockIndexData = () =>
  useQuery({
    queryKey: qk.blocks,
    queryFn: async () => unwrap(await client.GET("/api/scope/blocks", { params: { query: {} } })),
    staleTime: Infinity,
  });

export const useSelectionQuery = () =>
  useQuery({
    queryKey: qk.selection,
    queryFn: async () => unwrap(await client.GET("/api/scope/selection")),
    staleTime: Infinity,
  });

export const useModels = () =>
  useQuery({
    queryKey: qk.models,
    queryFn: async () => unwrap(await client.GET("/api/scope/models")),
    staleTime: 30_000,
  });

export const useActiveJobs = () =>
  useQuery({
    queryKey: qk.jobs,
    queryFn: async () =>
      unwrap(await client.GET("/api/jobs", { params: { query: { status: ["queued", "running"] } } })),
    staleTime: 0,
    // Poll only while something is queued or running (design 1.2).
    refetchInterval: (q) => (q.state.data?.length ? 1000 : false),
  });

/** Make a freshly enqueued job visible at once so polling starts and its end is noticed. */
export function trackJob(qc: QueryClient, job: JobInfo): void {
  qc.setQueryData<JobInfo[]>(qk.jobs, (old) => [...(old ?? []).filter((j) => j.id !== job.id), job]);
  void qc.invalidateQueries({ queryKey: qk.jobs });
}

export function useUploadSources() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (files: File[]): Promise<JobInfo> => {
      const body = new FormData();
      for (const f of files) body.append("files", f);
      const res = await fetch("/api/sources", { method: "POST", body });
      if (!res.ok) throw new Error(`upload failed (${res.status})`);
      return (await res.json()) as JobInfo;
    },
    onSuccess: (job) => trackJob(qc, job),
  });
}

export function useRerun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await client.POST("/api/jobs", { body: { to: "group", allow_reparse: false } })),
    onSuccess: (job) => trackJob(qc, job),
  });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(await client.POST("/api/jobs/{job_id}/cancel", { params: { path: { job_id: id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.jobs }),
  });
}

export function useConfirmScope() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await client.POST("/api/scope/confirm", { body: {} })),
    onSuccess: (job) => trackJob(qc, job),
  });
}

export function useRunProbe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<ProbeOut> => unwrap(await client.POST("/api/probe")),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.models }),
  });
}

export function useApplyTier() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (tier: Tier): Promise<ApplyTierOut> =>
      unwrap(await client.POST("/api/config/apply-tier", { body: { tier, force: false, request_id: crypto.randomUUID() } })),
    onSuccess: (out) => {
      qc.setQueryData(qk.models, (old: unknown) => ({ ...(old as object), models: out.models }));
      void qc.invalidateQueries({ queryKey: qk.sources });
      void qc.invalidateQueries({ queryKey: qk.status });
    },
  });
}

/** Query keys refreshed whenever a background job finishes successfully (design 1.2). */
export function invalidateAfterJob(qc: QueryClient): void {
  for (const key of [qk.sources, qk.status, qk.groups, qk.selection, qk.summary, qk.blocks, qk.models])
    void qc.invalidateQueries({ queryKey: key });
}
