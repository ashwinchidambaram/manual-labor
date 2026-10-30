import { forwardRef } from "react";
import Copy from "./Copy";
import type { GuideStep } from "./guide";

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-1";
/** A mouse click on a guide button must not take focus from the editor, the queue or a dialog (O2). */
const keepFocus = (e: React.MouseEvent): void => e.preventDefault();

export interface GuidePanelProps {
  step: GuideStep;
  index: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
  onHide: () => void;
  /** project facts that change what the guide says */
  notes?: string[];
}

/**
 * The docked, non-modal getting-started panel (design 12 O1, O2). It never calls focus() and sits outside every
 * `data-zone`, so the screen's focus rules and hotkeys work exactly as without it.
 */
const GuidePanel = forwardRef<HTMLElement, GuidePanelProps>(function GuidePanel({ step, index, total, onPrev, onNext, onHide, notes = [] }, ref) {
  const last = index === total - 1;
  return (
    <aside
      ref={ref}
      aria-label="Getting started"
      data-testid="guide-panel"
      data-step={step.id}
      className="fixed inset-x-0 bottom-0 z-30 flex max-h-[40vh] flex-col border-t border-slate-300 bg-white shadow-[0_-4px_16px_rgba(15,23,42,0.08)] xl:sticky xl:top-0 xl:z-auto xl:max-h-screen xl:w-[22rem] xl:shrink-0 xl:self-start xl:border-l xl:border-t-0 xl:shadow-none"
    >
      <div className="flex items-baseline justify-between gap-2 border-b border-slate-200 px-4 pb-2 pt-3">
        <p className="text-xs text-slate-600">
          Getting started <span aria-hidden="true">·</span>{" "}
          <span data-testid="guide-progress">
            Step {index + 1} of {total}
          </span>
        </p>
        <button type="button" onMouseDown={keepFocus} onClick={onHide} data-testid="guide-hide" className={`rounded px-1.5 text-xs text-slate-700 underline underline-offset-2 hover:text-slate-950 ${FOCUS}`}>
          Hide guide
        </button>
      </div>
      {/* scrollable, so keyboard users can reach it (it holds no control of its own) */}
      <div tabIndex={0} role="region" aria-label="Guide text" className={`min-h-0 flex-1 overflow-y-auto px-4 py-3 ${FOCUS} focus-visible:ring-inset focus-visible:ring-offset-0`}>
        <h2 className="text-base font-semibold leading-snug text-slate-950" data-testid="guide-title">
          {step.title}
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-slate-700">{step.what}</p>
        {notes.map((n) => (
          <p key={n} role="note" className="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-950">
            {n}
          </p>
        ))}
        <h3 className="mt-4 text-xs font-semibold text-slate-800">What to do</h3>
        <ol className="mt-1 space-y-1.5 text-sm leading-relaxed text-slate-800">
          {step.do.map((d, i) => (
            <li key={d} className="grid grid-cols-[1.25rem_1fr] gap-1">
              <span aria-hidden="true" className="tabular-nums text-slate-500">
                {i + 1}.
              </span>
              <span>
                <Copy text={d} />
              </span>
            </li>
          ))}
        </ol>
        <h3 className="mt-4 text-xs font-semibold text-slate-800">Why you can trust this</h3>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm leading-relaxed text-slate-700 marker:text-slate-400">
          {step.trust.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </div>
      <div className="flex items-center gap-2 border-t border-slate-200 px-4 py-2">
        <button
          type="button"
          onMouseDown={keepFocus}
          onClick={onPrev}
          disabled={index === 0}
          className={`rounded border border-slate-400 bg-white px-2.5 py-1 text-sm hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 ${FOCUS}`}
        >
          Previous
        </button>
        <button
          type="button"
          onMouseDown={keepFocus}
          onClick={last ? onHide : onNext}
          data-testid="guide-next"
          className={`ml-auto rounded bg-slate-900 px-3 py-1 text-sm font-medium text-white hover:bg-slate-700 ${FOCUS}`}
        >
          {last ? "Done" : "Next"}
        </button>
      </div>
    </aside>
  );
});

export default GuidePanel;
