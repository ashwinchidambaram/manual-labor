import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, client, unwrap } from "../api/client";
import { trackJob, useActiveJobs, useExportStatus, useSources } from "../api/queries";
import type { FigureRailItem, FlagCategory, PageRef } from "../api/schema";
import { useHotkeys } from "../hooks/useHotkeys";
import { useNextStep } from "../shell/nextStep";
import { useMediaQuery, VAST_QUERY } from "../shell/useMediaQuery";
import { useToast } from "../shell/Toast";
import { Keycap } from "../onboarding/Copy";
import { keyLabel } from "../onboarding/guide";
import { coachFor } from "./coach";
import { pageMarks } from "./pageMarks";
import PageStrip from "./PageStrip";
import ActionBar from "./ActionBar";
import CropEditor from "./CropEditor";
import ExtractedPane, { diffOps, type EditState } from "./ExtractedPane";
import FigureRail from "./FigureRail";
import FlagNotice from "../agent/FlagNotice";
import FlagDialog from "./FlagDialog";
import { validCrop, type BBox } from "./geometry";
import { cardTitle, FOCUS } from "./labels";
import Queue from "./Queue";
import SourcePane from "./SourcePane";
import StatusStrip from "./StatusStrip";
import { isPipelineJob, isReadingJob } from "../shell/jobStep";
import { beingScored, scoringJob, scoringWords } from "./scoringWork";
import { useReviewChangeNote } from "./reviewChange";
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
  // the empty queue offers "Next: export" only when the gate is open: read it again whenever the list empties
  const exportGate = useExportStatus();
  const listEmpty = state.items.length === 0 && !state.pinned;
  const refetchGate = exportGate.refetch;
  useEffect(() => {
    if (listEmpty) void refetchGate();
  }, [listEmpty, refetchGate]);
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
      const id = state.currentId;
      if (!id) return;
      // a crop or missing-figure flag on a figure block targets the figure (design 09 O6). The figure id is only in
      // the block's detail. The queue advances at once like every other action (no key can land on the flagged
      // block); if the detail has not arrived yet, the figure id is loaded inside the queued write, and if that
      // fails the flag is not sent (never silently re-targeted at the block).
      const d = detail && detail.block.id === id ? detail : undefined;
      const item = state.items.find((i) => i.block_id === id) ?? (state.pinned?.block_id === id ? state.pinned : null);
      const figureCategory = category === "bad_crop" || category === "missing_figure";
      const target = d && d.block.type === "figure" && figureCategory ? d.block.figure_id : null;
      const flagTarget =
        !d && figureCategory && item?.type === "figure"
          ? async () => {
              const got = await qc.fetchQuery({ queryKey: blockKey(id), queryFn: () => fetchBlock(id), staleTime: Infinity });
              return got.block.type === "figure" ? (got.block.figure_id ?? null) : null;
            }
          : undefined;
      const res = v.act("flag", { flag: { category, note, target_id: target ?? null }, flagTarget });
      v.requestFocus();
      const r = await res;
      if (r.ok) announce(`Flagged ${id}. Next: ${r.out.next?.block_id ?? "none"}`);
    },
    [detail, state.currentId, state.items, state.pinned, qc, v, announce],
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
  const currentItem = state.items.find((i) => i.block_id === currentId) ?? (state.pinned?.block_id === currentId ? state.pinned : null);
  const sources = useSources();
  const docTitles = useMemo(() => new Map((sources.data ?? []).map((x) => [x.slug, x.filename])), [sources.data]);
  // scoring still queued or running (server truth: the active jobs), so an empty list never reads "All caught up"
  const activeJobs = useActiveJobs();
  const jobs = activeJobs.data ?? [];
  const work = scoringJob(jobs);
  const busyFor = beingScored(jobs);
  // only a job that scores re-scores a stale document; one that only reads manuals puts nothing in this list
  const rescoring = beingScored(jobs.filter((j) => !isReadingJob(j)));
  const pipeline = jobs.filter(isPipelineJob);
  const reading = pipeline.length > 0 && pipeline.every(isReadingJob);
  const scoring = work ? scoringWords(work, (slug) => docTitles.get(slug) ?? slug) : null;
  // the reducer's counts are placeholders until a snapshot is applied: they are not "the counts before the job"
  const change = useReviewChangeNote(state.loaded ? state.counts : null);
  const docTitle = currentItem ? ((sources.data ?? []).find((x) => x.slug === currentItem.doc_id)?.filename ?? null) : null;
  const title = currentItem ? cardTitle(currentItem.section_title, docTitle, currentItem.page, currentItem.type) : null;
  const ownDetail = detail && detail.block.id === currentId ? detail : undefined;
  useNextStep(currentId ? coachFor(ownDetail, currentItem?.weakest_word) : null);
  const marks = useMemo(() => pageMarks(ownDetail?.block ?? null, ownDetail?.why ?? []), [ownDetail]);
  const showStrip = !zoom && !crop && !!ownDetail && !!ownDetail.page.render_url && ownDetail.page.width > 0 && (ownDetail.block.bbox ?? []).length === 4;
  const big = zoom || !!crop;
  // fluid layout (design 13 section 9): from `vast` the whole page has its own column, except while zoomed or cropping
  const vast = useMediaQuery(VAST_QUERY);
  const pageInColumn = vast && !big && !!sourcePage?.render_url;
  // the strip and the locator share the band; from `split` they sit in the text's and the evidence's columns
  const bandGrid = showStrip && !big;
  const aspect = sourcePage && sourcePage.width > 0 && sourcePage.height > 0 ? sourcePage.width / sourcePage.height : 0.77;
  // the strip frame's rendered height: the locator beside it is sized from it, so the band is as tall as the block needs
  const [stripFrame, setStripFrame] = useState(0);
  const locatorH = stripFrame > 0 ? `${stripFrame}px` : "var(--strip-max)";
  const at = state.items.findIndex((i) => i.block_id === currentId);
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
    <main className="flex min-h-0 flex-1 flex-col" data-testid="verify-screen">
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
        change={change}
        busy={busyFor}
        rescoring={rescoring}
      />
      {v.queueQ.isError ? (
        <div role="alert" className="flex shrink-0 items-center gap-2 bg-fail-wash px-4 py-2 text-sm text-ink wide:px-7" data-testid="queue-error">
          <span aria-hidden="true" className="font-bold text-fail">
            ✕
          </span>
          Could not load the review queue.
          <button type="button" className={`min-h-[2rem] rounded-lg border border-line-strong bg-raised px-2.5 ${FOCUS}`} onClick={() => void v.queueQ.refetch()}>
            Retry
          </button>
        </div>
      ) : null}
      {/* one row that fills the frame: the queue and the work area scroll inside it, never the frame */}
      <div
        className={`flex min-h-0 flex-1 flex-col wide:grid wide:grid-rows-[minmax(0,1fr)] ${
          pageInColumn ? "wide:grid-cols-[var(--queue-w)_minmax(0,1fr)_var(--page-col-w)]" : "wide:grid-cols-[var(--queue-w)_minmax(0,1fr)]"
        }`}
      >
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
          threshold={v.T}
          gate={exportGate.data}
          docTitles={docTitles}
          scoring={scoring}
          busyFor={busyFor}
          reading={reading}
          rescoring={rescoring}
        />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div
            data-testid="page-band"
            className={`flex shrink-0 gap-4 border-b border-line bg-sunk px-4 py-3 short:py-2 wide:gap-5 wide:px-7 ${
              big ? "flex-col" : bandGrid ? "items-start split:grid split:grid-cols-[minmax(0,1fr)_var(--evidence-w)] split:gap-0 split:px-0 split:py-0" : "items-start"
            }`}
          >
            {showStrip && ownDetail ? <PageStrip page={ownDetail.page} bbox={ownDetail.block.bbox as number[]} marks={marks} pageNo={ownDetail.page.page} onFrameHeight={setStripFrame} /> : null}
            <div
              className={
                big || !showStrip
                  ? "flex min-w-0 flex-1 flex-col gap-2"
                  : "hidden w-max max-w-[var(--locator-max)] shrink-0 flex-col gap-1.5 wide:flex split:w-auto split:max-w-none split:self-stretch split:border-l split:border-line split:px-5 split:py-3 short:split:py-2"
              }
              data-testid="page-locator"
            >
              <p className="flex items-baseline justify-between gap-2 text-2xs font-semibold uppercase tracking-[0.07em] text-muted">
                <span>{sourcePage ? `Page ${sourcePage.page}` : "Page"}</span>
                {big && !crop ? (
                  <span className="flex items-center gap-1 font-normal normal-case tracking-normal">
                    <Keycap>{keyLabel("vZoom")}</Keycap> back to the block
                  </span>
                ) : null}
              </p>
              {pageInColumn ? (
                <p className="text-xs text-muted">The whole page is on the right.</p>
              ) : sourcePage ? (
                // beside the strip, the small locator is never the band's tallest part: as wide as the strip frame's height
                // allows for this page's shape, and never wider than its cell (design 13 section 9.3). One parent in every mode, so
                // Z never remounts the page (focus on a block's outline survives it).
                <div style={bandGrid ? { width: `max(var(--locator-min), min(var(--locator-max), calc((${locatorH} - 1.25rem) * ${aspect.toFixed(4)})))` } : undefined}>
                  <SourcePane page={sourcePage} detail={detail ?? null} currentId={currentId} zoom={zoom} onJump={(id) => void v.jumpTo(id)} crop={cropState} />
                </div>
              ) : (
                <section role="region" aria-label="Source page" className="text-sm text-muted">
                  No block selected
                </section>
              )}
              {!big && !pageInColumn && sourcePage?.render_url ? (
                <p className="flex flex-wrap items-center gap-1 text-2xs text-muted">
                  <Keycap>{keyLabel("vZoom")}</Keycap> whole page
                </p>
              ) : null}
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
          </div>
          {ownDetail ? <FlagNotice detail={ownDetail} /> : null}
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
            title={title}
            aside={<FigureRail detail={detail} enqueue={v.writes.enqueue} onCrop={(it) => void openCrop(it)} />}
          />
        </div>
        {pageInColumn && sourcePage ? (
          // from `vast`: the whole page, fit to its own column, the current block outlined (design 13 section 9.2)
          <div data-testid="page-column" className="flex min-h-0 min-w-0 flex-col gap-2 overflow-auto border-l border-line bg-sunk px-5 py-3">
            <p className="text-2xs font-semibold uppercase tracking-[0.07em] text-muted">Page {sourcePage.page}</p>
            <SourcePane page={sourcePage} detail={detail ?? null} currentId={currentId} zoom={false} onJump={(id) => void v.jumpTo(id)} crop={null} />
            <p className="flex flex-wrap items-center gap-1 text-2xs text-muted">
              <Keycap>{keyLabel("vZoom")}</Keycap> zoom the page
            </p>
          </div>
        ) : null}
      </div>
      <ActionBar
        hasCurrent={currentId !== null}
        isFigure={!!isFigure}
        numeric={!!ownDetail?.block.has_numeric_spec}
        position={at >= 0 ? `Block ${at + 1} of ${state.total}` : null}
        saveState={saveState}
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
