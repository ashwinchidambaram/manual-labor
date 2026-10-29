import type { DocReadiness, QueueSort, ReviewCounts } from "../api/schema";
import { FOCUS } from "./labels";
import { normalizeView, sliderCopy } from "./sliderCopy";

const SORTS: { id: QueueSort; label: string }[] = [
  { id: "worst_first", label: "Worst first" },
  { id: "by_page", label: "By page" },
  { id: "figures_only", label: "Figures only" },
];

export interface StatusStripProps {
  counts: ReviewCounts;
  /** auto-approved blocks currently listed because of the view filter */
  viewAdded: number;
  viewAddedPartial: boolean;
  /** the view filter the list was built with (the server cursor); differs from `view` while a change is saving */
  appliedView: number | null;
  docs: DocReadiness[];
  threshold: number;
  view: number | null;
  sort: QueueSort;
  onView: (v: number | null) => void;
  onSort: (s: QueueSort) => void;
  saveState: string;
}

function Stat({ id, label, value }: { id: string; label: string; value: number }) {
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-xs text-slate-600">{label}</span>
      <span className="text-lg font-semibold tabular-nums" data-testid={id}>
        {value}
      </span>
    </div>
  );
}

export default function StatusStrip(p: StatusStripProps) {
  const queued = Math.max(0, p.counts.pending - p.viewAdded);
  const T = p.threshold;
  return (
    <section aria-label="Review status" className="flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-slate-300 bg-white px-4 py-2">
      <Stat id="cnt-queued" label="Queued" value={queued} />
      <Stat id="cnt-auto" label="Auto-approved" value={p.counts.auto_approved} />
      <Stat id="cnt-flagged" label="Flagged" value={p.counts.flagged_open} />
      <Stat id="cnt-done" label="Done" value={p.counts.approved + p.counts.edited} />
      <Stat id="cnt-scope" label="In scope" value={p.counts.in_scope} />
      <div className="flex items-center gap-2">
        <input
          type="range"
          aria-label="Also review auto-approved blocks below"
          min={T}
          max={1}
          step={0.01}
          value={p.view ?? T}
          onChange={(e) => p.onView(normalizeView(Number(e.target.value), T))}
          className={`w-40 ${FOCUS}`}
        />
        <span className="text-sm text-slate-700" data-testid="view-copy">
          {sliderCopy(p.view, T, p.viewAdded, p.viewAddedPartial, p.view !== p.appliedView)}
        </span>
        <button type="button" onClick={() => p.onView(1)} className={`rounded border border-slate-400 px-2 text-xs ${FOCUS}`}>
          Show all
        </button>
      </div>
      <label className="flex items-center gap-1 text-sm">
        <span className="sr-only">Sort</span>
        <select
          aria-label="Sort"
          value={p.sort}
          onChange={(e) => p.onSort(e.target.value as QueueSort)}
          className={`rounded border border-slate-400 bg-white px-1 py-0.5 ${FOCUS}`}
        >
          {SORTS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <span className="ml-auto text-sm text-slate-700" data-testid="save-state" role="status">
        {p.saveState}
      </span>
      {p.docs
        .filter((d) => d.state === "pending" || d.stale)
        .map((d) => (
          <span key={d.doc_id} data-testid="doc-chip" className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-950">
            {d.state === "pending" ? `${d.doc_id}: preparing${d.waiting_for ? ` (${d.waiting_for})` : ""}` : `${d.doc_id}: re-scoring`}
          </span>
        ))}
    </section>
  );
}
