import { useEffect, useRef, useState } from "react";
import type { FlagCategory } from "../api/schema";
import { useHotkeys } from "../hooks/useHotkeys";
import { FLAG_CATEGORIES, FOCUS } from "./labels";

interface Props {
  onSubmit: (category: FlagCategory, note: string | null) => void;
  onCancel: () => void;
}

export default function FlagDialog({ onSubmit, onCancel }: Props) {
  const [cat, setCat] = useState<FlagCategory | null>(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const dlg = useRef<HTMLDivElement>(null);
  const group = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prior = document.activeElement as HTMLElement | null;
    group.current?.focus();
    return () => prior?.focus?.();
  }, []);
  const submit = (): void => {
    if (!cat) {
      setMsg("Choose a category");
      return;
    }
    onSubmit(cat, note.trim() === "" ? null : note.trim());
  };
  const pick = (i: number) => () => {
    setCat(FLAG_CATEGORIES[i].id);
    setMsg("");
  };
  useHotkeys({
    vFlagCat1: pick(0),
    vFlagCat2: pick(1),
    vFlagCat3: pick(2),
    vFlagCat4: pick(3),
    vFlagCat5: pick(4),
    vFlagSubmit: submit,
    vFlagSubmitMod: submit,
  });
  const onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onCancel();
    } else if (e.key === "Tab") {
      const f = Array.from(dlg.current?.querySelectorAll<HTMLElement>("[tabindex='0'], textarea, button:not([tabindex='-1'])") ?? []);
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div
        ref={dlg}
        role="dialog"
        aria-modal="true"
        aria-label="Flag block"
        data-hotkey-scope="flagDialog"
        data-testid="flag-dialog"
        onKeyDown={onKeyDown}
        className="w-[28rem] space-y-3 rounded bg-white p-4 shadow-xl"
      >
        <h2 className="text-lg font-semibold">Flag this block</h2>
        <div ref={group} role="radiogroup" aria-label="Category" tabIndex={0} className={`flex flex-wrap gap-2 rounded p-1 ${FOCUS}`}>
          {FLAG_CATEGORIES.map((c, i) => (
            <button
              key={c.id}
              type="button"
              role="radio"
              aria-checked={cat === c.id}
              tabIndex={-1}
              data-testid={`flag-cat-${c.id}`}
              onClick={() => {
                pick(i)();
                group.current?.focus();
              }}
              className={`rounded border px-2 py-1 text-sm ${cat === c.id ? "border-slate-900 bg-slate-900 text-white" : "border-slate-400"}`}
            >
              <kbd className="mr-1 font-mono text-xs">{i + 1}</kbd>
              {c.label}
            </button>
          ))}
        </div>
        <label className="block text-sm">
          Note (optional)
          <textarea
            aria-label="Note (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            className={`mt-1 w-full rounded border border-slate-400 p-1 ${FOCUS}`}
          />
        </label>
        <p role="status" className="min-h-[1.25rem] text-sm text-red-800" data-testid="flag-msg">
          {msg}
        </p>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} className={`rounded border border-slate-500 px-3 py-1 ${FOCUS}`}>
            Cancel
          </button>
          <button type="button" onClick={submit} className={`rounded bg-slate-900 px-3 py-1 text-white ${FOCUS}`}>
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}
