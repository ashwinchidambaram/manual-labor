import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useActiveJobs, useConfirmScope, useModels, useSources, useStatus } from "../api/queries";
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

const VIEW_NAME: Record<View, string> = { topic: "Suggested topics", structure: "Document structure" };
const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";

function Panel({ error, retry, children, testid }: { error: Error | null; retry: () => void; children: React.ReactNode; testid: string }) {
  if (!error) return <>{children}</>;
  const e = error as Error & { code?: string; detail?: string };
  return (
    <div role="alert" data-testid={testid} className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900">
      <p>
        {e.code ? `${e.code}: ` : ""}
        {e.detail ?? e.message}
      </p>
      <button type="button" onClick={retry} className={`mt-1 rounded border border-red-400 px-2 py-0.5 ${FOCUS}`}>
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
    <div role="alert" data-testid={testid} className="flex items-center gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-sm text-amber-950">
      <span>
        {children} ({e.code ? `${e.code}: ` : ""}
        {e.detail ?? e.message})
      </span>
      <button type="button" onClick={retry} className={`rounded border border-amber-500 px-2 text-xs ${FOCUS}`}>
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

  const noSources = sources.isSuccess && sources.data.length === 0 && eng.docs.length === 0;
  const jobsList = jobs.data ?? [];

  return (
    <main
      className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[18rem_minmax(0,1fr)_20rem] group-data-[guide=open]/shell:max-xl:pb-28"
      data-testid="scope-screen"
    >
      <aside className="flex flex-col gap-4" aria-label="Sources panel">
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
      </aside>

      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <ViewToggle view={view} onChange={changeView} />
          <span className="text-xs text-slate-600">
            Press <Keycap>{keyLabel("help")}</Keycap> for the guide and keyboard shortcuts
          </span>
        </div>
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
            <div data-testid="scope-empty" className="rounded border border-dashed border-slate-400 px-6 py-8 text-center">
              <p className="mx-auto max-w-prose text-sm text-slate-700">Manual Labor turns PDF and DOCX manuals into a reviewed knowledge base.</p>
              <p className="mb-3 mt-1 font-medium">Step 1: add documents.</p>
              <UploadButton label="Add documents" />
            </div>
          ) : eng.isLoading ? (
            <div aria-busy="true" data-testid="tree-loading" className="flex flex-col gap-1">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-12 animate-pulse rounded bg-slate-200" />
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

      <aside className="flex flex-col gap-4" aria-label="Summary and models">
        {summary ? <SplitModeControl split={split} summary={summary} view={view} onChange={changeSplit} /> : null}
        {summary ? <SelectionSummary summary={summary} processing={ungrouped.length} /> : null}
        {summary ? (
          <div className="flex gap-2" data-testid="select-controls">
            <Hint id="selectAll">
              <button type="button" onClick={selectAll} className={`flex-1 rounded border border-slate-400 bg-white px-2 py-1 text-sm hover:bg-slate-100 ${FOCUS}`}>
                Select all
              </button>
            </Hint>
            <Hint id="selectNone">
              <button
                type="button"
                onClick={selectNone}
                data-testid="clear-selection"
                className={`flex-1 rounded border px-2 py-1 text-sm ${FOCUS} ${armed ? "border-amber-500 bg-amber-50 text-amber-950" : "border-slate-400 bg-white hover:bg-slate-100"}`}
              >
                {armed ? "Press again to clear" : "Clear selection"}
              </button>
            </Hint>
          </div>
        ) : null}
        {/* while the guide is a bottom sheet, the primary action is pinned just above it so the sheet never covers it */}
        <div
          data-testid="confirm-dock"
          className="group-data-[guide=open]/shell:max-xl:fixed group-data-[guide=open]/shell:max-xl:inset-x-0 group-data-[guide=open]/shell:max-xl:bottom-[var(--guide-sheet,0px)] group-data-[guide=open]/shell:max-xl:z-20 group-data-[guide=open]/shell:max-xl:border-t group-data-[guide=open]/shell:max-xl:border-slate-300 group-data-[guide=open]/shell:max-xl:bg-white group-data-[guide=open]/shell:max-xl:px-4 group-data-[guide=open]/shell:max-xl:py-2"
        >
          <ConfirmButton
            blocks={summary?.blocks ?? 0}
            processing={processing}
            busy={confirm.isPending}
            onConfirm={() => void onConfirm()}
          />
        </div>
        <Panel error={models.error} retry={() => void models.refetch()} testid="models-error">
          {models.data ? <ModelPanel data={models.data} /> : <div aria-busy="true" className="h-24 animate-pulse rounded bg-slate-200" />}
        </Panel>
      </aside>
    </main>
  );
}
