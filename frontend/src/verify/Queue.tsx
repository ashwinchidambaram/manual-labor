import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type { DocReadiness, ExportStatus, QueueItem, ReviewCounts } from "../api/schema";
import { Keycap } from "../onboarding/Copy";
import { keyLabel } from "../onboarding/guide";
import { cardTitle } from "./labels";
import QueueCard from "./QueueCard";

export const ROW = 100;
/** rows always rendered at the head of the list */
const HEAD = 8;

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
  threshold: number | null;
  /** the export gate; "Next: export" is only offered when it is open */
  gate?: ExportStatus;
  /** document slug -> file name, the card title fallback */
  docTitles?: ReadonlyMap<string, string>;
}

const NO_TITLES: ReadonlyMap<string, string> = new Map();

export default function Queue({ items, total, pinned, currentId, docs, counts, focusTick, wantFocus, focusBlocked, onSelect, onNearEnd, threshold, gate, docTitles = NO_TITLES }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const idx = items.findIndex((i) => i.block_id === currentId);
  const v = useVirtualizer({
    count: items.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW,
    // Cards are 100px tall: a generous window means a jump or a fast wheel lands on rendered rows. The head of the list is
    // always rendered too, so a sort change shows its first cards at once, wherever the current block is.
    overscan: 30,
    // The current card is always rendered too: when a refetch inserts rows ahead of it, its row moves instead of
    // unmounting, so it keeps keyboard focus.
    rangeExtractor: (r) => {
      const head = Array.from({ length: Math.min(HEAD, r.count) }, (_, i) => i);
      const cur = idx >= 0 && idx < r.count ? [idx] : [];
      return [...new Set([...head, ...cur, ...defaultRangeExtractor(r)])].sort((a, b) => a - b);
    },
    scrollMargin: pinned ? ROW : 0,
    initialRect: { width: 320, height: 640 },
  });
  useEffect(() => {
    if (idx >= 0) v.scrollToIndex(idx, { align: "auto" });
    if (idx >= 0 && idx > items.length - 50) onNearEnd();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, items.length]);
  const preparing = docs.filter((d) => d.state === "pending").length;
  const empty = items.length === 0 && !pinned;
  // nothing confirmed yet: no block in scope, nothing flagged, no document still being prepared
  const unconfirmed = empty && counts.in_scope === 0 && counts.flagged_open === 0 && preparing === 0;
  const LINK = "font-medium text-act-ink underline underline-offset-2 hover:text-act-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";
  const at = idx >= 0 ? idx + 1 : null;
  // the folded queue (short, narrow window) still names the current block, as its card would
  const cur = idx >= 0 ? items[idx] : pinned && pinned.block_id === currentId ? pinned : null;
  const curTitle = cur ? cardTitle(cur.section_title, docTitles.get(cur.doc_id), cur.page, cur.type) : null;
  return (
    <div className="group/queue flex min-h-0 flex-col border-b border-line bg-paper wide:h-full wide:border-b-0 wide:border-r" data-zone="queue">
      {/* On a short, narrow window the open card folds away and this line stands for it: Up and Down still browse, and the
          focus ring the hidden card holds is drawn here instead. */}
      <p className="flex shrink-0 items-center justify-between gap-2 border-b border-line-soft px-4 py-2 text-xs text-muted short-narrow:group-focus-within/queue:bg-act-wash short-narrow:group-focus-within/queue:shadow-[inset_3px_0_0_0_var(--act)] short-narrow:group-has-[:focus-visible]/queue:ring-2 short-narrow:group-has-[:focus-visible]/queue:ring-inset short-narrow:group-has-[:focus-visible]/queue:ring-focus">
        <span className="min-w-0 truncate">
          {at !== null ? (
            <>
              Block <span className="font-semibold tabular-nums text-ink">{at}</span> of <span className="tabular-nums">{total}</span> in this list
              {curTitle ? <span className="hidden font-semibold text-ink short-narrow:inline"> · {curTitle}</span> : null}
            </>
          ) : (
            <>
              <span className="tabular-nums">{total}</span> in this list
            </>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-1" aria-hidden="true">
          <Keycap>{keyLabel("vBrowsePrev")}</Keycap>
          <Keycap>{keyLabel("vBrowseNext")}</Keycap> browse
        </span>
      </p>
      <div
        ref={scroller}
        role="listbox"
        aria-label="Review queue"
        aria-orientation="vertical"
        className="h-[6.25rem] min-h-0 overflow-auto short-narrow:sr-only wide:h-auto wide:flex-1"
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
            threshold={threshold}
            docTitle={docTitles.get(pinned.doc_id) ?? null}
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
                threshold={threshold}
                docTitle={docTitles.get(it.doc_id) ?? null}
              />
            );
          })}
        </div>
      </div>
      {unconfirmed ? (
        <div data-testid="queue-empty" data-variant="unconfirmed" className="space-y-1.5 px-4 py-5 text-sm">
          <p className="text-base font-semibold text-ink">Nothing to review yet</p>
          <p className="text-muted">
            Confirm your scope on the Scope screen (<Keycap>{keyLabel("goScope")}</Keycap>, then <Keycap>{keyLabel("confirm")}</Keycap>).
          </p>
          <Link className={LINK} to="/scope">
            Go to Scope
          </Link>
        </div>
      ) : empty ? (
        <EmptyNext counts={counts} gate={gate} link={LINK} />
      ) : null}
      {preparing > 0 ? (
        <p data-testid="queue-footer" className="shrink-0 border-t border-line-soft bg-needs-wash px-4 py-2 text-xs text-needs-ink">
          {preparing} document{preparing === 1 ? "" : "s"} still preparing; their blocks appear here when ready. You can start now.
        </p>
      ) : null}
    </div>
  );
}

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

/** The empty queue: what was done, and the next step only when it is really open (review M12 #14). */
function EmptyNext({ counts, gate, link }: { counts: ReviewCounts; gate: ExportStatus | undefined; link: string }) {
  const waiting = gate?.queued ?? counts.queued;
  const flagged = gate?.open_flags ?? counts.flagged_open;
  const open = !!gate && (gate.blockers ?? []).length === 0;
  const next = !gate
    ? null
    : open
      ? "Next: export the knowledge base."
      : flagged > 0 && waiting === 0
        ? `Next: hand the ${plural(flagged, "flagged block")} to the Agent, or export with an override.`
        : `Export is still locked: ${plural(waiting, "block")} in scope still ${waiting === 1 ? "needs" : "need"} review and ${waiting === 1 ? "is" : "are"} not in this list.${
            flagged > 0 ? ` ${plural(flagged, "open flag")} also ${flagged === 1 ? "blocks" : "block"} it.` : ""
          } Check the sort and document filter, or see the Export screen for the list.`;
  return (
    <div data-testid="queue-empty" data-variant="caught-up" className="space-y-1.5 px-4 py-5 text-sm">
      <p className="flex items-center gap-2 text-base font-semibold text-ink">
        {waiting > 0 ? null : (
          <span aria-hidden="true" className="grid h-6 w-6 place-items-center rounded-full bg-done-wash text-xs font-bold text-done-ink">
            ✓
          </span>
        )}
        {waiting > 0 ? "Nothing in this list" : "All caught up"}
      </p>
      <p className="text-muted" data-testid="queue-empty-counts">
        {counts.approved + counts.edited} reviewed, {counts.auto_approved} auto-approved, {counts.flagged_open} flagged.
      </p>
      {next ? (
        <p className="text-ink" data-testid="queue-next">
          {next}
        </p>
      ) : null}
      <p className="flex gap-3">
        {flagged > 0 || counts.flagged_open > 0 ? (
          <Link className={link} to="/agent">
            Go to Agent
          </Link>
        ) : null}
        <Link className={link} to="/export">
          Go to Export
        </Link>
      </p>
    </div>
  );
}
