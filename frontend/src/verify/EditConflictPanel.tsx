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
      className="space-y-2 rounded border-2 border-red-400 bg-red-50 p-3 text-sm"
    >
      <h3 id="conflict-title" className="font-semibold text-red-900">
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
        <p data-testid="numeric-changes" className="font-bold text-red-800">
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
          className={`rounded bg-red-700 px-3 py-1 text-white ${FOCUS}`}
        >
          Confirm content change
        </button>
        <button ref={keep} type="button" onClick={onKeep} className={`rounded border border-slate-500 px-3 py-1 ${FOCUS}`}>
          Keep editing
        </button>
      </div>
    </div>
  );
}
