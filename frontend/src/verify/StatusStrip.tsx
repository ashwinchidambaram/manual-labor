import type { DocReadiness, QueueSort, ReviewCounts } from "../api/schema";
import Hint from "../onboarding/Hint";
import { MISMATCH, reconcileReview, reviewMismatchDetail, reviewReconcileText } from "../onboarding/reconcile";
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
  /** null until the project has loaded */
  threshold: number | null;
  view: number | null;
  sort: QueueSort;
  onView: (v: number | null) => void;
  onSort: (s: QueueSort) => void;
  saveState: string;
}

function Stat({ id, label, value, partial = false }: { id: string; label: string; value: number; partial?: boolean }) {
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-xs text-slate-600">{label}</span>
      <span className="text-lg font-semibold tabular-nums" data-testid={id}>
        {value}
        {partial ? "+" : ""}
      </span>
      {partial ? <span className="sr-only"> or more, not all pages are loaded</span> : null}
    </div>
  );
}

export default function StatusStrip(p: StatusStripProps) {
  // TODO(G1): the server will send `view_added` (auto-approved blocks the view filter lists). Until then:
  //  - no view filter: every pending block is queued, so `pending` is exact;
  //  - view filter and every page loaded: pending minus the loaded auto-approved rows is exact;
  //  - view filter and more pages exist: only a lower bound is known (pending minus ALL auto-approved), shown as "N+".
  const filtered = p.appliedView !== null;
  const queuedPartial = filtered && p.viewAddedPartial;
  const queued = Math.max(0, p.counts.pending - (!filtered ? 0 : queuedPartial ? p.counts.auto_approved : p.viewAdded));
  const T = p.threshold;
  const rec = reconcileReview(p.counts);
  return (
    <section aria-label="Review status" className="flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-slate-300 bg-white px-4 py-2">
      <Stat id="cnt-queued" label="Queued" value={queued} partial={queuedPartial} />
      <Stat id="cnt-auto" label="Auto-approved" value={p.counts.auto_approved} />
      <Stat id="cnt-flagged" label="Flagged" value={p.counts.flagged_open} />
      <Stat id="cnt-done" label="Done" value={p.counts.approved + p.counts.edited} />
      <Stat id="cnt-scope" label="In scope" value={p.counts.in_scope} />
      {T === null ? (
        <span className="text-sm text-slate-600" data-testid="view-copy">
          Loading the review threshold
        </span>
      ) : (
      <div className="flex items-center gap-2">
        <Hint id="viewSlider">
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
        </Hint>
        <span className="text-sm text-slate-700" data-testid="view-copy">
          {sliderCopy(p.view, T, p.viewAdded, p.viewAddedPartial, p.view !== p.appliedView)}
          {p.view !== null && p.view === p.appliedView && p.viewAddedPartial ? " (loaded)" : ""}
        </span>
        <button type="button" onClick={() => p.onView(1)} className={`rounded border border-slate-400 px-2 text-xs ${FOCUS}`}>
          Show all
        </button>
      </div>
      )}
      <label className="flex items-center gap-1 text-sm">
        <span className="sr-only">Sort</span>
        <Hint id="sort">
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
        </Hint>
      </label>
      <span className="ml-auto text-sm text-slate-700" data-testid="save-state" role="status">
        {p.saveState}
      </span>
      {rec.ok ? (
        <p className="basis-full text-xs tabular-nums text-slate-600" data-testid="reconcile-review">
          {reviewReconcileText(rec)}
          {rec.skipped > 0 ? ` (${rec.skipped} skipped)` : ""}
        </p>
      ) : (
        <p role="note" className="basis-full rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-950" data-testid="reconcile-mismatch">
          {MISMATCH(reviewMismatchDetail(rec))}
        </p>
      )}
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
