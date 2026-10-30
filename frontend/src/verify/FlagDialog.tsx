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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(39_32_26/0.38)] p-4">
      <div
        ref={dlg}
        role="dialog"
        aria-modal="true"
        aria-label="Flag block"
        data-hotkey-scope="flagDialog"
        data-testid="flag-dialog"
        onKeyDown={onKeyDown}
        className="w-[28rem] max-w-full space-y-3 rounded-2xl bg-raised p-5 text-ink shadow-[0_24px_60px_-20px_rgb(39_32_26/0.45)]"
      >
        <h2 className="text-lg font-semibold">Flag this block</h2>
        <p className="text-sm text-muted" data-testid="flag-next">
          It goes to the Agent screen, where a model proposes a fix for you to accept or reject. This flag locks the export until it is resolved on
          the Agent screen.
        </p>
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
              className={`min-h-[2.25rem] rounded-lg px-2.5 text-sm ring-1 ring-inset ${cat === c.id ? "bg-ink font-semibold text-raised ring-ink" : "bg-raised text-ink ring-line-strong hover:bg-sunk"}`}
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
            className={`mt-1 w-full rounded-lg border border-line-strong bg-raised p-2 ${FOCUS}`}
          />
          <span className="mt-1 block text-xs text-muted">In the note, Ctrl or Cmd + Enter submits.</span>
        </label>
        <p role="status" className="min-h-[1.25rem] text-sm text-fail" data-testid="flag-msg">
          {msg}
        </p>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} className={`min-h-[2.5rem] rounded-xl border border-line-strong bg-raised px-4 font-semibold ${FOCUS}`}>
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            className={`inline-flex min-h-[2.5rem] items-center gap-2 rounded-xl bg-act px-4 font-semibold text-act-on hover:bg-act-hover ${FOCUS} focus-visible:ring-offset-2`}
          >
            Submit
            {/* Enter submits outside the note; inside it, Ctrl or Cmd + Enter (hotkeys vFlagSubmit, vFlagSubmitMod) */}
            <kbd aria-hidden="true" className="rounded-md border border-act-line bg-act-hover px-1.5 font-mono text-2xs font-semibold leading-5 text-act-on">
              Enter
            </kbd>
          </button>
        </div>
      </div>
    </div>
  );
}
