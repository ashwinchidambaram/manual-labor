// Server-owned selection with an optimistic overlay in the Query cache (design 08 sections 3.2, 3.3).
// apply(): reducer -> setQueryData (same frame) -> 150 ms debounced, strictly ordered PUTs -> server wins.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { client, unwrap } from "../api/client";
import { qk, useBlockIndexData, useGroups, useSelectionQuery } from "../api/queries";
import type { DocGroups, ScopeSummary, SelectionOp, SelectionOut } from "../api/schema";
import { buildBlockIndex, buildGroupsIndex, summaryFrom } from "../scope/derive";
import { reduce } from "../scope/selectionReducer";

export const DEBOUNCE_MS = 150;
export type OpInput = Partial<Omit<SelectionOp, "request_id" | "op">> & Pick<SelectionOp, "op">;

export interface SelectionEngine {
  data: SelectionOut | undefined;
  docs: DocGroups[];
  ids: ReadonlySet<string>;
  /** operations not yet confirmed by the server (coverage chips are stale while > 0) */
  pending: number;
  apply: (...ops: OpInput[]) => void;
  /** resolve once every queued op has been acknowledged by the server */
  settle: () => Promise<void>;
  error: string | null;
  clearError: () => void;
  isLoading: boolean;
  groupsError: Error | null;
  selectionError: Error | null;
  retry: () => void;
}

export function useSelectionEngine(): SelectionEngine {
  const qc = useQueryClient();
  const groupsQ = useGroups();
  const blocksQ = useBlockIndexData();
  const selQ = useSelectionQuery();
  const docs = useMemo(() => groupsQ.data ?? [], [groupsQ.data]);
  const groupsIdx = useMemo(() => buildGroupsIndex(docs), [docs]);
  const blockIdx = useMemo(() => (blocksQ.data ? buildBlockIndex(blocksQ.data) : undefined), [blocksQ.data]);
  const live = useRef({ docs, groupsIdx, blockIdx });
  live.current = { docs, groupsIdx, blockIdx };

  const queue = useRef<SelectionOp[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflight = useRef(false);
  const inflightP = useRef<Promise<void> | null>(null);
  const serverOut = useRef<SelectionOut | undefined>(undefined);
  const pendingRef = useRef(0);
  const [pending, setPendingState] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const setPending = (n: number): void => {
    pendingRef.current = n;
    setPendingState(n);
  };

  useEffect(() => {
    if (selQ.data && pendingRef.current === 0) serverOut.current = selQ.data;
  }, [selQ.data]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const run = useCallback(async () => {
    let last: SelectionOut | undefined;
    try {
      while (queue.current.length) {
        const op = queue.current.shift()!;
        last = unwrap(await client.PUT("/api/scope/selection", { body: op }));
        serverOut.current = last;
        setPending(Math.max(0, pendingRef.current - 1));
      }
      if (last && pendingRef.current === 0) qc.setQueryData(qk.selection, last);
    } catch (e) {
      queue.current = [];
      setPending(0);
      if (serverOut.current) qc.setQueryData(qk.selection, serverOut.current);
      setError(`Selection not saved: ${e instanceof Error ? e.message : String(e)}`);
      void qc.invalidateQueries({ queryKey: qk.selection });
    } finally {
      inflight.current = false;
      inflightP.current = null;
    }
  }, [qc]);

  const flush = useCallback((): Promise<void> => {
    if (inflightP.current) return inflightP.current;
    if (!queue.current.length) return Promise.resolve();
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    inflight.current = true;
    inflightP.current = run();
    return inflightP.current;
  }, [run]);

  const settle = useCallback(async () => {
    while (queue.current.length || inflightP.current) await flush();
  }, [flush]);

  const apply = useCallback(
    (...inputs: OpInput[]) => {
      const cur = qc.getQueryData<SelectionOut>(qk.selection);
      if (!cur) return;
      let out = cur;
      for (const input of inputs) {
        const op: SelectionOp = { block_ids: [], subtree: false, ...input, request_id: crypto.randomUUID() };
        const { groupsIdx: gi, blockIdx: bi, docs: ds } = live.current;
        const state = {
          ids: new Set(out.selection.block_ids) as ReadonlySet<string>,
          split: out.selection.article_split,
          view: out.selection.active_view,
        };
        const next = reduce(state, op, gi);
        const ids = next.ids === state.ids ? out.selection.block_ids : [...next.ids];
        let summary: ScopeSummary = out.summary;
        if (bi) summary = summaryFrom(next.ids, bi, ds, out.summary.review_load.threshold, next.split);
        else
          summary = {
            ...summary,
            articles: next.split === "per_topic" ? summary.articles_per_topic : summary.articles_per_document,
          };
        out = {
          ...out,
          selection: { block_ids: ids, article_split: next.split, active_view: next.view },
          summary,
        };
        queue.current.push(op);
        setPending(pendingRef.current + 1);
      }
      qc.setQueryData(qk.selection, out);
      if (!inflight.current && !timer.current) timer.current = setTimeout(() => void flush(), DEBOUNCE_MS);
    },
    [qc, flush],
  );

  const ids = useMemo(() => new Set(selQ.data?.selection.block_ids ?? []), [selQ.data?.selection.block_ids]);
  const retry = useCallback(() => {
    void groupsQ.refetch();
    void selQ.refetch();
    void blocksQ.refetch();
  }, [groupsQ, selQ, blocksQ]);

  return {
    data: selQ.data,
    docs,
    ids,
    pending,
    apply,
    settle,
    error,
    clearError: () => setError(null),
    isLoading: groupsQ.isLoading || selQ.isLoading,
    groupsError: groupsQ.error,
    selectionError: selQ.error,
    retry,
  };
}
