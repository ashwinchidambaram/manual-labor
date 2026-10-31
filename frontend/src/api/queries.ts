// All TanStack Query wrappers live here (design 08 section 1.2): one place for keys and fetchers.
import { useMutation, useQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { client, unwrap } from "./client";
import { selSync } from "./selectionSync";
import type { ApplyTierOut, JobInfo, ProbeOut, SelectionOut, Tier } from "./schema";

export const qk = {
  project: ["project"] as const,
  sources: ["sources"] as const,
  status: ["status"] as const,
  groups: ["groups"] as const,
  selection: ["selection"] as const,
  models: ["models"] as const,
  jobs: ["jobs", "active"] as const,
  blocks: ["block-index"] as const,
  exportStatus: ["export", "status"] as const,
  flags: ["flags", "open"] as const,
  agentItems: ["agent", "items"] as const,
  proposals: ["agent", "proposals"] as const,
  calibration: ["calibration"] as const,
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
    queryFn: async ({ client: qc }) => {
      const version = selSync.version;
      const dirty = selSync.pending > 0;
      const data = unwrap(await client.GET("/api/scope/selection"));
      // A local edit happened (or is unconfirmed) since this request began: the answer is older than the cache.
      if (dirty || selSync.pending > 0 || selSync.version !== version) return qc.getQueryData<SelectionOut>(qk.selection) ?? data;
      return data;
    },
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

/**
 * Make a freshly enqueued job visible at once so polling starts and its end is noticed. A job the server folded into
 * an identical queued one (`merged`, design 07 section 18) is not a bar of its own: the job doing the work is tracked
 * instead (a stand-in until the refetch lists it), so its end is noticed even if it finishes before that refetch.
 */
export function trackJob(qc: QueryClient, job: JobInfo): void {
  const shown: JobInfo | null =
    job.status !== "merged" ? job : job.merged_into ? { ...job, id: job.merged_into, status: "queued", merged_into: null } : null;
  if (shown)
    qc.setQueryData<JobInfo[]>(qk.jobs, (old) =>
      job.status === "merged" && (old ?? []).some((j) => j.id === shown.id) ? old ?? [] : [...(old ?? []).filter((j) => j.id !== shown.id), shown],
    );
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

/** Query-key prefixes of later screens (Verify) that a finished job makes stale. */
export const JOB_INVALIDATION_PREFIXES: readonly (readonly string[])[] = [
  ["verify"],
  ["rail"],
  ["docFigures"],
  ["pageBlocks"],
  ["export"],
  ["flags"],
  ["agent"],
  ["calibration"],
];

/** Query keys refreshed whenever a background job finishes successfully (design 1.2); `extra` adds more. */
export function invalidateAfterJob(qc: QueryClient, extra: readonly QueryKey[] = []): void {
  const keys: readonly QueryKey[] = [
    qk.sources,
    qk.status,
    qk.groups,
    qk.selection,
    qk.blocks,
    qk.models,
    ...JOB_INVALIDATION_PREFIXES,
    ...extra,
  ];
  for (const key of keys) void qc.invalidateQueries({ queryKey: key });
}

// Export, Agent and the step indicator (module 12). Read-mostly: every number shown comes from these answers.
export const useExportStatus = (enabled = true) =>
  useQuery({
    queryKey: qk.exportStatus,
    queryFn: async () => unwrap(await client.GET("/api/export/status")),
    staleTime: 0,
    enabled,
  });

export const useOpenFlags = () =>
  useQuery({
    queryKey: qk.flags,
    queryFn: async () => unwrap(await client.GET("/api/flags", { params: { query: { status: "open" } } })),
    staleTime: 0,
  });

export const useAgentItems = () =>
  useQuery({
    queryKey: qk.agentItems,
    queryFn: async () => unwrap(await client.GET("/api/agent/items")),
    staleTime: 0,
    retry: false,
  });

export const useProposals = () =>
  useQuery({
    queryKey: qk.proposals,
    queryFn: async () => unwrap(await client.GET("/api/agent/proposals", { params: { query: { status: "pending" } } })),
    staleTime: 0,
    retry: false,
  });

export const useCalibration = () =>
  useQuery({
    queryKey: qk.calibration,
    queryFn: async () => unwrap(await client.GET("/api/calibration", { params: { query: {} } })),
    staleTime: 0,
    retry: false,
  });

/** After a review-changing write elsewhere (agent decision, override), refresh every count that depends on it. */
export function invalidateReviewCounts(qc: QueryClient): void {
  for (const key of [["export"], ["flags"], ["agent"], ["calibration"], ["verify"]]) void qc.invalidateQueries({ queryKey: key });
}
