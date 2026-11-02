import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { useRemovalPreview, useRemoveSource } from "../api/queries";
import type { SourceRemoval } from "../api/schema";

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";
const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

/**
 * What removing a manual loses, in the server's counts (design 08 section 11). A zero is left out rather than said
 * ("0 decisions"); the last sentence is there only when something stays behind in the log.
 */
export function removalSentences(p: SourceRemoval): string[] {
  const out: string[] = [];
  const blocks = p.blocks === 0 ? "" : p.selected_blocks > 0 ? `: ${plural(p.blocks, "block")}, ${p.selected_blocks} of them in your selection` : `: ${plural(p.blocks, "block")}`;
  out.push(`The file and everything read from it are deleted${blocks}.`);
  const kept = [p.decisions > 0 ? plural(p.decisions, "decision") : "", p.open_flags > 0 ? plural(p.open_flags, "open flag") : ""].filter(Boolean);
  if (kept.length) {
    const one = p.decisions + p.open_flags === 1;
    out.push(`${kept.join(" and ")} on its blocks ${one ? "stays" : "stay"} in the decision log but no longer ${one ? "counts" : "count"}.`);
    if (p.decisions > 0) out.push("Adding the same file again brings back the decisions whose text has not changed.");
  }
  return out;
}

/** The confirmation for removing a manual (design 08 section 11): an alert dialog, focus on "Keep it". */
export default function RemoveManualDialog({ slug, filename, onClose }: { slug: string; filename: string; onClose: (removed: boolean) => void }) {
  const preview = useRemovalPreview(slug);
  const remove = useRemoveSource();
  const [requestId] = useState(() => crypto.randomUUID());
  const dlg = useRef<HTMLDivElement>(null);
  const keep = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const prior = document.activeElement as HTMLElement | null;
    keep.current?.focus();
    return () => prior?.focus?.();
  }, []);
  const p = preview.data;
  const blocked = p?.blocked_by ?? null;
  const err = remove.error instanceof ApiError ? remove.error.detail : remove.error ? remove.error.message : null;
  const onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose(false);
    } else if (e.key === "Tab") {
      const f = Array.from(dlg.current?.querySelectorAll<HTMLElement>("button:not([disabled])") ?? []);
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
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="remove-manual-title"
        aria-describedby="remove-manual-body"
        data-testid="remove-dialog"
        onKeyDown={onKeyDown}
        className="w-[30rem] max-w-full space-y-3 rounded-2xl bg-raised p-5 text-ink shadow-[0_24px_60px_-20px_rgb(39_32_26/0.45)]"
      >
        <h2 id="remove-manual-title" className="text-lg font-semibold">
          Remove {filename}?
        </h2>
        <div id="remove-manual-body" className="space-y-1.5 text-sm" data-testid="remove-body">
          {p ? removalSentences(p).map((s) => <p key={s}>{s}</p>) : preview.isError ? <p>Could not read what would be removed.</p> : <p className="text-muted">Counting what would be removed…</p>}
          {blocked ? (
            <p className="text-needs-ink" data-testid="remove-blocked">
              {blocked}
            </p>
          ) : null}
        </div>
        {err ? (
          <p role="alert" className="text-sm text-fail" data-testid="remove-error">
            {err}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <button ref={keep} type="button" onClick={() => onClose(false)} className={`min-h-[2.5rem] rounded-xl border border-line-strong bg-raised px-4 font-semibold ${FOCUS}`}>
            Keep it
          </button>
          <button
            type="button"
            data-testid="remove-confirm"
            disabled={!p || !!blocked || remove.isPending}
            onClick={() => remove.mutate({ slug, requestId }, { onSuccess: () => onClose(true) })}
            className={`min-h-[2.5rem] rounded-xl bg-act px-4 font-semibold text-act-on hover:bg-act-hover disabled:opacity-50 ${FOCUS} focus-visible:ring-offset-2`}
          >
            Remove manual
          </button>
        </div>
      </div>
    </div>
  );
}
