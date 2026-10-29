import { memo } from "react";
import type { Group, View } from "../api/schema";
import { coverageLabel, type CheckState } from "./derive";

export interface GroupRowProps {
  group: Group;
  view: View;
  depth: number;
  posInSet: number;
  setSize: number;
  hasChildren: boolean;
  childCount: number;
  expanded: boolean;
  check: CheckState;
  fraction: number | null;
  stale: boolean;
  low: boolean;
  cursor: boolean;
  onToggle: (id: string) => void;
  onExpand: (id: string) => void;
  onCursor: (id: string) => void;
}

function pages(g: Group): string {
  if (!g.page_ranges.length) return "";
  const parts = g.page_ranges.map((r) => (r.start === r.end ? `${r.start}` : `${r.start}-${r.end}`));
  return `${g.page_ranges.length === 1 && g.page_ranges[0].start === g.page_ranges[0].end ? "p." : "pp."} ${parts.join(", ")}`;
}

function plural(n: number, w: string): string {
  return `${n} ${w}${n === 1 ? "" : "s"}`;
}

function GroupRowImpl(p: GroupRowProps) {
  const g = p.group;
  const topic = p.view === "topic";
  const title = `${!topic && g.section_number ? `${g.section_number} ` : ""}${g.title}`.trim();
  const sections = topic ? (g.section_ids ?? []).length : p.childCount;
  const meta = [
    pages(g),
    plural(g.block_count, "block"),
    plural(g.figure_count, "figure"),
    sections > 0 || topic ? plural(sections, "section") : "",
    topic && g.cohesion != null ? `cohesion ${g.cohesion.toFixed(2)}` : "",
  ].filter(Boolean);
  const pct = coverageLabel(p.fraction);
  const pctLabel = p.fraction == null ? "n/a" : pct === "none" ? "0%" : pct === "all" ? "100%" : pct;
  const titleId = `row-title-${g.id}`;
  const selected = p.check === "checked";
  return (
    <div
      role={topic ? "option" : "treeitem"}
      aria-labelledby={titleId}
      aria-selected={selected}
      aria-level={topic ? undefined : p.depth}
      aria-setsize={p.setSize}
      aria-posinset={p.posInSet}
      aria-expanded={!topic && p.hasChildren ? p.expanded : undefined}
      tabIndex={p.cursor ? 0 : -1}
      data-testid="row"
      data-group-id={g.id}
      data-check={p.check}
      onFocus={(e) => {
        if (e.target === e.currentTarget) p.onCursor(g.id);
      }}
      onClick={() => {
        p.onCursor(g.id);
        p.onToggle(g.id);
      }}
      style={{ paddingLeft: `${0.5 + (p.depth - 1) * 1.25}rem` }}
      className={`flex min-h-[3rem] cursor-pointer items-center gap-2 border-b border-slate-200 py-1 pr-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600 ${
        selected ? "bg-blue-50" : "bg-white hover:bg-slate-50"
      }`}
    >
      {!topic ? (
        p.hasChildren ? (
          <button
            type="button"
            tabIndex={-1}
            aria-label={p.expanded ? "Collapse section" : "Expand section"}
            onClick={(e) => {
              e.stopPropagation();
              p.onExpand(g.id);
            }}
            className="w-5 shrink-0 text-slate-600"
          >
            {p.expanded ? "v" : ">"}
          </button>
        ) : (
          <span className="w-5 shrink-0" />
        )
      ) : null}
      <span
        role="checkbox"
        aria-checked={p.check === "mixed" ? "mixed" : selected}
        aria-label={`Select ${g.title}`}
        data-testid="row-check"
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border text-[10px] leading-none ${
          p.check === "unchecked" ? "border-slate-500 bg-white" : "border-blue-700 bg-blue-700 text-white"
        }`}
      >
        {p.check === "checked" ? "x" : p.check === "mixed" ? "-" : ""}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span id={titleId} className="truncate text-sm font-medium" title={title}>
            {g.is_unassigned ? "Unassigned blocks" : title}
          </span>
          {g.is_unassigned ? (
            <span className="shrink-0 rounded bg-slate-200 px-1.5 text-xs text-slate-800">Catch-all</span>
          ) : null}
          {p.low ? (
            <span
              className="shrink-0 rounded bg-amber-200 px-1.5 text-xs font-medium text-amber-950"
              data-testid="low-cohesion"
              aria-label={`Low cohesion ${g.cohesion?.toFixed(2)}`}
            >
              Low cohesion
            </span>
          ) : null}
        </div>
        <div className="truncate text-xs text-slate-600" data-testid="row-meta">
          {meta.join(" · ")}
        </div>
      </div>
      <span
        data-testid="coverage-chip"
        data-stale={p.stale ? "true" : "false"}
        aria-label={
          p.fraction == null ? "coverage not available" : `${Math.round(p.fraction * 100)} percent of this ${topic ? "topic" : "section"} is in your selection`
        }
        className={`shrink-0 rounded border border-slate-300 px-1.5 text-xs tabular-nums ${p.stale ? "opacity-50" : ""}`}
      >
        {pctLabel} selected
      </span>
    </div>
  );
}

export default memo(GroupRowImpl);
