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
  const opts: { value: Split; label: string }[] = [
    { value: "per_topic", label: `One article per topic (${summary.articles_per_topic})` },
    { value: "per_document", label: `One article per document (${summary.articles_per_document})` },
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
      <Hint id="splitMode" within>
      <div role="radiogroup" aria-label="Article split" className="flex flex-col gap-1" onKeyDown={onKeyDown}>
        {opts.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={split === o.value}
            tabIndex={split === o.value ? 0 : -1}
            data-value={o.value}
            onClick={() => onChange(o.value)}
            className={`rounded border px-2 py-1 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
              split === o.value ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white hover:bg-slate-100"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
      </Hint>
      {view === "structure" ? (
        <p className="mt-1 text-xs text-slate-600" data-testid="split-hint">
          Per-topic article counts always come from the topic view.
        </p>
      ) : null}
    </div>
  );
}
