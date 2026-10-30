import { memo, useLayoutEffect, useMemo, useRef } from "react";
import type { QueueItem } from "../api/schema";
import Hint from "../onboarding/Hint";
import { signalHint } from "../onboarding/hints";
import { cardTitle, FOCUS, SCORE_TITLE, STALE_NAME, STATUS_LABEL, scoreText } from "./labels";
import { reasonChips, reasonsFromQueueItem } from "./reasons";

interface Props {
  item: QueueItem;
  isCurrent: boolean;
  /** position for aria-posinset / aria-setsize */
  pos?: number;
  size?: number;
  /** current card only: a changed value means "take focus now" */
  focusTick: number;
  wantFocus: React.MutableRefObject<boolean>;
  focusBlocked?: React.MutableRefObject<boolean>;
  onSelect: (id: string) => void;
  /** row height in px */
  height: number;
  /** translateY in px for an absolutely positioned (virtualised) row; undefined for a static row */
  offset?: number;
  pinned?: boolean;
  criticalReasons?: number;
  /** the auto-approve threshold the score is judged against */
  threshold: number | null;
  /** the document's display name, the title fallback when no heading precedes the block */
  docTitle?: string | null;
}

/**
 * A queue card (design 13 section 2.8.3): a human title (section heading, else document, else page), the first line of
 * the text in the manual's typeface, the reasons with the specific word named, then the id and score as support.
 */
function QueueCardImpl({ item, isCurrent, pos, size, focusTick, wantFocus, focusBlocked, onSelect, height, offset, pinned, criticalReasons, threshold, docTitle }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  // primitives in, stable style out: the object identity must not defeat memo()
  const style = useMemo<React.CSSProperties>(
    () => (offset === undefined ? { height } : { position: "absolute", top: 0, left: 0, width: "100%", height, transform: `translateY(${offset}px)` }),
    [height, offset],
  );
  useLayoutEffect(() => {
    // a request made while an editor/dialog is open stays pending: it must not steal focus from it
    if (isCurrent && wantFocus.current && !focusBlocked?.current && !document.querySelector("[aria-modal='true']") && ref.current) {
      wantFocus.current = false;
      // the queue scrolls its own list to the card (Queue's scrollToIndex); below `wide` the page is one document and a
      // plain focus() would scroll it back to the queue after every decision
      ref.current.focus({ preventScroll: true });
    }
  }, [isCurrent, focusTick, wantFocus, focusBlocked]);
  // A card that unmounts while it holds focus (virtualised away, or a pinned copy handing over to its list card) asks
  // the current card to take focus on its next render, so focus never falls to <body>. Unmount only.
  useLayoutEffect(() => {
    const el = ref.current;
    return () => {
      if (el && el.contains(document.activeElement)) wantFocus.current = true;
    };
  }, [wantFocus]);
  const why = reasonsFromQueueItem(item.reasons ?? [], item.has_numeric_spec, criticalReasons);
  const chips = reasonChips({ why, hasNumeric: item.has_numeric_spec });
  const stale = (item.reasons ?? []).includes(STALE_NAME);
  const title = cardTitle(item.section_title, docTitle, item.page, item.type);
  const weak = item.weakest_word ?? null;
  return (
    <div
      ref={ref}
      role="option"
      tabIndex={isCurrent ? 0 : -1}
      aria-selected={isCurrent}
      aria-current={isCurrent ? "true" : undefined}
      aria-posinset={pos}
      aria-setsize={size}
      data-testid={`card-${item.block_id}`}
      data-pinned={pinned ? "true" : undefined}
      onClick={() => onSelect(item.block_id)}
      style={style}
      className={`flex cursor-pointer flex-col justify-center gap-[3px] overflow-hidden border-b border-line-soft px-4 transition-colors duration-150 ease-out-quart focus-visible:ring-inset ${FOCUS} ${
        isCurrent ? "bg-act-wash shadow-[inset_3px_0_0_0_var(--act),inset_0_0_0_1px_var(--act-line)]" : "bg-paper hover:bg-sunk"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-sm font-semibold text-ink">{title}</span>
        <span className="shrink-0 text-2xs tabular-nums text-muted">
          p.{item.page} · {item.type}
        </span>
      </div>
      <p className="manual-text truncate text-sm text-ink">{item.excerpt || " "}</p>
      <p className="truncate text-xs text-needs-ink">
        {item.status !== "queued" ? <span className="rounded font-semibold text-done-ink">{STATUS_LABEL[item.status] ?? item.status}</span> : null}
        {stale || chips.status.length ? <span className="rounded font-semibold">{STALE_NAME}</span> : null}
        {item.stale_doc ? <span className="rounded font-semibold">re-scoring</span> : null}
        {chips.reasons.map((c, i) => (
          <span key={c.name}>
            {i > 0 || item.status !== "queued" || stale || chips.status.length || item.stale_doc ? (
              <span aria-hidden="true" className="mx-1 text-muted">
                ·
              </span>
            ) : null}
            <Hint id="reasonChip" text={signalHint(c.name) ?? undefined}>
              <span className={`rounded ${c.tone === "rule" ? "text-ink" : ""}`}>{c.text}</span>
            </Hint>
            {c.name === "ocr_min" && weak ? <span className="manual-text text-ink"> “{weak}”</span> : null}
          </span>
        ))}
        {chips.overflow.length ? (
          <span title={chips.overflow.join(", ")} className="ml-1 rounded text-muted">
            +{chips.overflow.length}
          </span>
        ) : null}
      </p>
      <div className="flex items-baseline justify-between gap-2 text-2xs text-muted">
        <span className="truncate font-mono">{item.block_id}</span>
        <span className="shrink-0 tabular-nums" data-testid="queue-score" title={SCORE_TITLE}>
          {scoreText(item.confidence, threshold)}
        </span>
      </div>
    </div>
  );
}

export default memo(QueueCardImpl);
