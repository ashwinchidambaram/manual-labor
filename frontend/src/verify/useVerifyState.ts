// Verify data flow (design 09 section 3): queue + optimistic reducer + serial writes + cursor persistence.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, client, unwrap } from "../api/client";
import { useProject } from "../api/queries";
import type { BlockDetail, EditConflict, FlagCategory, PageBlock, QueueItem, QueuePage, QueueSort, ReviewActionOut } from "../api/schema";
import { useToast } from "../shell/Toast";
import { cmpItems, initialState, queueReducer, type ActKind, type QueueEvent, type QueueState } from "./queueReducer";
import { cardExcerpt, weakestFromDetail } from "./labels";
import { stepView as stepViewBy } from "./sliderCopy";
import { CancelledError, useVerifyWrites } from "./useVerifyWrites";

export const PAGE_LIMIT = 500;
const SORTS: QueueSort[] = ["worst_first", "by_page", "figures_only"];

export interface Controls {
  sort: QueueSort;
  view: number | null;
}
type Applied = Controls | null;

export const blockKey = (id: string | null) => ["verify", "block", id] as const;
export const pageBlocksKey = (slug: string, page: number) => ["pageBlocks", slug, page] as const;

export const fetchBlock = async (id: string): Promise<BlockDetail> =>
  unwrap(await client.GET("/api/verify/blocks/{block_id}", { params: { path: { block_id: id } } }));

/**
 * A queue item for a block outside the loaded list (the pinned card), built by the server's own card rules (shared
 * helper `cardExcerpt`), so the card reads the same when the block comes back in the list. The section title is not
 * in the detail: it is kept from the item when this block was seen in the list before.
 */
export function itemFromDetail(d: BlockDetail, known?: QueueItem | null): QueueItem {
  const b = d.block;
  const caption = b.figure_id ? ((d.figures ?? []).find((f) => f.figure_id === b.figure_id)?.record.caption_original ?? null) : null;
  const ocrMin = d.why?.find((w) => w.kind === "signal" && w.name === "ocr_min");
  return {
    block_id: b.id,
    doc_id: b.doc_id,
    page: b.page,
    type: b.type,
    confidence: b.confidence ?? null,
    status: b.status,
    has_numeric_spec: b.has_numeric_spec,
    reasons: d.why?.filter((w) => w.kind === "stale" || (w.kind === "signal" && (w.value ?? 1) < 1)).map((w) => w.name).slice(0, 3) ?? [],
    stale_doc: false,
    excerpt: cardExcerpt(b, caption),
    section_title: known?.section_title ?? null,
    weakest_word: known?.weakest_word ?? weakestFromDetail(ocrMin?.detail) ?? null,
  };
}

export interface ActOpts {
  text?: string;
  confirm?: boolean;
  flag?: { category: FlagCategory; note: string | null; target_id?: string | null };
  /** act only if this is still the current block (an await happened between the decision and the act) */
  expectId?: string | null;
  /** resolves the flag's target inside the queued write (a figure flag before the block's detail arrived). The queue
   * has already moved on, so no key can land on the flagged block; if it rejects, the flag is not sent. */
  flagTarget?: () => Promise<string | null>;
}

/** The flag's target could not be resolved: the flag was not sent. */
export class FlagTargetError extends Error {
  constructor(
    readonly blockId: string,
    readonly cause: unknown,
  ) {
    super(`could not load the figure of ${blockId}`);
    this.name = "FlagTargetError";
  }
}
export type ActResult = { ok: true; out: ReviewActionOut } | { ok: false; error: unknown; conflict?: EditConflict };

export function useVerifyState() {
  const qc = useQueryClient();
  const toast = useToast();
  const writes = useVerifyWrites();
  const project = useProject();
  // null until the project has loaded: scores are shown bare until then, never against a guessed threshold
  const T: number | null = project.data?.config.threshold ?? null;

  // the reducer runs synchronously so two fast key presses see each other's effects
  const ref = useRef<QueueState>(initialState);
  const [state, setState] = useState<QueueState>(initialState);
  const dispatch = useCallback((e: QueueEvent) => {
    ref.current = queueReducer(ref.current, e);
    setState(ref.current);
  }, []);

  const controlsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [controls, setControls] = useState<Controls>({ sort: "worst_first", view: null });
  const controlsRef = useRef(controls);
  controlsRef.current = controls;
  const [applied, setApplied] = useState<Applied>(null);
  const [firstLoad, setFirstLoad] = useState(false);
  const [focusTick, setFocusTick] = useState(0);
  /** the next card that becomes current takes focus (consumed by QueueCard) */
  const wantFocus = useRef(false);
  /** an editor, dialog or crop mode owns focus: a pending card-focus request waits until it closes */
  const focusBlocked = useRef(false);
  const requestFocus = useCallback(() => {
    wantFocus.current = true;
    setFocusTick((t) => t + 1);
  }, []);

  const queueQ = useQuery({
    queryKey: ["verify", "queue", applied] as const,
    queryFn: async (): Promise<QueuePage & { writesSeen: number }> => {
      // the writes settled before this request left: if more settle while it is out, its answer may predate them
      const writesSeen = writes.settled.current;
      const page = unwrap(
        await client.GET("/api/verify/queue", {
          params: { query: { limit: PAGE_LIMIT, ...(applied ? { sort: applied.sort, ...(applied.view !== null ? { view_threshold: applied.view } : {}) } : {}) } },
        }),
      );
      return { ...page, writesSeen };
    },
    staleTime: Infinity,
    refetchInterval: (q) => (q.state.data?.docs.some((d) => d.state === "pending") ? 3000 : false),
  });

  // Apply server snapshots only while no write is in flight (the acks are authoritative until then), and only a
  // snapshot that left after the last write settled: an older one lists an approved block as queued and current, and
  // applying it would take the reviewer back to the block they just approved. It is fetched again instead.
  const stash = useRef<(QueuePage & { writesSeen: number }) | null>(null);
  const refetchQueue = queueQ.refetch;
  const writesPending = useRef(0);
  writesPending.current = writes.pending;
  const apply = useCallback(
    (d: QueuePage) => {
      dispatch({ type: "loaded", items: d.items, total: d.total, counts: d.counts, docs: d.docs, cursor: d.cursor, replace: true });
      if (!controlsTimer.current) setControls({ sort: d.cursor.sort, view: d.cursor.view_threshold ?? null });
      setFirstLoad(true);
    },
    [dispatch],
  );
  useEffect(() => {
    const d = queueQ.data;
    if (!d) return;
    if (writesPending.current > 0) stash.current = d;
    else if (d.writesSeen !== writes.settled.current) void refetchQueue();
    else apply(d);
  }, [queueQ.data, apply, writes.settled, refetchQueue]);
  useEffect(() => {
    if (writes.pending === 0 && stash.current) {
      const d = stash.current;
      stash.current = null;
      if (d.writesSeen !== writes.settled.current) void refetchQueue();
      else apply(d);
    }
  }, [writes.pending, apply, writes.settled, refetchQueue]);

  // -- cursor persistence --------------------------------------------------------------------------------------

  const putCursor = useCallback(
    (c: Controls = controlsRef.current) =>
      writes.enqueue(async () =>
        unwrap(
          await client.PUT("/api/verify/cursor", {
            body: {
              sort: c.sort,
              view_threshold: c.view,
              doc_filter: ref.current.cursor.doc_filter ?? null,
              current_block_id: ref.current.currentId,
              request_id: crypto.randomUUID(),
            },
          }),
        ),
      ),
    [writes],
  );
  const cursorTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleCursor = useCallback(() => {
    if (cursorTimer.current) clearTimeout(cursorTimer.current);
    cursorTimer.current = setTimeout(() => {
      cursorTimer.current = null;
      void putCursor().catch(() => undefined);
    }, 300);
  }, [putCursor]);
  useEffect(
    () => () => {
      if (cursorTimer.current) clearTimeout(cursorTimer.current);
    },
    [],
  );

  const applyControls = useCallback(
    (c: Controls, delay: number) => {
      setControls(c);
      controlsRef.current = c;
      if (controlsTimer.current) clearTimeout(controlsTimer.current);
      controlsTimer.current = setTimeout(() => {
        controlsTimer.current = null;
        void putCursor(c)
          .then(() => setApplied(c))
          .catch((e) => {
            if (!(e instanceof CancelledError)) toast.error(`Not saved: ${e instanceof ApiError ? e.detail : "network error"}`);
          });
      }, delay);
    },
    [putCursor, toast],
  );
  useEffect(
    () => () => {
      if (controlsTimer.current) clearTimeout(controlsTimer.current);
    },
    [],
  );
  const setSort = useCallback((sort: QueueSort) => applyControls({ ...controlsRef.current, sort }, 0), [applyControls]);
  const setView = useCallback((view: number | null) => applyControls({ ...controlsRef.current, view }, 250), [applyControls]);
  const stepView = useCallback(
    (dir: 1 | -1) => {
      if (T !== null) applyControls({ ...controlsRef.current, view: stepViewBy(controlsRef.current.view, dir, T) }, 250);
    },
    [applyControls, T],
  );
  const cycleSort = useCallback(
    () => applyControls({ ...controlsRef.current, sort: SORTS[(SORTS.indexOf(controlsRef.current.sort) + 1) % SORTS.length] }, 0),
    [applyControls],
  );

  // -- navigation -------------------------------------------------------------------------------------------

  const browse = useCallback(
    (id: string) => {
      dispatch({ type: "browse", id });
      scheduleCursor();
    },
    [dispatch, scheduleCursor],
  );
  const browseBy = useCallback(
    (delta: number | "first" | "last") => {
      const s = ref.current;
      const all = s.pinned ? [s.pinned, ...s.items] : s.items;
      if (!all.length) return;
      const i = all.findIndex((x) => x.block_id === s.currentId);
      const j = delta === "first" ? 0 : delta === "last" ? all.length - 1 : Math.min(all.length - 1, Math.max(0, (i < 0 ? 0 : i) + delta));
      browse(all[j].block_id);
    },
    [browse],
  );
  const jumpTo = useCallback(
    async (id: string) => {
      const s = ref.current;
      const listed = s.items.find((i) => i.block_id === id) ?? (s.pinned?.block_id === id ? s.pinned : undefined);
      if (listed) {
        browse(id);
        requestFocus();
        return;
      }
      try {
        const d = await qc.fetchQuery({ queryKey: blockKey(id), queryFn: () => fetchBlock(id), staleTime: Infinity });
        dispatch({ type: "jump", item: itemFromDetail(d, ref.current.seen[id]) });
        scheduleCursor();
      } catch (e) {
        if (e instanceof ApiError && (e.status === 422 || e.status === 404)) toast.info("Not in your selection");
        else toast.error(`Could not open ${id}`);
      }
    },
    [browse, dispatch, qc, requestFocus, scheduleCursor, toast],
  );

  // the server's current block may be missing from the loaded pages (reload, back, view change): pin it
  useEffect(() => {
    const s = state;
    if (!s.currentId || s.pinned?.block_id === s.currentId || s.items.some((i) => i.block_id === s.currentId)) return;
    let live = true;
    qc.fetchQuery({ queryKey: blockKey(s.currentId), queryFn: () => fetchBlock(s.currentId!), staleTime: Infinity })
      .then((d) => live && dispatch({ type: "pin", item: itemFromDetail(d, s.seen[d.block.id] ?? (s.pinned?.block_id === d.block.id ? s.pinned : null)) }))
      .catch(() => live && s.items[0] && dispatch({ type: "browse", id: s.items[0].block_id }));
    return () => {
      live = false;
    };
  }, [state, qc, dispatch]);

  const loadMore = useCallback(async () => {
    const s = ref.current;
    if (s.items.length >= s.total) return;
    try {
      const d = unwrap(
        await client.GET("/api/verify/queue", {
          params: {
            query: {
              limit: PAGE_LIMIT,
              offset: s.items.length,
              ...(applied ? { sort: applied.sort, ...(applied.view !== null ? { view_threshold: applied.view } : {}) } : {}),
            },
          },
        }),
      );
      dispatch({ type: "loaded", items: d.items, total: d.total, counts: d.counts, docs: d.docs, cursor: ref.current.cursor, replace: false });
    } catch {
      /* the next browse retries */
    }
  }, [applied, dispatch]);

  // Resume: a saved cursor can sit beyond the first page. While the pinned current block is a queueable item that
  // sorts after the last loaded one, keep fetching the next page until the list contains it (then it is no longer
  // pinned and onNearEnd paging continues from there). Done/flagged blocks are never in the list: no paging for them.
  useEffect(() => {
    const p = state.pinned;
    const last = state.items[state.items.length - 1];
    if (!p || !last || state.items.length >= state.total || p.block_id !== state.currentId) return;
    if (["approved", "edited", "flagged", "rejected"].includes(p.status)) return;
    if (cmpItems(state.cursor.sort, p, last) <= 0) return;
    void loadMore();
  }, [state.pinned, state.items, state.total, state.currentId, state.cursor.sort, loadMore]);

  // -- actions ----------------------------------------------------------------------------------------------

  const act = useCallback(
    (kind: ActKind, opts: ActOpts = {}): Promise<ActResult> => {
      const s = ref.current;
      const id = kind === "back" ? null : s.currentId;
      if (kind !== "back" && !id) return Promise.resolve({ ok: false, error: new Error("no current block") });
      if (opts.expectId !== undefined && opts.expectId !== id) return Promise.resolve({ ok: false, error: new Error(`${opts.expectId} is no longer the current block`) });
      const rid = crypto.randomUUID();
      const optimistic = kind !== "edit";
      if (optimistic) dispatch({ type: "act", kind, blockId: id, rid });
      const doc = id ? (s.items.find((i) => i.block_id === id) ?? s.seen[id] ?? s.pinned) : null;
      return writes
        .enqueue(async () => {
          let flag = opts.flag;
          if (flag && opts.flagTarget) {
            try {
              flag = { ...flag, target_id: await opts.flagTarget() };
            } catch (cause) {
              throw new FlagTargetError(id ?? "", cause);
            }
          }
          const out: ReviewActionOut = unwrap(
            await client.POST("/api/verify/actions", {
              body: {
                kind,
                ...(id ? { block_id: id } : {}),
                ...(opts.text !== undefined ? { text: opts.text } : {}),
                confirm_content_change: opts.confirm ?? false,
                ...(flag ? { flag: { category: flag.category, note: flag.note, target_id: flag.target_id ?? null } } : {}),
                request_id: rid,
              },
            }),
          );
          return out;
        }, optimistic ? undefined : { inlineStatuses: [422] })
        .then((out): ActResult => {
          if (!optimistic) dispatch({ type: "act", kind, blockId: id, rid });
          dispatch({ type: "ack", rid, out });
          requestFocus();
          if (id) {
            void qc.invalidateQueries({ queryKey: blockKey(id) });
            if (doc && out.block_status)
              qc.setQueryData<PageBlock[]>(pageBlocksKey(doc.doc_id, doc.page), (rows) =>
                rows?.map((r) => (r.block_id === id ? { ...r, status: out.block_status! } : r)),
              );
          }
          return { ok: true, out };
        })
        .catch((error: unknown): ActResult => {
          if (error instanceof CancelledError) return { ok: false, error };
          if (!optimistic) {
            const body = error instanceof ApiError ? (error.body as { conflict?: EditConflict } | undefined) : undefined;
            if (error instanceof ApiError && (error.status === 409 || error.status === 422))
              return { ok: false, error, conflict: body?.conflict };
            toast.error(`Not saved: ${error instanceof ApiError ? error.detail : "network error"}`);
            return { ok: false, error };
          }
          writes.cancelQueued();
          dispatch({ type: "fail", rid });
          if (error instanceof FlagTargetError) {
            const why = error.cause instanceof ApiError ? error.cause.detail : "network error";
            toast.error(`Flag not sent: ${error.message} (${why})`);
          } else toast.error(`Not saved: ${error instanceof ApiError ? error.detail : "network error"}`);
          void qc.invalidateQueries({ queryKey: ["verify", "queue"] });
          requestFocus();
          return { ok: false, error };
        });
    },
    [dispatch, qc, requestFocus, toast, writes],
  );

  const viewAdded = useMemo(() => state.items.filter((i) => i.status === "auto_approved").length, [state.items]);

  return {
    state,
    stateRef: ref,
    dispatch,
    writes,
    T,
    controls,
    setSort,
    setView,
    stepView,
    cycleSort,
    firstLoad,
    queueQ,
    browse,
    browseBy,
    jumpTo,
    loadMore,
    act,
    viewAdded,
    focusTick,
    wantFocus,
    focusBlocked,
    requestFocus,
  };
}
