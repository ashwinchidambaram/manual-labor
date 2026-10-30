// Server-owned selection with an optimistic overlay in the Query cache (design 08 sections 3.2, 3.3).
// apply(): reducer -> setQueryData (same frame) -> 150 ms debounced, strictly ordered PUTs -> server wins.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { client, unwrap } from "../api/client";
import { bumpSelectionVersion, selSync } from "../api/selectionSync";
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
  /** resolve once every queued op has been acknowledged by the server; false when a save failed */
  settle: () => Promise<boolean>;
  error: string | null;
  clearError: () => void;
  isLoading: boolean;
  groupsError: Error | null;
  selectionError: Error | null;
  /** the block index (live counts) failed to load */
  blocksError: Error | null;
  retryBlocks: () => void;
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
  const failed = useRef(false);
  const unloadSent = useRef(false);
  const setPending = (n: number): void => {
    pendingRef.current = n;
    selSync.pending = n;
    setPendingState(n);
  };

  useEffect(() => {
    if (selQ.data && pendingRef.current === 0) serverOut.current = selQ.data;
  }, [selQ.data]);

  // A click made before the block index loaded could only carry the server's old counts in its
  // optimistic summary. Recount once the index is here, so the counts go live without waiting for
  // the server's answer (which may be slow, or held).
  useEffect(() => {
    if (!blockIdx || pendingRef.current === 0) return;
    const cur = qc.getQueryData<SelectionOut>(qk.selection);
    if (!cur) return;
    const ids = new Set(cur.selection.block_ids) as ReadonlySet<string>;
    qc.setQueryData(qk.selection, {
      ...cur,
      summary: summaryFrom(ids, blockIdx, live.current.docs, cur.summary.review_load.threshold, cur.selection.article_split),
    });
  }, [blockIdx, qc]);

  const run = useCallback(async () => {
    let last: SelectionOut | undefined;
    try {
      while (queue.current.length) {
        const op = queue.current.shift()!;
        last = unwrap(await client.PUT("/api/scope/selection", { body: op }));
        serverOut.current = last;
        bumpSelectionVersion();
        setPending(Math.max(0, pendingRef.current - 1));
      }
      if (last && pendingRef.current === 0) qc.setQueryData(qk.selection, last);
    } catch (e) {
      queue.current = [];
      failed.current = true;
      setPending(0);
      bumpSelectionVersion();
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
    failed.current = false;
    while (queue.current.length || inflightP.current) await flush();
    return !failed.current;
  }, [flush]);

  // Leaving the screen must not drop edits still inside the debounce window.
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
      void flush();
    },
    [flush],
  );

  // Page unload: the queue cannot be awaited, so send the net difference as independent (commutative)
  // keepalive PUTs: select, deselect, view and split touch disjoint state.
  useEffect(() => {
    const send = (): void => {
      if (unloadSent.current || (!queue.current.length && !inflightP.current)) return;
      unloadSent.current = true;
      const cur = qc.getQueryData<SelectionOut>(qk.selection);
      const base = serverOut.current;
      let ops: SelectionOp[];
      if (cur && base) {
        const had = new Set(base.selection.block_ids);
        const has = new Set(cur.selection.block_ids);
        const mk = (o: Partial<SelectionOp> & Pick<SelectionOp, "op">): SelectionOp => ({ block_ids: [], subtree: false, ...o, request_id: crypto.randomUUID() });
        ops = [];
        const add = [...has].filter((i) => !had.has(i));
        const rem = [...had].filter((i) => !has.has(i));
        if (add.length) ops.push(mk({ op: "select", block_ids: add }));
        if (rem.length) ops.push(mk({ op: "deselect", block_ids: rem }));
        if (cur.selection.active_view !== base.selection.active_view) ops.push(mk({ op: "set_view", view: cur.selection.active_view }));
        if (cur.selection.article_split !== base.selection.article_split) ops.push(mk({ op: "set_split", split: cur.selection.article_split }));
      } else ops = [...queue.current];
      for (const op of ops)
        void fetch("/api/scope/selection", {
          method: "PUT",
          keepalive: true,
          headers: { "content-type": "application/json" },
          body: JSON.stringify(op),
        }).catch(() => undefined);
    };
    const back = (): void => {
      unloadSent.current = false;
    };
    window.addEventListener("pagehide", send);
    window.addEventListener("beforeunload", send);
    window.addEventListener("pageshow", back);
    return () => {
      window.removeEventListener("pagehide", send);
      window.removeEventListener("beforeunload", send);
      window.removeEventListener("pageshow", back);
    };
  }, [qc]);


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
          selection: { ...out.selection, block_ids: ids, article_split: next.split, active_view: next.view },
          summary,
        };
        queue.current.push(op);
        setPending(pendingRef.current + 1);
      }
      bumpSelectionVersion();
      void qc.cancelQueries({ queryKey: qk.selection });
      qc.setQueryData(qk.selection, out);
      if (!inflight.current && !timer.current) timer.current = setTimeout(() => void flush(), DEBOUNCE_MS);
    },
    [qc, flush],
  );

  const ids = useMemo(() => new Set(selQ.data?.selection.block_ids ?? []), [selQ.data?.selection.block_ids]);
  const clearError = useCallback(() => setError(null), []);
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
    clearError,
    isLoading: groupsQ.isLoading || selQ.isLoading,
    groupsError: groupsQ.error,
    selectionError: selQ.error,
    blocksError: blocksQ.error,
    retryBlocks: () => void blocksQ.refetch(),
    retry,
  };
}
