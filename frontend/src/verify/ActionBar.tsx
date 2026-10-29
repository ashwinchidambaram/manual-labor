import { FOCUS } from "./labels";

interface Props {
  hasCurrent: boolean;
  isFigure: boolean;
  onApprove: () => void;
  onEdit: () => void;
  onFlag: () => void;
  onSkip: () => void;
  onBack: () => void;
  onHelp: () => void;
}

export default function ActionBar(p: Props) {
  const btn = (label: string, key: string, onClick: () => void, disabled: boolean, id: string) => (
    <button
      type="button"
      data-testid={id}
      disabled={disabled}
      onClick={onClick}
      className={`flex items-center gap-1 rounded border border-slate-500 bg-white px-3 py-1 text-sm disabled:opacity-40 ${FOCUS}`}
    >
      {label} <kbd className="rounded bg-slate-200 px-1 font-mono text-xs">{key}</kbd>
    </button>
  );
  return (
    <div role="toolbar" aria-label="Review actions" className="sticky bottom-0 flex items-center gap-2 border-t border-slate-300 bg-white px-4 py-2">
      {btn("Approve", "A", p.onApprove, !p.hasCurrent, "act-approve")}
      {btn("Edit", "E", p.onEdit, !p.hasCurrent || p.isFigure, "act-edit")}
      {btn("Flag", "F", p.onFlag, !p.hasCurrent, "act-flag")}
      {btn("Skip", "J", p.onSkip, !p.hasCurrent, "act-skip")}
      {btn("Back", "K", p.onBack, false, "act-back")}
      <button type="button" onClick={p.onHelp} className={`ml-auto rounded border border-slate-400 px-2 py-1 text-sm ${FOCUS}`}>
        <kbd className="font-mono">?</kbd> Help
      </button>
    </div>
  );
}
