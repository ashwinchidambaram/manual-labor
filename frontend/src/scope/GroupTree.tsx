import { useEffect, useMemo, useRef } from "react";
import { useBlockIndexData } from "../api/queries";
import type { DocGroups, GroupCoverage, View } from "../api/schema";
import { useHotkeys } from "../hooks/useHotkeys";
import { MISMATCH, docMismatchDetail, docReconcileText, reconcileDoc, type DocReconcile } from "../onboarding/reconcile";
import { lowCohesion, rowFraction, type CheckState, type Row } from "./derive";
import GroupRow from "./GroupRow";

export interface GroupTreeProps {
  docs: DocGroups[];
  rows: Row[];
  view: View;
  coverage: Map<string, GroupCoverage>;
  checks: ReadonlyMap<string, CheckState>;
  expanded: ReadonlySet<string>;
  cursor: string | null;
  stale: boolean;
  filenames: Map<string, string>;
  ungrouped: string[];
  onCursor: (id: string | null) => void;
  onToggle: (id: string) => void;
  onSelectOnly: (id: string) => void;
  onSelectDoc: (id: string) => void;
  /** toggle expansion (chevron click) */
  onExpand: (id: string) => void;
  onExpandKey: (id: string) => void;
  onCollapseKey: (id: string) => void;
  onMove: (delta: 1 | -1) => void;
  onEdge: (which: "first" | "last") => void;
}

/** role=tree (structure) or role=listbox (topics) with a roving tabindex cursor. */
export default function GroupTree(p: GroupTreeProps) {
  const zone = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);
  const structure = p.view === "structure";

  // Keep DOM focus on the cursor row while the tree owns focus (design 1.3).
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const z = zone.current;
    if (!z || !p.cursor) return;
    if (z.contains(document.activeElement) && document.activeElement?.getAttribute("data-group-id") !== p.cursor)
      z.querySelector<HTMLElement>(`[data-group-id="${CSS.escape(p.cursor)}"]`)?.focus();
  }, [p.cursor, p.rows]);

  // A view toggle or split change swaps the rows under a focused row and the browser drops focus to <body>.
  // Remember (during render, before the DOM changes) which row had focus; afterwards focus the same group if it
  // still exists, else the first row. Never steals focus that was elsewhere.
  const owned = useRef<string | null>(null);
  const active = typeof document === "undefined" ? null : document.activeElement;
  if (zone.current?.contains(active)) owned.current = (active as HTMLElement).getAttribute("data-group-id") ?? "";
  else if (active && active !== document.body) owned.current = null;
  useEffect(() => {
    const drop = (): void => {
      owned.current = null; // a pointer press elsewhere means focus was moved on purpose
    };
    document.addEventListener("mousedown", drop, true);
    return () => document.removeEventListener("mousedown", drop, true);
  }, []);
  const { onCursor } = p;
  useEffect(() => {
    const z = zone.current;
    const was = owned.current;
    if (!z || was === null) return;
    const a = document.activeElement;
    if (a && a !== document.body) return;
    const same = was ? z.querySelector<HTMLElement>(`[data-group-id="${CSS.escape(was)}"]`) : null;
    const target = same ?? z.querySelector<HTMLElement>("[data-group-id]");
    if (!target) return;
    target.focus();
    const id = target.getAttribute("data-group-id");
    if (id) onCursor(id);
  });

  const cur = p.cursor;
  useHotkeys({
    moveDown: () => p.onMove(1),
    moveUp: () => p.onMove(-1),
    first: () => p.onEdge("first"),
    last: () => p.onEdge("last"),
    toggleRow: () => cur && p.onToggle(cur),
    selectOnly: () => cur && p.onSelectOnly(cur),
    selectWholeDoc: () => cur && p.onSelectDoc(cur),
    ...(structure
      ? { expand: () => cur && p.onExpandKey(cur), collapse: () => cur && p.onCollapseKey(cur) }
      : {}),
  });

  // "nothing dropped": per document, parsed blocks reconcile against the groups (design 12 section 2.5)
  const blockIndex = useBlockIndexData();
  const reconciled = useMemo(() => {
    const m = new Map<string, DocReconcile>();
    const byDoc = new Map((blockIndex.data ?? []).map((d) => [d.doc_id, d.blocks]));
    for (const d of p.docs) {
      const blocks = byDoc.get(d.doc_id);
      if (blocks) m.set(d.doc_id, reconcileDoc(blocks, d));
    }
    return m;
  }, [blockIndex.data, p.docs]);
  const paramsOf = new Map(p.docs.map((d) => [d.doc_id, d.groups.params]));
  // titles that appear twice in one document of this view get their page range beside them (design 13 F12)
  const dupes = useMemo(() => {
    const seen = new Map<string, number>();
    for (const r of p.rows) {
      const k = `${r.docId}\u0000${r.group.title}`;
      seen.set(k, (seen.get(k) ?? 0) + 1);
    }
    return seen;
  }, [p.rows]);
  const noticeDocs = new Map(p.docs.map((d) => [d.doc_id, d]));
  const out: JSX.Element[] = [];
  let lastDoc = "";
  for (const r of p.rows) {
    if (r.docId !== lastDoc) {
      lastDoc = r.docId;
      const d = noticeDocs.get(r.docId);
      const rec = reconciled.get(r.docId);
      out.push(
        <div
          key={`doc-${r.docId}`}
          role="presentation"
          data-doc={r.docId}
          data-testid="doc-heading"
          className="sticky top-0 z-10 flex flex-col gap-0.5 border-b border-line-soft bg-sunk px-4 py-2.5 [&:not(:first-child)]:border-t [&:not(:first-child)]:border-t-line"
        >
          <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-base font-semibold text-ink">{p.filenames.get(r.docId) ?? r.docId}</span>
          {d && d.groups.learning_snapshot !== "baseline" ? (
            <span className="text-xs text-muted">
              learned grouping: {d.groups.learning_snapshot}
            </span>
          ) : null}
          {d && d.groups.topic_status === "failed" ? (
            <span role="note" className="text-xs text-needs-ink" data-testid="topics-failed">
              Topics unavailable: {d.groups.topic_error ?? "unknown error"}. Structure view still works.
            </span>
          ) : null}
          </span>
          {rec ? (
            rec.ok ? (
              <span className="text-xs tabular-nums text-muted [&_b]:font-semibold [&_b]:text-ink" data-testid="doc-reconcile">
                {docReconcileText(rec)}
              </span>
            ) : (
              <span role="note" className="text-xs font-medium text-fail" data-testid="doc-reconcile-mismatch">
                <span aria-hidden="true">✕ </span>
                {MISMATCH(docMismatchDetail(rec))}
              </span>
            )
          ) : null}
        </div>,
      );
    }
    const c = p.coverage.get(r.group.id);
    const params = paramsOf.get(r.docId);
    out.push(
      <GroupRow
        key={r.group.id}
        group={r.group}
        view={p.view}
        depth={r.depth}
        posInSet={r.posInSet}
        setSize={r.setSize}
        hasChildren={r.hasChildren}
        childCount={r.childCount}
        expanded={p.expanded.has(r.group.id)}
        check={p.checks.get(r.group.id) ?? "unchecked"}
        fraction={rowFraction(c, p.view)}
        stale={p.stale}
        low={params ? lowCohesion(r.group, params) : false}
        duplicate={(dupes.get(`${r.docId}\u0000${r.group.title}`) ?? 0) > 1}
        cursor={r.group.id === p.cursor}
        onToggle={p.onToggle}
        onExpand={p.onExpand}
        onCursor={p.onCursor}
      />,
    );
  }
  for (const slug of p.ungrouped)
    out.push(
      <div key={`pending-${slug}`} data-testid="grouping-placeholder" className="border-b border-line-soft bg-raised px-4 py-3 text-sm text-muted">
        {p.filenames.get(slug) ?? slug}: grouping...
      </div>,
    );

  return (
    <div
      ref={zone}
      data-zone="tree"
      role={structure ? "tree" : "listbox"}
      aria-label={structure ? "Document structure" : "Suggested topics"}
      aria-multiselectable="true"
      data-testid="group-tree"
      className="overflow-auto rounded-xl border border-line bg-raised"
    >
      {out}
    </div>
  );
}
