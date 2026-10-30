import type { View } from "../api/schema";
import Hint from "../onboarding/Hint";

const OPTIONS: { value: View; label: string }[] = [
  { value: "topic", label: "Suggested topics" },
  { value: "structure", label: "Document structure" },
];

/** Two-option radiogroup with roving tabindex; arrows move and select (native radio feel). */
export default function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    const dir = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    const group = e.currentTarget;
    const i = OPTIONS.findIndex((o) => o.value === view);
    const next = OPTIONS[(i + dir + OPTIONS.length) % OPTIONS.length];
    onChange(next.value);
    requestAnimationFrame(() => group.querySelector<HTMLElement>(`[data-value="${next.value}"]`)?.focus());
  };
  return (
    <Hint id="viewToggle" within>
    <div role="radiogroup" aria-label="Grouping view" className="inline-flex rounded-xl bg-sunk p-[3px] ring-1 ring-inset ring-line-soft" onKeyDown={onKeyDown} data-testid="view-toggle">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={view === o.value}
          tabIndex={view === o.value ? 0 : -1}
          data-value={o.value}
          onClick={() => onChange(o.value)}
          className={`min-h-[2.25rem] whitespace-nowrap rounded-[9px] px-3.5 text-sm transition-colors duration-150 ease-out-quart focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus ${
            view === o.value ? "bg-raised font-semibold text-ink shadow-[0_1px_2px_rgb(39_32_26/0.12)]" : "font-medium text-muted hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
    </Hint>
  );
}
