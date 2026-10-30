import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type { DocReadiness, QueueItem, ReviewCounts } from "../api/schema";
import { keyLabel } from "../onboarding/guide";
import QueueCard from "./QueueCard";

export const ROW = 64;

interface Props {
  items: QueueItem[];
  total: number;
  pinned: QueueItem | null;
  currentId: string | null;
  docs: DocReadiness[];
  counts: ReviewCounts;
  focusTick: number;
  wantFocus: React.MutableRefObject<boolean>;
  focusBlocked?: React.MutableRefObject<boolean>;
  onSelect: (id: string) => void;
  onNearEnd: () => void;
}

export default function Queue({ items, total, pinned, currentId, docs, counts, focusTick, wantFocus, focusBlocked, onSelect, onNearEnd }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({
    count: items.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW,
    overscan: 8,
    scrollMargin: pinned ? ROW : 0,
    initialRect: { width: 320, height: 640 },
  });
  const idx = items.findIndex((i) => i.block_id === currentId);
  useEffect(() => {
    if (idx >= 0) v.scrollToIndex(idx, { align: "auto" });
    if (idx >= 0 && idx > items.length - 50) onNearEnd();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, items.length]);
  const preparing = docs.filter((d) => d.state === "pending").length;
  const empty = items.length === 0 && !pinned;
  // nothing confirmed yet: no block in scope, nothing flagged, no document still being prepared
  const unconfirmed = empty && counts.in_scope === 0 && counts.flagged_open === 0 && preparing === 0;
  const LINK = "text-blue-700 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
  return (
    <div className="flex min-h-0 flex-col border-r border-slate-300 bg-white" data-zone="queue">
      <div
        ref={scroller}
        role="listbox"
        aria-label="Review queue"
        aria-orientation="vertical"
        className="min-h-0 flex-1 overflow-auto"
        data-testid="queue"
      >
        {pinned ? (
          <QueueCard
            item={pinned}
            isCurrent={pinned.block_id === currentId}
            pinned
            pos={0}
            size={total}
            focusTick={focusTick}
            wantFocus={wantFocus}
            focusBlocked={focusBlocked}
            onSelect={onSelect}
            height={ROW}
          />
        ) : null}
        <div style={{ height: v.getTotalSize(), position: "relative" }}>
          {v.getVirtualItems().map((row) => {
            const it = items[row.index];
            return (
              <QueueCard
                key={it.block_id}
                item={it}
                isCurrent={it.block_id === currentId}
                pos={row.index + 1}
                size={total}
                focusTick={it.block_id === currentId ? focusTick : 0}
                wantFocus={wantFocus}
                focusBlocked={focusBlocked}
                onSelect={onSelect}
                height={ROW}
                offset={row.start - (pinned ? ROW : 0)}
              />
            );
          })}
        </div>
      </div>
      {unconfirmed ? (
        <div data-testid="queue-empty" data-variant="unconfirmed" className="space-y-1 p-3 text-sm">
          <p className="font-medium">Nothing to review yet</p>
          <p className="text-slate-700">
            Confirm your scope on the Scope screen (<kbd className="rounded border border-slate-300 px-1 font-mono text-xs">{keyLabel("goScope")}</kbd>, then{" "}
            <kbd className="rounded border border-slate-300 px-1 font-mono text-xs">{keyLabel("confirm")}</kbd>).
          </p>
          <Link className={LINK} to="/scope">
            Go to Scope
          </Link>
        </div>
      ) : empty ? (
        <div data-testid="queue-empty" data-variant="caught-up" className="space-y-1 p-3 text-sm">
          <p className="font-medium">All caught up</p>
          <p className="text-slate-700" data-testid="queue-empty-counts">
            {counts.approved + counts.edited} reviewed, {counts.auto_approved} auto-approved, {counts.flagged_open} flagged.
          </p>
          <p className="text-slate-700">
            {counts.flagged_open > 0
              ? `Next: hand the ${counts.flagged_open} flagged block${counts.flagged_open === 1 ? "" : "s"} to the Agent, or export with an override.`
              : "Next: export the knowledge base."}
          </p>
          <p className="flex gap-3">
            {counts.flagged_open > 0 ? (
              <Link className={LINK} to="/agent">
                Go to Agent
              </Link>
            ) : null}
            <Link className={LINK} to="/export">
              Go to Export
            </Link>
          </p>
        </div>
      ) : null}
      {preparing > 0 ? (
        <p data-testid="queue-footer" className="border-t border-slate-200 px-2 py-1 text-xs text-slate-700">
          {preparing} document{preparing === 1 ? "" : "s"} still preparing; their blocks appear here when ready. You can start now.
        </p>
      ) : null}
    </div>
  );
}
