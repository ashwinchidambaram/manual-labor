import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type { DocReadiness, ExportStatus, QueueItem, ReviewCounts } from "../api/schema";
import { Keycap } from "../onboarding/Copy";
import { keyLabel } from "../onboarding/guide";
import { blockingFlagsOf, scopeTerms, toReviewOf } from "../shell/scopeTerms";
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
  /** scoring still queued or running, in words (from the active jobs); null when no pipeline job is active */
  scoring?: string | null;
  /** the active pipeline jobs only read manuals (an upload): nothing they do puts a block in this list */
  reading?: boolean;
  /** a job re-scores this document now (not a reading job): only then is a stale document "re-scoring" */
  rescoring?: (doc: string) => boolean;
  /** a queued or running job will prepare this document */
  busyFor?: (doc: string) => boolean;
}

const NO_TITLES: ReadonlyMap<string, string> = new Map();
const NOBODY = (): boolean => false;

export default function Queue({ items, total, pinned, currentId, docs, counts, focusTick, wantFocus, focusBlocked, onSelect, onNearEnd, threshold, gate, docTitles = NO_TITLES, scoring = null, busyFor = NOBODY, reading = false, rescoring = NOBODY }: Props) {
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
  const pendingDocs = docs.filter((d) => d.state === "pending");
  const preparing = pendingDocs.length;
  const scoringN = pendingDocs.filter((d) => busyFor(d.doc_id)).length;
  const unscoredN = preparing - scoringN;
  const empty = items.length === 0 && !pinned;
  // Work is only claimed while a job is queued or running (CLAUDE.md "Claiming work is happening"): with one, the
  // empty list is "scoring in progress"; without one, a pending document is "not scored yet", never "preparing".
  const busy = scoring !== null;
  // nothing confirmed yet: no block in scope, nothing flagged, no document still being prepared
  const unconfirmed = empty && !busy && counts.in_scope === 0 && counts.flagged_open === 0 && preparing === 0;
  const LINK = "font-medium text-act-ink underline underline-offset-2 hover:text-act-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";
  const at = idx >= 0 ? idx + 1 : null;
  // the folded queue (low, narrow window) still names the current block, as its card would
  const cur = idx >= 0 ? items[idx] : pinned && pinned.block_id === currentId ? pinned : null;
  const curTitle = cur ? cardTitle(cur.section_title, docTitles.get(cur.doc_id), cur.page, cur.type) : null;
  return (
    <div className="group/queue flex min-h-0 flex-col border-b border-line bg-paper wide:h-full wide:border-b-0 wide:border-r" data-zone="queue">
      {/* On a low or short, narrow window (design 13 section 9.3) the open card folds away and this line stands for it:
          Up and Down still browse, and the focus ring the hidden card holds is drawn here instead. */}
      <p className="flex shrink-0 items-center justify-between gap-2 border-b border-line-soft px-4 py-2 text-xs text-muted low-narrow:group-focus-within/queue:bg-act-wash low-narrow:group-focus-within/queue:shadow-[inset_3px_0_0_0_var(--act)] low-narrow:group-has-[:focus-visible]/queue:ring-2 low-narrow:group-has-[:focus-visible]/queue:ring-inset low-narrow:group-has-[:focus-visible]/queue:ring-focus">
        <span className="min-w-0 truncate">
          {at !== null ? (
            <>
              Block <span className="font-semibold tabular-nums text-ink">{at}</span> of <span className="tabular-nums">{total}</span> in this list
              {curTitle ? <span className="hidden font-semibold text-ink low-narrow:inline"> · {curTitle}</span> : null}
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
        className="h-[6.25rem] min-h-0 overflow-auto low-narrow:sr-only wide:h-auto wide:flex-1"
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
            rescoring={rescoring(pinned.doc_id)}
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
                rescoring={rescoring(it.doc_id)}
              />
            );
          })}
        </div>
      </div>
      {empty && busy ? (
        <div data-testid="queue-empty" data-variant={reading ? "reading" : "scoring"} className="space-y-1.5 px-4 py-5 text-sm">
          <p className="text-base font-semibold text-ink">{reading ? "Reading in progress" : "Scoring in progress"}</p>
          <p className="tabular-nums text-ink" data-testid="queue-scoring-count">
            {scoring}
          </p>
          <p className="text-muted">
            {reading
              ? "Reading puts no block in this list: blocks come here after scoring. Confirm your scope on the Scope screen once reading finishes. Nothing is waiting for you yet."
              : "Blocks come here as each document finishes scoring. Nothing is waiting for you yet."}
          </p>
        </div>
      ) : empty && unscoredN > 0 && !unconfirmed ? (
        <div data-testid="queue-empty" data-variant="not-scored" className="space-y-1.5 px-4 py-5 text-sm">
          <p className="text-base font-semibold text-ink">
            {unscoredN} document{unscoredN === 1 ? " is" : "s are"} not scored yet
          </p>
          <p className="text-muted">Their blocks come here after scoring. Start it from the Scope screen.</p>
          <p className="flex gap-3">
            <Link className={LINK} to="/scope">
              Go to Scope
            </Link>
            {counts.flagged_open > 0 ? (
              <Link className={LINK} to="/agent">
                Go to Agent
              </Link>
            ) : null}
          </p>
        </div>
      ) : unconfirmed ? (
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
          {[
            scoringN > 0
              ? reading
                ? `${scoringN} document${scoringN === 1 ? "" : "s"} being read; their blocks appear here after scoring.`
                : `${scoringN} document${scoringN === 1 ? "" : "s"} still being scored; their blocks appear here when ready.${empty ? "" : " You can start now."}`
              : "",
            unscoredN > 0 ? `${unscoredN} document${unscoredN === 1 ? "" : "s"} not scored yet; their blocks appear here after scoring.` : "",
          ]
            .filter(Boolean)
            .join(" ")}
        </p>
      ) : null}
    </div>
  );
}

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

/** The empty queue: what was done, and the next step only when it is really open (review M12 #14). */
function EmptyNext({ counts, gate, link }: { counts: ReviewCounts; gate: ExportStatus | undefined; link: string }) {
  // the gate's partition (design 11 section 17): an overridden block does not wait for review, a covered flag does not block
  const waiting = gate ? toReviewOf(gate) : counts.queued;
  // blocks held by a flag, not flags: a block with two flags is one block to hand over
  const flagged = gate ? (gate.flag_blockers ? new Set(gate.flag_blockers.map((f) => f.block_id)).size : blockingFlagsOf(gate)) : counts.flagged_open;
  const overridden = scopeTerms(gate)?.overridden ?? 0;
  const open = !!gate && (gate.blockers ?? []).length === 0;
  const next = !gate
    ? null
    : open
      ? `Next: export the knowledge base.${overridden > 0 ? ` ${plural(overridden, "overridden block")} will go out unreviewed, as recorded.` : ""}`
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
