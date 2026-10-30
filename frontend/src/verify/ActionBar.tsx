import Hint from "../onboarding/Hint";
import type { HintId } from "../onboarding/hints";
import { FOCUS } from "./labels";

interface Props {
  hasCurrent: boolean;
  isFigure: boolean;
  /** the current block has numbers: Approve also records them as checked */
  numeric?: boolean;
  /** "Block 3 of 216" */
  position?: string | null;
  onApprove: () => void;
  onEdit: () => void;
  onFlag: () => void;
  onSkip: () => void;
  onBack: () => void;
  onHelp: () => void;
}

const KEY = "rounded-md border px-1.5 font-mono text-2xs font-semibold leading-5";

/** The decisions, always in view. Approve is the one primary button and says what it records (design 13 section 2.5.4). */
export default function ActionBar(p: Props) {
  const btn = (label: string, key: string, onClick: () => void, disabled: boolean, id: string, hint: HintId) => (
    <Hint id={hint}>
      <button
        type="button"
        data-testid={id}
        disabled={disabled}
        onClick={onClick}
        className={`inline-flex min-h-[2.75rem] items-center gap-2 rounded-xl border border-line-strong bg-raised px-3.5 text-sm font-semibold text-ink transition-colors duration-150 ease-out-quart hover:bg-sunk disabled:cursor-not-allowed disabled:opacity-40 ${FOCUS} focus-visible:ring-offset-2`}
      >
        {label} <kbd className={`${KEY} border-line bg-paper text-ink shadow-key`}>{key}</kbd>
      </button>
    </Hint>
  );
  return (
    <div
      role="toolbar"
      aria-label="Review actions"
      className="sticky bottom-[var(--guide-sheet,0px)] z-20 flex shrink-0 flex-wrap items-center gap-2 border-t border-line bg-raised px-4 py-2 wide:static wide:px-7 wide:py-2.5"
    >
      <Hint id="approve">
        <button
          type="button"
          data-testid="act-approve"
          disabled={!p.hasCurrent}
          onClick={p.onApprove}
          className={`inline-flex min-h-[2.75rem] items-center gap-2.5 rounded-xl bg-act px-4 text-sm font-semibold text-act-on transition-colors duration-150 ease-out-quart hover:bg-act-hover disabled:cursor-not-allowed disabled:opacity-40 ${FOCUS} focus-visible:ring-offset-2`}
        >
          Approve <kbd className={`${KEY} border-act-line bg-act-hover text-act-on`}>A</kbd>
          {p.numeric && !p.isFigure ? <span className="sr-only text-xs font-normal opacity-95 wide:not-sr-only">and mark its numbers checked</span> : null}
        </button>
      </Hint>
      {btn("Edit", "E", p.onEdit, !p.hasCurrent || p.isFigure, "act-edit", "edit")}
      {btn("Flag", "F", p.onFlag, !p.hasCurrent, "act-flag", "flag")}
      {btn("Skip", "J", p.onSkip, !p.hasCurrent, "act-skip", "skip")}
      {btn("Back", "K", p.onBack, false, "act-back", "back")}
      <span className="ml-auto flex items-center gap-3 text-xs text-muted">
        {p.position ? <span className="hidden tabular-nums lg:inline">{p.position} · saved after every action</span> : null}
        <button type="button" onClick={p.onHelp} className={`hidden min-h-[2rem] rounded-lg px-2 text-xs font-medium text-muted hover:bg-sunk hover:text-ink wide:inline-block ${FOCUS}`}>
          <kbd className="font-mono font-bold">?</kbd> Help
        </button>
      </span>
    </div>
  );
}
