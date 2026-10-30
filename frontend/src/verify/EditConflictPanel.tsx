import { useEffect, useRef } from "react";
import type { EditConflict } from "../api/schema";
import DiffView from "./DiffView";
import { FOCUS } from "./labels";

interface Props {
  conflict: EditConflict;
  onConfirm: () => void;
  onKeep: () => void;
  busy: boolean;
}

export default function EditConflictPanel({ conflict, onConfirm, onKeep, busy }: Props) {
  const confirm = useRef<HTMLButtonElement>(null);
  const keep = useRef<HTMLButtonElement>(null);
  useEffect(() => confirm.current?.focus(), []);
  const onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onKeep();
    } else if (e.key === "Tab") {
      e.preventDefault();
      (document.activeElement === confirm.current ? keep : confirm).current?.focus();
    }
  };
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="conflict-title"
      data-testid="edit-conflict"
      onKeyDown={onKeyDown}
      className="space-y-2 rounded-xl border border-fail-line bg-fail-wash p-4 font-sans text-sm text-ink"
    >
      <h3 id="conflict-title" className="font-semibold text-fail">
        <span aria-hidden="true">✕ </span>
        This edit changes content
      </h3>
      <ul className="list-disc pl-5">
        {conflict.violations.map((v, i) => (
          <li key={i}>
            {v.kind}: <code>{v.raw || "(nothing)"}</code> → <code>{v.clean || "(nothing)"}</code>
          </li>
        ))}
      </ul>
      {conflict.numeric_changes.length ? (
        <p data-testid="numeric-changes" className="font-bold text-fail">
          Numbers changed: {conflict.numeric_changes.join("; ")}
        </p>
      ) : null}
      <DiffView ops={conflict.diff} />
      <div className="flex gap-2">
        <button
          ref={confirm}
          type="button"
          disabled={busy}
          onClick={onConfirm}
          className={`min-h-[2.25rem] rounded-lg bg-fail px-3 font-semibold text-act-on ${FOCUS}`}
        >
          Confirm content change
        </button>
        <button ref={keep} type="button" onClick={onKeep} className={`min-h-[2.25rem] rounded-lg border border-line-strong bg-raised px-3 ${FOCUS}`}>
          Keep editing
        </button>
      </div>
    </div>
  );
}
