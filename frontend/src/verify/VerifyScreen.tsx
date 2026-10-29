import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, client, unwrap } from "../api/client";
import { trackJob } from "../api/queries";
import type { FigureRailItem, FlagCategory, PageRef } from "../api/schema";
import { useHotkeys } from "../hooks/useHotkeys";
import { useToast } from "../shell/Toast";
import ActionBar from "./ActionBar";
import CropEditor from "./CropEditor";
import ExtractedPane, { diffOps, type EditState } from "./ExtractedPane";
import FigureRail from "./FigureRail";
import FlagDialog from "./FlagDialog";
import { validCrop, type BBox } from "./geometry";
import { FOCUS } from "./labels";
import Queue from "./Queue";
import SourcePane from "./SourcePane";
import StatusStrip from "./StatusStrip";
import { blockKey, fetchBlock, useVerifyState } from "./useVerifyState";

interface CropMode {
  item: FigureRailItem;
  box: BBox | null;
  page: PageRef | null;
  busy: boolean;
}

export default function VerifyScreen() {
  const qc = useQueryClient();
  const toast = useToast();
  const v = useVerifyState();
  const { state } = v;
  const [view, setView] = useState<"text" | "diff">("text");
  const [zoom, setZoom] = useState(false);
  const [edit, setEdit] = useState<EditState | null>(null);
  const [flagOpen, setFlagOpen] = useState(false);
  const [crop, setCrop] = useState<CropMode | null>(null);
  const [live, setLive] = useState("");
  // read by QueueCard layout effects during this same commit: while an editor or crop mode is open, no card takes focus
  v.focusBlocked.current = edit !== null || crop !== null;

  const currentId = state.currentId;
  const detailQ = useQuery({
    queryKey: blockKey(currentId),
    queryFn: () => fetchBlock(currentId!),
    enabled: currentId !== null,
    staleTime: Infinity,
    gcTime: 60_000,
    retry: false,
  });
  const detail = detailQ.data;
  const isFigure = detail?.block.type === "figure";

  // first load: focus goes to the current card
  useEffect(() => {
    if (v.firstLoad) v.requestFocus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [v.firstLoad]);

  // prefetch the next two blocks and the next page image
  useEffect(() => {
    const i = state.items.findIndex((x) => x.block_id === currentId);
    const next = state.items.slice(i + 1, i + 3);
    for (const n of next) void qc.prefetchQuery({ queryKey: blockKey(n.block_id), queryFn: () => fetchBlock(n.block_id), staleTime: Infinity });
    const n0 = next[0];
    if (n0 && detail && n0.page !== detail.block.page && typeof Image !== "undefined") new Image().src = `/api/docs/${n0.doc_id}/pages/${n0.page}.png?dpi=150`;
  }, [currentId, state.items, detail, qc]);

  // an unsaved draft is not a decision: leaving the block drops it
  useEffect(() => setEdit((e) => (e && !e.busy ? null : e)), [currentId]);

  const announce = useCallback((m: string) => setLive(m), []);

  const approve = useCallback(async () => {
    const id = state.currentId;
    if (!id) return;
    const res = v.act("approve");
    v.requestFocus();
    const r = await res;
    if (r.ok) announce(`Approved ${id}. Next: ${r.out.next?.block_id ?? "none"}`);
  }, [state.currentId, v, announce]);
  const skip = useCallback(async () => {
    const id = state.currentId;
    if (!id) return;
    const res = v.act("skip");
    v.requestFocus();
    const r = await res;
    if (r.ok) announce(`Skipped ${id}. Next: ${r.out.next?.block_id ?? "none"}`);
  }, [state.currentId, v, announce]);
  const back = useCallback(async () => {
    if ((state.cursor.trail ?? []).length === 0) announce("Nothing to go back to");
    const res = v.act("back");
    v.requestFocus();
    const r = await res;
    if (r.ok) announce(`Back to ${r.out.next?.block_id ?? "none"}`);
  }, [(state.cursor.trail ?? []).length, v, announce]);

  // `e` before the block's detail has arrived is remembered, not dropped
  const [editWanted, setEditWanted] = useState(false);
  const startEdit = useCallback(() => {
    if (!state.currentId) return;
    if (!detail) {
      setEditWanted(true);
      return;
    }
    if (isFigure) return;
    setEdit({ text: detail.block.clean_text ?? detail.block.raw_text, error: null, conflict: null, conflictText: null, busy: false });
  }, [detail, isFigure, state.currentId]);
  useEffect(() => {
    if (editWanted && detail) {
      setEditWanted(false);
      if (!isFigure) setEdit({ text: detail.block.clean_text ?? detail.block.raw_text, error: null, conflict: null, conflictText: null, busy: false });
    }
  }, [editWanted, detail, isFigure]);
  useEffect(() => setEditWanted(false), [currentId]);

  const saveEdit = useCallback(
    async (confirm: boolean) => {
      if (!edit) return;
      // a confirmation sends exactly the text the server flagged, never what the textarea holds now
      const text = confirm && edit.conflict && edit.conflictText !== null ? edit.conflictText : edit.text;
      setEdit((e) => (e ? { ...e, busy: true, error: null } : e));
      const id = state.currentId;
      const r = await v.act("edit", { text, confirm });
      if (r.ok) {
        setEdit(null);
        v.requestFocus();
        announce(`Edited ${id}. Next: ${r.out.next?.block_id ?? "none"}`);
        return;
      }
      if (r.conflict) setEdit((e) => (e ? { ...e, busy: false, conflict: r.conflict ?? null, conflictText: text } : e));
      else setEdit((e) => (e ? { ...e, busy: false, error: r.error instanceof ApiError ? r.error.detail : "Not saved" } : e));
    },
    [edit, state.currentId, v, announce],
  );

  const submitFlag = useCallback(
    async (category: FlagCategory, note: string | null) => {
      setFlagOpen(false);
      const target = detail?.block.type === "figure" && (category === "bad_crop" || category === "missing_figure") ? detail.block.figure_id : null;
      const id = state.currentId;
      const res = v.act("flag", { flag: { category, note, target_id: target ?? null } });
      v.requestFocus();
      const r = await res;
      if (r.ok) announce(`Flagged ${id}. Next: ${r.out.next?.block_id ?? "none"}`);
    },
    [detail, state.currentId, v, announce],
  );

  const openCrop = useCallback(
    async (item: FigureRailItem) => {
      const bbox = item.record.bbox;
      try {
        const d = await qc.fetchQuery({ queryKey: blockKey(item.block_id), queryFn: () => fetchBlock(item.block_id), staleTime: Infinity });
        setCrop({ item, box: bbox && bbox.length === 4 ? ([...bbox] as BBox) : null, page: d.page, busy: false });
      } catch {
        toast.error("Could not open the crop editor");
      }
    },
    [qc, toast],
  );
  const saveCrop = useCallback(async () => {
    if (!crop || !crop.box) return;
    setCrop({ ...crop, busy: true });
    try {
      const out = await v.writes.enqueue(async () =>
        unwrap(
          await client.PUT("/api/figures/{fid}/bbox", {
            params: { path: { fid: crop.item.figure_id } },
            body: { bbox: crop.box!, request_id: crypto.randomUUID() },
          }),
        ),
      );
      trackJob(qc, out.job);
      toast.info("Crop saved. Figures are being re-extracted");
      setCrop(null);
      v.requestFocus();
    } catch (e) {
      setCrop((c) => (c ? { ...c, busy: false } : c));
      toast.error(`Crop not saved: ${e instanceof ApiError ? e.detail : "network error"}`);
    }
  }, [crop, qc, toast, v]);

  const focusCard = useCallback(() => v.requestFocus(), [v]);

  useHotkeys(
    {
      vApprove: () => void approve(),
      vEdit: startEdit,
      vFlag: () => state.currentId && setFlagOpen(true),
      vSkip: () => void skip(),
      vBack: () => void back(),
      vToggleDiff: () => detail && setView((x) => (x === "text" ? (diffOps(detail) ? "diff" : "text") : "text")),
      vFocusSource: () => document.querySelector<HTMLElement>("[data-zone='source'] [data-current='true']")?.focus(),
      vFocusRail: () => document.querySelector<HTMLElement>("[data-zone='rail'] [data-rail-focusable]")?.focus(),
      vSort: () => v.cycleSort(),
      vViewDown: () => v.stepView(-1),
      vViewUp: () => v.stepView(1),
      vZoom: () => setZoom((z) => !z),
      vEscape: () => {
        if (edit?.conflict) setEdit({ ...edit, conflict: null, conflictText: null });
        else if (edit) {
          setEdit(null);
          focusCard();
        } else if (crop) {
          setCrop(null);
          focusCard();
        } else focusCard();
      },
      vBrowseNext: () => {
        v.browseBy(1);
        v.requestFocus();
      },
      vBrowsePrev: () => {
        v.browseBy(-1);
        v.requestFocus();
      },
      vFirst: () => {
        v.browseBy("first");
        v.requestFocus();
      },
      vLast: () => {
        v.browseBy("last");
        v.requestFocus();
      },
      vSaveEdit: () => void saveEdit(false),
    },
    true,
  );

  const sourcePage = crop?.page ?? detail?.page ?? null;
  const cropState = useMemo(
    () => (crop && crop.box ? { box: crop.box, onChange: (b: BBox) => setCrop((c) => (c ? { ...c, box: b } : c)) } : null),
    [crop],
  );
  const saveState = v.writes.pending > 0 ? `Saving (${v.writes.pending})` : v.writes.failed ? "Not saved" : "Saved";
  const partial = state.items.length < state.total;
  const detailError = detailQ.error
    ? detailQ.error instanceof ApiError && detailQ.error.status === 422
      ? "This block is not in your selection"
      : "Could not load this block"
    : null;

  return (
    <main className="flex min-h-[calc(100vh-8rem)] flex-col" data-testid="verify-screen">
      <h2 className="sr-only">Verify</h2>
      <StatusStrip
        counts={state.counts}
        viewAdded={v.viewAdded}
        viewAddedPartial={partial}
        appliedView={state.cursor.view_threshold ?? null}
        docs={state.docs}
        threshold={v.T}
        view={v.controls.view}
        sort={v.controls.sort}
        onView={v.setView}
        onSort={v.setSort}
        saveState={saveState}
      />
      {v.queueQ.isError ? (
        <div role="alert" className="flex items-center gap-2 bg-red-50 px-4 py-2 text-sm text-red-900" data-testid="queue-error">
          Could not load the review queue.
          <button type="button" className={`rounded border border-red-500 px-2 ${FOCUS}`} onClick={() => void v.queueQ.refetch()}>
            Retry
          </button>
        </div>
      ) : null}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 lg:grid-cols-[18rem_1fr_1fr] xl:h-[calc(100vh-13rem)] xl:grid-cols-[20rem_1fr_1fr_16rem]">
        <div className="h-72 lg:h-auto xl:h-full">
          <Queue
            items={state.items}
            total={state.total}
            pinned={state.pinned}
            currentId={currentId}
            docs={state.docs}
            counts={state.counts}
            focusTick={v.focusTick}
            wantFocus={v.wantFocus}
            focusBlocked={v.focusBlocked}
            onSelect={v.browse}
            onNearEnd={() => void v.loadMore()}
          />
        </div>
        <div className="order-3 flex min-h-0 flex-col lg:order-none">
          <ExtractedPane
            detail={detail}
            loading={detailQ.isLoading && currentId !== null}
            error={detailError}
            view={view}
            onView={setView}
            edit={edit}
            onEditText={(t) => setEdit((e) => (e ? { ...e, text: t, error: null } : e))}
            onConfirmConflict={() => void saveEdit(true)}
            onKeepEditing={() => setEdit((e) => (e ? { ...e, conflict: null, conflictText: null } : e))}
            threshold={v.T}
          />
        </div>
        <div className="order-2 flex max-h-[80vh] min-h-0 flex-col lg:order-none xl:max-h-none">
          {sourcePage ? (
            <SourcePane page={sourcePage} detail={detail ?? null} currentId={currentId} zoom={zoom} onJump={(id) => void v.jumpTo(id)} crop={cropState} />
          ) : (
            <section role="region" aria-label="Source page" className="p-3 text-sm text-slate-600">
              No block selected
            </section>
          )}
          {crop ? (
            <CropEditor
              figureId={crop.item.figure_id}
              box={crop.box}
              page={crop.page}
              onChange={(b) => setCrop((c) => (c ? { ...c, box: b } : c))}
              onSave={() => void saveCrop()}
              onCancel={() => {
                setCrop(null);
                focusCard();
              }}
              busy={crop.busy}
            />
          ) : null}
        </div>
        <div className="order-4 min-h-0 lg:col-span-3 xl:col-span-1">
          <FigureRail detail={detail} enqueue={v.writes.enqueue} onCrop={(it) => void openCrop(it)} />
        </div>
      </div>
      <ActionBar
        hasCurrent={currentId !== null}
        isFigure={!!isFigure}
        onApprove={() => void approve()}
        onEdit={startEdit}
        onFlag={() => state.currentId && setFlagOpen(true)}
        onSkip={() => void skip()}
        onBack={() => void back()}
        onHelp={() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "?", bubbles: true }))}
      />
      <p role="status" aria-live="polite" className="sr-only" data-testid="live">
        {state.notice ?? live}
      </p>
      {flagOpen ? <FlagDialog onSubmit={(c, n) => void submitFlag(c, n)} onCancel={() => { setFlagOpen(false); focusCard(); }} /> : null}
    </main>
  );
}

// validCrop is re-exported for the screen's tests
export { validCrop };
