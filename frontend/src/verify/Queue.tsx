import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type { DocReadiness, QueueItem, ReviewCounts } from "../api/schema";
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
  onSelect: (id: string) => void;
  onNearEnd: () => void;
}

export default function Queue({ items, total, pinned, currentId, docs, counts, focusTick, wantFocus, onSelect, onNearEnd }: Props) {
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
                onSelect={onSelect}
                height={ROW}
                offset={row.start - (pinned ? ROW : 0)}
              />
            );
          })}
        </div>
      </div>
      {empty ? (
        <div data-testid="queue-empty" className="p-3 text-sm">
          <p className="font-medium">All caught up</p>
          <p className="mt-1 flex gap-3">
            {counts.flagged_open > 0 ? (
              <Link className="text-blue-700 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600" to="/agent">
                Go to Agent
              </Link>
            ) : null}
            <Link className="text-blue-700 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600" to="/export">
              Go to Export
            </Link>
          </p>
        </div>
      ) : null}
      {preparing > 0 ? (
        <p data-testid="queue-footer" className="border-t border-slate-200 px-2 py-1 text-xs text-slate-700">
          {preparing} document{preparing === 1 ? "" : "s"} still preparing; their blocks appear here when ready
        </p>
      ) : null}
    </div>
  );
}
