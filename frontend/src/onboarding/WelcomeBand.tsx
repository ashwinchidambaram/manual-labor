import { useRef } from "react";
import type { ScopeSummary, SourceInfo } from "../api/schema";

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

export interface WelcomeFacts {
  manuals: number;
  /** manuals whose blocks are grouped and listed on Scope; the others are still being read */
  ready: number;
  /** every manual's file name, in the server's order */
  names: string[];
  pages: number;
  /** blocks and figures in the current selection, and whether that selection is every selectable block */
  blocks: number;
  figures: number;
  /** the selected blocks by type, from the block index; null when it is not loaded */
  types: Record<string, number> | null;
  everything: boolean;
  queued: number;
  numericQueued: number;
}

export function welcomeFacts(
  sources: readonly SourceInfo[],
  summary: ScopeSummary,
  everything: boolean,
  extra: { ready: number; types: Record<string, number> | null } = { ready: sources.length, types: null },
): WelcomeFacts {
  return {
    manuals: sources.length,
    ready: extra.ready,
    names: sources.map((s) => s.filename),
    pages: sources.reduce((n, s) => n + s.pages, 0),
    blocks: summary.blocks,
    figures: summary.figures,
    types: extra.types,
    everything,
    queued: summary.review_load.queued,
    numericQueued: summary.review_load.numeric_queued,
  };
}

const list = (xs: string[]): string => (xs.length <= 1 ? (xs[0] ?? "") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** Block types in the order a reader meets them, with the word for each. */
const TYPE_WORDS: [string, string][] = [
  ["paragraph", "paragraph"],
  ["list", "list"],
  ["table", "table"],
  ["heading", "heading"],
  ["caption", "caption"],
  ["figure", "figure"],
  ["other", "other block"],
];

/**
 * "364 blocks: 270 paragraphs, 44 headings, 19 captions and 20 figures" when the type counts add up to the server's
 * total; otherwise only what is certain: "364 blocks, 20 of them figures". A count is never estimated.
 */
export function blockBreakdown(blocks: number, figures: number, types: Record<string, number> | null): string {
  const known = new Set(TYPE_WORDS.map(([t]) => t));
  const sum = types ? Object.values(types).reduce((a, b) => a + b, 0) : -1;
  const unknownTypes = types ? Object.keys(types).some((t) => !known.has(t) && (types[t] ?? 0) > 0) : true;
  if (types && sum === blocks && !unknownTypes && blocks > 0) {
    const parts = TYPE_WORDS.filter(([t]) => (types[t] ?? 0) > 0).map(([t, w]) => plural(types[t], w));
    return `${plural(blocks, "block")}: ${list(parts)}`;
  }
  return figures > 0 ? `${plural(blocks, "block")}, ${figures} of them figure${figures === 1 ? "" : "s"}` : plural(blocks, "block");
}

/** Every number is a server count; the wording changes with them instead of rounding or guessing. */
export function welcomeCopy(f: WelcomeFacts): { title: string; body: string; manuals: string; steps: { title: string; line: string }[] } {
  const what = blockBreakdown(f.blocks, f.figures, f.types);
  const found = f.everything ? `We read ${plural(f.pages, "page")} and found ${what}.` : `We read ${plural(f.pages, "page")}. Selected right now: ${what}.`;
  const numeric =
    f.queued === 0
      ? "Nothing needs a person yet."
      : f.numericQueued === f.queued
        ? "All of them contain numbers, which a person always checks."
        : f.numericQueued > 0
          ? `${f.numericQueued} of them contain numbers, which a person always checks.`
          : "None of them contain numbers; each scored under the auto-approve line.";
  const reading = f.manuals - f.ready;
  const title =
    reading <= 0
      ? `Welcome. Your ${f.manuals === 1 ? "manual is" : `${f.manuals} manuals are`} read and ready.`
      : `Welcome. ${f.ready} of your ${f.manuals} manuals ${f.ready === 1 ? "is" : "are"} ready; ${reading === 1 ? "one is" : `${reading} are`} still being read.`;
  return {
    title,
    body: `${found} You decide what goes into the knowledge base. Anything the checks cannot vouch for comes to you, next to the page it came from.`,
    manuals: list(f.names),
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
        <p className="mt-1.5 text-sm text-muted" data-testid="welcome-manuals">
          <span className="font-medium text-ink">Your manuals:</span> {c.manuals}
        </p>
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
