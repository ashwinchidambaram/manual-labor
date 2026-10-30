import { useRef } from "react";
import type { ScopeSummary, SourceInfo } from "../api/schema";

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

export interface WelcomeFacts {
  manuals: number;
  pages: number;
  /** blocks and figures in the current selection, and whether that selection is every selectable block */
  blocks: number;
  figures: number;
  everything: boolean;
  queued: number;
  numericQueued: number;
}

export function welcomeFacts(sources: readonly SourceInfo[], summary: ScopeSummary, everything: boolean): WelcomeFacts {
  return {
    manuals: sources.length,
    pages: sources.reduce((n, s) => n + s.pages, 0),
    blocks: summary.blocks,
    figures: summary.figures,
    everything,
    queued: summary.review_load.queued,
    numericQueued: summary.review_load.numeric_queued,
  };
}

/** Every number is a server count; the wording changes with them instead of rounding or guessing. */
export function welcomeCopy(f: WelcomeFacts): { title: string; body: string; steps: { title: string; line: string }[] } {
  const found = f.everything
    ? `We read ${plural(f.pages, "page")} and found ${plural(f.blocks, "block")} of text (paragraphs, lists and tables) and ${plural(f.figures, "figure")}.`
    : `We read ${plural(f.pages, "page")}. Selected right now: ${plural(f.blocks, "block")} of text and ${plural(f.figures, "figure")}.`;
  const numeric =
    f.queued === 0
      ? "Nothing needs a person yet."
      : f.numericQueued === f.queued
        ? "All of them contain numbers, which a person always checks."
        : f.numericQueued > 0
          ? `${f.numericQueued} of them contain numbers, which a person always checks.`
          : "None of them contain numbers; each scored under the auto-approve line.";
  return {
    title: `Welcome. Your ${f.manuals === 1 ? "manual is" : `${f.manuals} manuals are`} read and ready.`,
    body: `${found} You decide what goes into the knowledge base. Anything the checks cannot vouch for comes to you, next to the page it came from.`,
    steps: [
      { title: "Choose what goes in", line: "Pick topics or sections. You are here." },
      { title: `Check ${plural(f.queued, "block")} against the page`, line: numeric },
      { title: "Fix anything you flag", line: "A model proposes a fix, the checks run again, and you decide." },
      { title: "Export the reviewed knowledge base", line: "Articles, figures and a manifest of every decision." },
    ],
  };
}

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2";

/**
 * First-run welcome (design 13 section 2.5.2, owner decision D6): a region, never a dialog, shown once per project
 * (the server's `ui/guide` flag). Both buttons record it as seen. Focus is only moved when it was inside the band
 * (it would otherwise be lost with it): to the screen's own focus target, the group list.
 */
export default function WelcomeBand({ facts, onDismiss }: { facts: WelcomeFacts; onDismiss: () => void }) {
  const ref = useRef<HTMLElement>(null);
  const c = welcomeCopy(facts);
  const dismiss = (): void => {
    const inside = ref.current?.contains(document.activeElement) ?? false;
    onDismiss();
    if (inside)
      (document.querySelector<HTMLElement>("[data-zone='tree'] [tabindex='0']") ?? document.querySelector<HTMLElement>("[data-help-button]"))?.focus();
  };
  return (
    <section
      ref={ref}
      aria-labelledby="welcome-title"
      data-testid="welcome"
      className="grid gap-x-10 gap-y-6 rounded-2xl bg-sunk px-6 py-6 ring-1 ring-inset ring-line-soft lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:px-8 lg:py-7"
    >
      <div className="min-w-0">
        <h2 id="welcome-title" className="text-xl font-bold tracking-[-0.015em] text-ink lg:text-2xl">
          {c.title}
        </h2>
        <p className="mt-2 max-w-[58ch] text-base leading-relaxed text-ink">{c.body}</p>
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={dismiss}
            data-testid="welcome-start"
            className={`min-h-[2.75rem] rounded-xl bg-act px-5 text-base font-semibold text-act-on transition-colors duration-150 ease-out-quart hover:bg-act-hover ${FOCUS}`}
          >
            Start with step 1
          </button>
          <button type="button" onClick={dismiss} data-testid="welcome-dismiss" className={`min-h-[2.75rem] rounded-xl px-3 text-base text-muted hover:text-ink ${FOCUS}`}>
            I have used this before
          </button>
        </div>
      </div>
      <ol className="flex flex-col gap-3.5" aria-label="The four steps">
        {c.steps.map((s, i) => (
          <li key={s.title} className="grid grid-cols-[1.75rem_1fr] items-start gap-3">
            <span
              aria-hidden="true"
              className={`grid h-7 w-7 place-items-center rounded-full text-xs font-bold ${i === 0 ? "bg-act text-act-on" : "border border-line bg-raised text-muted"}`}
            >
              {i + 1}
            </span>
            <span>
              <span className="block text-base font-semibold text-ink">{s.title}</span>
              <span className="block text-sm text-muted">{s.line}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
