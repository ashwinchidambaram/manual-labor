import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useActiveJobs, useBlockIndexData, useConfirmScope, useModels, useSources, useStatus } from "../api/queries";
import type { Split, View } from "../api/schema";
import { useHotkeys } from "../hooks/useHotkeys";
import { useToast } from "../shell/Toast";
import { useSelectionEngine } from "../hooks/useSelectionEngine";
import ConfirmButton from "./ConfirmButton";
import {
  buildGroupsIndex,
  checkState,
  type CheckState,
  collapseAction,
  coverageIndex,
  defaultExpanded,
  expandAction,
  moveCursor,
  rowCounts,
  smartToggle,
  visibleRows,
} from "./derive";
import GroupTree from "./GroupTree";
import ModelPanel from "./ModelPanel";
import SelectionSummary from "./SelectionSummary";
import SourcesList, { UploadButton } from "./SourcesList";
import SplitModeControl from "./SplitModeControl";
import ViewToggle from "./ViewToggle";
import { Keycap } from "../onboarding/Copy";
import { keyLabel } from "../onboarding/guide";
import Hint from "../onboarding/Hint";
import WelcomeBand, { welcomeFacts } from "../onboarding/WelcomeBand";
import { useGuide } from "../shell/nextStep";

const VIEW_NAME: Record<View, string> = { topic: "Suggested topics", structure: "Document structure" };
const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";

function Panel({ error, retry, children, testid }: { error: Error | null; retry: () => void; children: React.ReactNode; testid: string }) {
  if (!error) return <>{children}</>;
  const e = error as Error & { code?: string; detail?: string };
  return (
    <div role="alert" data-testid={testid} className="rounded-xl border border-fail-line bg-fail-wash p-3 text-sm text-ink">
      <p>
        {e.code ? `${e.code}: ` : ""}
        {e.detail ?? e.message}
      </p>
      <button type="button" onClick={retry} className={`mt-1.5 min-h-[2rem] rounded-lg border border-line-strong bg-raised px-2.5 ${FOCUS}`}>
        Retry
      </button>
    </div>
  );
}

/** Non-blocking error: the content stays usable, the failure is visible and retryable. */
function Notice({ error, retry, testid, children }: { error: Error | null; retry: () => void; testid: string; children: React.ReactNode }) {
  if (!error) return null;
  const e = error as Error & { code?: string; detail?: string };
  return (
    <div role="alert" data-testid={testid} className="flex items-center gap-2 rounded-xl border border-fail-line bg-fail-wash px-3 py-1.5 text-sm text-ink">
      <span>
        {children} ({e.code ? `${e.code}: ` : ""}
        {e.detail ?? e.message})
      </span>
      <button type="button" onClick={retry} className={`min-h-[2rem] rounded-lg border border-line-strong bg-raised px-2.5 text-xs ${FOCUS}`}>
        Retry
      </button>
    </div>
  );
}

export default function ScopeScreen() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const eng = useSelectionEngine();
  const sources = useSources();
  const status = useStatus();
  const models = useModels();
  const jobs = useActiveJobs();
  const confirm = useConfirmScope();
  const toast = useToast();
  const [live, setLive] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [cursor, setCursor] = useState<string | null>(null);
  const lastIdx = useRef(0);
  const expandedInit = useRef(false);

  const sel = eng.data?.selection;
  const urlView = params.get("view");
  const view: View = urlView === "structure" || urlView === "topic" ? urlView : (sel?.active_view ?? "topic");
  const split: Split = sel?.article_split ?? "per_topic";

  useEffect(() => {
    if (!expandedInit.current && eng.docs.length) {
      expandedInit.current = true;
      setExpanded(defaultExpanded(eng.docs));
    }
  }, [eng.docs]);

  const rows = useMemo(() => visibleRows(eng.docs, view, expanded), [eng.docs, view, expanded]);
  const coverage = useMemo(() => coverageIndex(eng.data), [eng.data?.coverage]); // eslint-disable-line react-hooks/exhaustive-deps
  const index = useMemo(() => buildGroupsIndex(eng.docs), [eng.docs]);
  const checks = useMemo(() => {
    const m = new Map<string, CheckState>();
    for (const r of rows) {
      const { selected, total } = rowCounts(eng.ids, index, r.group.id, view);
      m.set(r.group.id, checkState(selected, total));
    }
    return m;
  }, [rows, eng.ids, index, view]);
  const filenames = useMemo(() => new Map((sources.data ?? []).map((s) => [s.slug, s.filename])), [sources.data]);

  // Cursor is a group id; when it does not exist in the current rows (view toggle, collapse)
  // fall back to the index-equivalent row (design 1.3).
  const found = rows.findIndex((r) => r.group.id === cursor);
  if (found >= 0) lastIdx.current = found;
  const cursorId = found >= 0 ? cursor : (rows[Math.min(lastIdx.current, rows.length - 1)]?.group.id ?? null);

  const gotFocus = useRef(false);
  useEffect(() => {
    if (gotFocus.current || eng.isLoading || !rows.length) return;
    gotFocus.current = true;
    document.querySelector<HTMLElement>("[data-zone='tree'] [tabindex='0']")?.focus();
  }, [rows.length, eng.isLoading]);

  const summary = eng.data?.summary;
  const groupedSlugs = new Set(eng.docs.map((d) => d.doc_id));
  const ungrouped = (sources.data ?? []).map((s) => s.slug).filter((s) => !groupedSlugs.has(s));
  const processing = ungrouped.length > 0;

  // Announce the reconciled selection once the server has caught up.
  const wasPending = useRef(false);
  useEffect(() => {
    if (eng.pending > 0) wasPending.current = true;
    else if (wasPending.current && summary) {
      wasPending.current = false;
      setLive(`Selected: ${summary.blocks} blocks, ${summary.articles} articles`);
    }
  }, [eng.pending, summary]);

  const focusTree = useCallback(() => {
    document.querySelector<HTMLElement>("[data-zone='tree'] [tabindex='0']")?.focus();
  }, []);

  const { apply } = eng;
  const changeView = useCallback(
    (v: View) => {
      if (v === view) return;
      setParams({ view: v }, { replace: true });
      apply({ op: "set_view", view: v });
      setLive(`Switched to ${VIEW_NAME[v]} view`);
    },
    [view, setParams, apply],
  );
  const changeSplit = useCallback((s: Split) => apply({ op: "set_split", split: s }), [apply]);

  // Callbacks read the latest ids/rows through refs so their identity only changes with the view:
  // memoised rows are not re-rendered on every selection change.
  const latest = useRef({ ids: eng.ids, rows, index, docs: eng.docs });
  latest.current = { ids: eng.ids, rows, index, docs: eng.docs };
  const toggleRow = useCallback(
    (id: string) => {
      const { ids, rows: rs, index: ix } = latest.current;
      const row = rs.find((r) => r.group.id === id);
      if (!row) return;
      const { selected, total } = rowCounts(ids, ix, id, view);
      if (total === 0) return;
      apply({
        op: smartToggle(checkState(selected, total)),
        group_id: id,
        doc_id: row.docId,
        subtree: view === "structure",
      });
    },
    [view, apply],
  );
  const selectOnly = useCallback(
    (id: string) => {
      const { ids, rows: rs } = latest.current;
      const row = rs.find((r) => r.group.id === id);
      if (!row) return;
      apply(
        { op: "deselect", block_ids: [...ids] },
        { op: "select_group", group_id: id, doc_id: row.docId, subtree: view === "structure" },
      );
    },
    [view, apply],
  );
  const selectDoc = useCallback(
    (id: string) => {
      const { index: ix, docs: ds } = latest.current;
      const d = ds.find((x) => x.doc_id === ix.docOf.get(id));
      if (d) apply({ op: "select", block_ids: d.groups.structure.flatMap((g) => g.block_ids) });
    },
    [apply],
  );
  const selectAll = useCallback(() => apply({ op: "select", block_ids: [...latest.current.index.selectable] }), [apply]);
  // `n` throws the whole selection away: it must be pressed twice within 3 s.
  const clearArmed = useRef<ReturnType<typeof setTimeout> | null>(null);
  // mirrors clearArmed for the mouse control's label
  const [armed, setArmed] = useState(false);
  useEffect(
    () => () => {
      if (clearArmed.current) clearTimeout(clearArmed.current);
    },
    [],
  );
  const selectNone = useCallback(() => {
    if (clearArmed.current) {
      clearTimeout(clearArmed.current);
      clearArmed.current = null;
      setArmed(false);
      apply({ op: "deselect", block_ids: [...latest.current.ids] });
      return;
    }
    setLive("Press n again to clear the selection");
    setArmed(true);
    clearArmed.current = setTimeout(() => {
      clearArmed.current = null;
      setArmed(false);
    }, 3000);
  }, [apply]);

  const toggleExpanded = useCallback((id: string) => {
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }, []);

  const { error: engError, clearError, settle } = eng;
  useEffect(() => {
    if (!engError) return;
    toast.error(engError);
    clearError();
  }, [engError, clearError, toast]);

  const onConfirm = useCallback(async () => {
    if (!summary || summary.blocks === 0) {
      setLive("Nothing selected");
      return;
    }
    if (processing) {
      setLive("Documents are still being processed");
      return;
    }
    try {
      if (!(await settle())) {
        setLive("Selection not saved; scope not confirmed");
        return;
      }
      await confirm.mutateAsync();
      nav("/verify");
    } catch (e) {
      const msg = `Could not confirm scope: ${e instanceof Error ? e.message : String(e)}`;
      setLive(msg);
      toast.error(msg);
    }
  }, [summary, processing, settle, confirm, nav, toast]);

  const focusZone = (zone: string, ...inner: string[]) => () => {
    for (const q of inner) {
      const el = document.querySelector<HTMLElement>(`[data-zone='${zone}'] ${q}`);
      if (el) return el.focus();
    }
  };

  useHotkeys({
    toggleView: () => changeView(view === "topic" ? "structure" : "topic"),
    focusTree,
    focusSources: focusZone("sources", "button[data-source]"),
    focusModels: () => {
      const inModels = document.activeElement?.closest("[data-zone='models']");
      if (inModels) focusTree();
      else focusZone("models", "[role='radio'][tabindex='0']", "button")();
    },
    focusSummary: () => document.querySelector<HTMLElement>("[data-zone='summary']")?.focus(),
    splitMode: () => changeSplit(split === "per_topic" ? "per_document" : "per_topic"),
    selectAll,
    selectNone,
    confirm: () => void onConfirm(),
  });

  const guide = useGuide();
  // the welcome's counts: selected blocks by type (from the block index the tree already loaded) and the manuals that
  // are grouped and listed here; a manual without groups is still being read
  const blockIndex = useBlockIndexData();
  const welcomeTypes = useMemo(() => {
    if (!blockIndex.data) return null;
    const t: Record<string, number> = {};
    for (const d of blockIndex.data) for (const b of d.blocks) if (eng.ids.has(b.id)) t[b.type] = (t[b.type] ?? 0) + 1;
    return t;
  }, [blockIndex.data, eng.ids]);
  const readyManuals = (sources.data ?? []).filter((s) => groupedSlugs.has(s.slug)).length;
  const welcome =
    guide?.open && summary && sources.data?.length
      ? welcomeFacts(sources.data, summary, eng.ids.size > 0 && eng.ids.size === index.selectable.size, { ready: readyManuals, types: welcomeTypes })
      : null;
  const noSources = sources.isSuccess && sources.data.length === 0 && eng.docs.length === 0;
  // the welcome is due (the guide flag says so) but its counts are still loading: keep its space so it does not push
  // the list down when it arrives
  const welcomeDue = !!guide?.open && !welcome && !noSources;
  const jobsList = jobs.data ?? [];

  return (
    <main className="flex flex-col gap-6 px-4 pb-32 pt-5 wide:px-8 wide:pb-10 wide:pt-6" data-testid="scope-screen">
      <h2 className="text-xl font-semibold tracking-[-0.01em] text-ink">Choose what goes into your knowledge base</h2>
      {welcome && guide ? (
        <WelcomeBand facts={welcome} onDismiss={guide.hide} />
      ) : welcomeDue ? (
        <div aria-hidden="true" data-testid="welcome-placeholder" className="min-h-[17.5rem] rounded-2xl bg-sunk ring-1 ring-inset ring-line-soft" />
      ) : null}
      {guide?.saveError ? (
        <p role="alert" className="rounded-xl border border-fail-line bg-fail-wash px-3 py-2 text-sm text-ink">
          {guide.saveError}
        </p>
      ) : null}
      {/* fluid layout (design 13 section 9.4): one column, then Topics beside the summary from `wide`, then Sources in
          their own column from `tri` (the wrapper below becomes `contents`, so its two panes are the grid's items) */}
      <div className="grid grid-cols-1 gap-x-8 gap-y-6 wide:grid-cols-[minmax(0,1fr)_var(--scope-aside-w)] tri:grid-cols-[var(--sources-w)_minmax(0,1fr)_var(--scope-aside-w)]">
        <div className="flex min-w-0 flex-col gap-6 tri:contents">
          <div
            className="flex min-w-0 flex-col gap-3 tri:sticky tri:top-[calc(var(--jobs-bar,0px)+1.5rem)] tri:self-start"
            aria-label="Sources panel"
            role="group"
          >
            <Notice error={status.error} retry={() => void status.refetch()} testid="status-error">
              Processing status is unavailable.
            </Notice>
            <Panel error={sources.error} retry={() => void sources.refetch()} testid="sources-error">
              <SourcesList
                sources={sources.data ?? []}
                status={status.data}
                jobs={jobsList}
                onGoTo={(slug) => {
                  document.querySelector(`[data-doc='${slug}']`)?.scrollIntoView({ block: "start" });
                  const first = rows.find((r) => r.docId === slug);
                  if (first) setCursor(first.group.id);
                }}
              />
            </Panel>
          </div>

          <div className="flex min-w-0 flex-col gap-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <h3 className="text-lg font-semibold text-ink">Topics</h3>
              <ViewToggle view={view} onChange={changeView} />
              <span className="ml-auto flex flex-wrap items-center gap-1 text-xs text-muted">
                <Keycap>{keyLabel("toggleView")}</Keycap> switch <span aria-hidden="true">·</span> <Keycap>{keyLabel("toggleRow")}</Keycap> select{" "}
                <span aria-hidden="true">·</span> <Keycap>{keyLabel("moveDown")}</Keycap>
                <Keycap>{keyLabel("moveUp")}</Keycap> move
              </span>
            </div>
            <p className="-mt-1 text-sm text-muted">Same blocks, two ways to browse. Switching never changes what is selected.</p>
            <Notice error={jobs.error} retry={() => void jobs.refetch()} testid="jobs-error">
              Background jobs cannot be listed.
            </Notice>
            <Notice error={eng.blocksError} retry={eng.retryBlocks} testid="blocks-error">
              Live counts are unavailable until the block index loads; the server still saves your choices.
            </Notice>
            <div role="status" aria-live="polite" data-testid="live" className="sr-only">
              {live}
            </div>
            <Panel error={eng.groupsError ?? eng.selectionError} retry={eng.retry} testid="tree-error">
              {noSources ? (
                <div data-testid="scope-empty" className="rounded-2xl border border-dashed border-line-strong bg-raised px-6 py-10 text-center">
                  <p className="mx-auto max-w-prose text-base text-ink">Manual Labor turns PDF and DOCX manuals into a reviewed knowledge base.</p>
                  <p className="mb-4 mt-1 text-sm text-muted">Step 1: add documents. They are read here, on this machine.</p>
                  <UploadButton label="Add documents" />
                </div>
              ) : eng.isLoading ? (
                <div aria-busy="true" data-testid="tree-loading" className="flex flex-col gap-px overflow-hidden rounded-xl border border-line">
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="h-[3.25rem] animate-pulse bg-sunk" />
                  ))}
                </div>
              ) : (
                <GroupTree
                  docs={eng.docs}
                  rows={rows}
                  view={view}
                  coverage={coverage}
                  checks={checks}
                  expanded={expanded}
                  cursor={cursorId}
                  stale={eng.pending > 0}
                  filenames={filenames}
                  ungrouped={ungrouped}
                  selected={eng.ids}
                  known={eng.data?.selection.known_docs}
                  onCursor={setCursor}
                  onToggle={toggleRow}
                  onSelectOnly={selectOnly}
                  onSelectDoc={selectDoc}
                  onExpand={toggleExpanded}
                  onExpandKey={(id) => {
                    const a = expandAction(rows, id, expanded);
                    if (!a) return;
                    if ("expand" in a) toggleExpanded(a.expand);
                    else setCursor(a.move);
                  }}
                  onCollapseKey={(id) => {
                    const a = collapseAction(rows, id, expanded);
                    if (!a) return;
                    if ("collapse" in a) toggleExpanded(a.collapse);
                    else setCursor(a.move);
                  }}
                  onMove={(d) => setCursor(moveCursor(rows, cursorId, d))}
                  onEdge={(w) => setCursor(rows.length ? rows[w === "first" ? 0 : rows.length - 1].group.id : null)}
                />
              )}
            </Panel>
          </div>
        </div>

        {/* sticky beside the long list, and never taller than the window: it scrolls on its own so every control stays reachable */}
        <aside
          className="flex min-w-0 flex-col gap-5 wide:sticky wide:top-[calc(var(--jobs-bar,0px)+1.5rem)] wide:-m-1 wide:max-h-[calc(100dvh-3rem-var(--jobs-bar,0px))] wide:self-start wide:overflow-y-auto wide:p-1"
          aria-label="Summary and models"
        >
          <div className="flex flex-col gap-5 rounded-2xl border border-line bg-raised p-5 shadow-lift">
            {summary ? <SplitModeControl split={split} summary={summary} view={view} onChange={changeSplit} /> : null}
            {summary ? <SelectionSummary summary={summary} processing={ungrouped.length} /> : null}
            {/* below the wide breakpoint the rail is a bottom sheet: the primary action is pinned just above it, with the
                selection's numbers, so they are on screen at every size (design 13 section 9.4) */}
            <div
              data-testid="confirm-dock"
              className="max-wide:fixed max-wide:inset-x-0 max-wide:bottom-[var(--guide-sheet,0px)] max-wide:z-20 max-wide:border-t max-wide:border-line max-wide:bg-raised max-wide:px-4 max-wide:py-2"
            >
              {summary ? (
                <p className="mb-1.5 text-xs text-muted wide:hidden" data-testid="dock-counts">
                  <span className="font-bold tabular-nums text-ink" data-testid="dock-blocks">
                    {summary.blocks}
                  </span>{" "}
                  {summary.blocks === 1 ? "block" : "blocks"} · estimated review{" "}
                  <span className="font-bold tabular-nums text-ink" data-testid="dock-queued">
                    {summary.review_load.queued}
                  </span>
                </p>
              ) : null}
              <ConfirmButton blocks={summary?.blocks ?? 0} processing={processing} busy={confirm.isPending} onConfirm={() => void onConfirm()} />
            </div>
            {summary ? (
              <div className="flex flex-wrap items-center gap-2 border-t border-line-soft pt-4 text-sm" data-testid="select-controls">
                <Hint id="selectAll">
                  <button type="button" onClick={selectAll} className={`min-h-[2.25rem] rounded-lg px-2.5 text-muted hover:bg-sunk hover:text-ink ${FOCUS}`}>
                    Select all
                  </button>
                </Hint>
                <Hint id="selectNone">
                  <button
                    type="button"
                    onClick={selectNone}
                    data-testid="clear-selection"
                    className={`min-h-[2.25rem] rounded-lg px-2.5 ${FOCUS} ${armed ? "bg-needs-wash font-semibold text-needs-ink" : "text-muted hover:bg-sunk hover:text-ink"}`}
                  >
                    {armed ? "Press again to clear" : "Clear selection"}
                  </button>
                </Hint>
              </div>
            ) : null}
          </div>
          <div className="rounded-2xl border border-line bg-raised p-5">
            <Panel error={models.error} retry={() => void models.refetch()} testid="models-error">
              {models.data ? <ModelPanel data={models.data} /> : <div aria-busy="true" className="h-24 animate-pulse rounded-lg bg-sunk" />}
            </Panel>
          </div>
        </aside>
      </div>
    </main>
  );
}
