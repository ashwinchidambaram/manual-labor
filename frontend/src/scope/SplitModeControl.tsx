import type { ScopeSummary, Split, View } from "../api/schema";
import Hint from "../onboarding/Hint";

export default function SplitModeControl({
  split,
  summary,
  view,
  onChange,
}: {
  split: Split;
  summary: ScopeSummary;
  view: View;
  onChange: (s: Split) => void;
}) {
  const opts: { value: Split; label: string; sub: string }[] = [
    { value: "per_topic", label: `One article per topic (${summary.articles_per_topic})`, sub: "Smaller articles, one per topic" },
    { value: "per_document", label: `One article per document (${summary.articles_per_document})`, sub: "One article per manual" },
  ];
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const group = e.currentTarget;
    const next = split === "per_topic" ? "per_document" : "per_topic";
    onChange(next);
    requestAnimationFrame(() => group.querySelector<HTMLElement>(`[data-value="${next}"]`)?.focus());
  };
  return (
    <div data-testid="split-mode">
      <h3 className="mb-2 text-2xs font-semibold uppercase tracking-[0.07em] text-muted">Articles</h3>
      <Hint id="splitMode" within>
      <div role="radiogroup" aria-label="Article split" className="flex flex-col gap-1.5" onKeyDown={onKeyDown}>
        {opts.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={split === o.value}
            tabIndex={split === o.value ? 0 : -1}
            data-value={o.value}
            onClick={() => onChange(o.value)}
            aria-describedby={`split-sub-${o.value}`}
            className={`flex items-start gap-2.5 rounded-lg px-3 py-2 text-left text-sm ring-1 ring-inset transition-colors duration-150 ease-out-quart focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus ${
              split === o.value ? "bg-sunk text-ink ring-line-strong" : "text-ink ring-line-soft hover:bg-sunk"
            }`}
          >
            <span
              aria-hidden="true"
              className={`mt-0.5 h-4 w-4 shrink-0 rounded-full border-ink bg-raised ${split === o.value ? "border-[5px]" : "border-2 border-line-strong"}`}
            />
            <span className="flex flex-col">
              <span>{o.label}</span>
              <span id={`split-sub-${o.value}`} aria-hidden="true" className="text-xs text-muted">
                {o.sub}
              </span>
            </span>
          </button>
        ))}
      </div>
      </Hint>
      {view === "structure" ? (
        <p className="mt-1.5 text-xs text-muted" data-testid="split-hint">
          Per-topic article counts always come from the topic view.
        </p>
      ) : null}
    </div>
  );
}
