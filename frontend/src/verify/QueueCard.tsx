import { memo, useLayoutEffect, useMemo, useRef } from "react";
import type { QueueItem } from "../api/schema";
import Hint from "../onboarding/Hint";
import { signalHint } from "../onboarding/hints";
import { FOCUS, STALE_NAME, STATUS_LABEL } from "./labels";
import { reasonChips, reasonsFromQueueItem } from "./reasons";

const TONE: Record<string, string> = {
  critical: "bg-red-100 text-red-900",
  soft: "bg-slate-200 text-slate-800",
  rule: "bg-violet-100 text-violet-900",
  status: "bg-amber-100 text-amber-950",
};

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
}

function QueueCardImpl({ item, isCurrent, pos, size, focusTick, wantFocus, focusBlocked, onSelect, height, offset, pinned, criticalReasons }: Props) {
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
      ref.current.focus();
    }
  }, [isCurrent, focusTick, wantFocus, focusBlocked]);
  const why = reasonsFromQueueItem(item.reasons ?? [], item.has_numeric_spec, criticalReasons);
  const chips = reasonChips({ why, hasNumeric: item.has_numeric_spec });
  const stale = (item.reasons ?? []).includes(STALE_NAME);
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
      className={`flex cursor-pointer flex-col justify-center gap-0.5 overflow-hidden border-b border-slate-200 px-2 text-sm ${FOCUS} ${
        isCurrent ? "bg-blue-50 ring-1 ring-inset ring-blue-500" : "bg-white hover:bg-slate-50"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="truncate font-mono text-xs">{item.block_id}</span>
        <span className="text-xs text-slate-600">p.{item.page}</span>
        <span className="text-xs text-slate-600">{item.type}</span>
        <span className="ml-auto text-xs tabular-nums">{item.confidence === null || item.confidence === undefined ? "n/a" : item.confidence.toFixed(2)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {item.status !== "queued" ? (
          <span className="rounded bg-emerald-100 px-1.5 text-xs text-emerald-900">{STATUS_LABEL[item.status] ?? item.status}</span>
        ) : null}
        {stale || chips.status.length ? <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-950">{STALE_NAME}</span> : null}
        {item.stale_doc ? <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-950">re-scoring</span> : null}
        {chips.reasons.map((c) => (
          <Hint key={c.name} id="reasonChip" text={signalHint(c.name) ?? undefined}>
            <span className={`rounded px-1.5 text-xs ${TONE[c.tone]}`}>{c.text}</span>
          </Hint>
        ))}
        {chips.overflow.length ? (
          <span title={chips.overflow.join(", ")} className="rounded bg-slate-100 px-1.5 text-xs text-slate-700">
            +{chips.overflow.length}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export default memo(QueueCardImpl);
