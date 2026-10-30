import { memo } from "react";
import type { Group, View } from "../api/schema";
import Hint from "../onboarding/Hint";
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
  /** another row of this document has the same title: show the pages beside it so the two can be told apart */
  duplicate?: boolean;
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
      style={{ paddingLeft: `${1 + (p.depth - 1) * 1.25}rem` }}
      className="flex min-h-[3.25rem] cursor-pointer items-center gap-3 border-b border-line-soft bg-raised py-1.5 pr-4 transition-colors duration-150 ease-out-quart last:border-b-0 hover:bg-sunk focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus"
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
            className="grid h-6 w-5 shrink-0 place-items-center text-muted"
          >
            <span aria-hidden="true" className={`inline-block transition-transform duration-150 ease-out-quart ${p.expanded ? "rotate-90" : ""}`}>
              ▸
            </span>
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
        className={`grid h-[1.125rem] w-[1.125rem] shrink-0 place-items-center rounded-[5px] border-[1.5px] text-[0.7rem] font-bold leading-none ${
          p.check === "unchecked" ? "border-line-strong bg-raised" : "border-ink bg-ink text-raised"
        }`}
      >
        {p.check === "checked" ? "✓" : p.check === "mixed" ? "–" : ""}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-baseline gap-2">
          <span id={titleId} className="min-w-0 truncate text-base font-medium text-ink" title={title}>
            {g.is_unassigned ? "Unassigned blocks" : title}
          </span>
          {p.duplicate && !g.is_unassigned && pages(g) ? <span className="shrink-0 text-xs tabular-nums text-muted">{pages(g)}</span> : null}
          {g.is_unassigned ? (
            <span className="shrink-0 rounded-full bg-sunk px-2 py-px text-2xs font-semibold text-muted ring-1 ring-inset ring-line">Catch-all</span>
          ) : null}
          {p.low ? (
            <Hint id="cohesion">
              <span
                className="shrink-0 rounded-full px-2 py-px text-2xs font-semibold text-needs-ink ring-1 ring-inset ring-needs-line"
                data-testid="low-cohesion"
                aria-label={`Mixed subjects, cohesion ${g.cohesion?.toFixed(2)}`}
              >
                Mixed subjects
              </span>
            </Hint>
          ) : null}
        </div>
        <div className="truncate text-xs text-muted" data-testid="row-meta">
          {meta.join(" · ")}
        </div>
      </div>
      <Hint id="coverage">
      <span
        data-testid="coverage-chip"
        data-stale={p.stale ? "true" : "false"}
        aria-label={
          p.fraction == null ? "coverage not available" : `${Math.round(p.fraction * 100)} percent of this ${topic ? "topic" : "section"} is in your selection`
        }
        className={`shrink-0 text-xs tabular-nums text-muted transition-opacity duration-150 ${p.stale ? "opacity-50" : ""}`}
      >
        {pctLabel} selected
      </span>
      </Hint>
    </div>
  );
}

export default memo(GroupRowImpl);
