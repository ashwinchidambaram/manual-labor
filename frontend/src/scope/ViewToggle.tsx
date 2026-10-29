import type { View } from "../api/schema";

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
    <div role="radiogroup" aria-label="Grouping view" className="inline-flex rounded border border-slate-400" onKeyDown={onKeyDown} data-testid="view-toggle">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={view === o.value}
          tabIndex={view === o.value ? 0 : -1}
          data-value={o.value}
          onClick={() => onChange(o.value)}
          className={`px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600 ${
            view === o.value ? "bg-slate-900 text-white" : "bg-white hover:bg-slate-100"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
