import type { DocReadiness, QueueSort, ReviewCounts } from "../api/schema";
import Hint from "../onboarding/Hint";
import { MISMATCH, reconcileReview, reviewMismatchDetail, reviewReconcileText } from "../onboarding/reconcile";
import { FOCUS } from "./labels";
import { normalizeView, sliderCopy } from "./sliderCopy";

const SORTS: { id: QueueSort; label: string }[] = [
  { id: "worst_first", label: "Most doubtful first" },
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

function Stat({ id, label, value, partial = false, swatch }: { id: string; label: string; value: number; partial?: boolean; swatch: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span aria-hidden="true" className={`inline-block h-2.5 w-2.5 translate-y-[1px] rounded-[3px] ${swatch}`} />
      <span className="text-sm font-bold tabular-nums text-ink" data-testid={id}>
        {value}
        {partial ? "+" : ""}
      </span>
      {partial ? <span className="sr-only"> or more, not all pages are loaded</span> : null}
      <span className="text-sm text-muted">{label}</span>
    </span>
  );
}

/** One segment of the bar: a full-width layer scaled from the left, so a change animates on transform only. */
function Segment({ start, size, className }: { start: number; size: number; className: string }) {
  return (
    <span
      aria-hidden="true"
      className={`absolute inset-y-0 left-0 w-full origin-left transition-transform duration-200 ease-out-quart ${className}`}
      style={{ transform: `translateX(${start * 100}%) scaleX(${size})` }}
    />
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
  const c = p.counts;
  const done = c.approved + c.edited;
  // the bar is drawn from the server's independent buckets over in scope (owner decision D1a); the legend says each in words
  const total = Math.max(1, c.in_scope);
  const segs = [
    { key: "done", n: done, cls: "bg-done-mid" },
    { key: "auto", n: c.auto_approved, cls: "hatch-cleared" },
    { key: "flagged", n: c.flagged_open + c.rejected, cls: "hatch-flag" },
  ];
  let at = 0;
  const yours = done + c.queued + c.flagged_open + c.rejected;
  return (
    <section aria-label="Review status" className="flex shrink-0 flex-col gap-2 border-b border-line bg-raised px-4 py-3 wide:px-7">
        <div
          role="img"
          aria-label={`${done} of ${yours} checked by you, ${c.auto_approved} cleared by the checks, ${c.queued} waiting for you, ${c.flagged_open} flagged, ${c.in_scope} in scope`}
          className="relative h-3 overflow-hidden rounded-full bg-needs-fill shadow-[inset_0_0_0_1px_var(--needs-line)]"
          data-testid="review-bar"
        >
          {segs.map((s) => {
            const start = at / total;
            at += s.n;
            return <Segment key={s.key} start={start} size={s.n / total} className={s.cls} />;
          })}
        </div>
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
          <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 translate-y-[1px] rounded-[3px] bg-done-mid" />
            <span className="text-sm font-bold tabular-nums text-ink" data-testid="cnt-done">
              {done}
            </span>
            <span className="text-sm text-muted">
              of <span className="tabular-nums">{yours}</span> checked by you
            </span>
          </span>
          <Stat id="cnt-auto" label="cleared by the checks" value={c.auto_approved} swatch="hatch-cleared ring-1 ring-inset ring-done-mid" />
          <Stat id="cnt-queued" label="waiting for you" value={queued} partial={queuedPartial} swatch="bg-needs-fill ring-1 ring-inset ring-needs-line" />
          <Stat id="cnt-flagged" label="flagged" value={c.flagged_open} swatch="hatch-flag" />
          <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
            <span className="text-sm font-bold tabular-nums text-ink" data-testid="cnt-scope">
              {c.in_scope}
            </span>
            <span className="text-sm text-muted">in scope</span>
          </span>
        </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        {T === null ? (
          <span className="text-muted" data-testid="view-copy">
            Loading the review threshold
          </span>
        ) : (
          <div className="flex flex-wrap items-center gap-2.5">
            <Hint id="viewSlider">
              <input
                type="range"
                aria-label="Also review auto-approved blocks below"
                min={T}
                max={1}
                step={0.01}
                value={p.view ?? T}
                onChange={(e) => p.onView(normalizeView(Number(e.target.value), T))}
                className={`w-28 accent-[var(--act)] ${FOCUS}`}
              />
            </Hint>
            <span className="text-muted" data-testid="view-copy">
              {sliderCopy(p.view, T, p.viewAdded, p.viewAddedPartial, p.view !== p.appliedView)}
              {p.view !== null && p.view === p.appliedView && p.viewAddedPartial ? " (loaded)" : ""}
            </span>
            <button type="button" onClick={() => p.onView(1)} className={`min-h-[2rem] rounded-lg border border-line px-2.5 text-xs font-medium text-ink hover:bg-sunk ${FOCUS}`}>
              Show all
            </button>
          </div>
        )}
        <label className="flex items-center gap-1">
          <span className="sr-only">Sort</span>
          <Hint id="sort">
            <select
              aria-label="Sort"
              value={p.sort}
              onChange={(e) => p.onSort(e.target.value as QueueSort)}
              className={`min-h-[2.25rem] rounded-lg border border-line-strong bg-raised px-2.5 text-sm text-ink ${FOCUS}`}
            >
              {SORTS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </Hint>
        </label>
        <span className="inline-flex items-center gap-1 text-sm font-semibold text-done-ink" role="status">
          <span aria-hidden="true">{p.saveState === "Saved" ? "✓" : p.saveState === "Not saved" ? "✕" : "◔"}</span>
          <span data-testid="save-state" className={p.saveState === "Not saved" ? "text-fail" : p.saveState === "Saved" ? "" : "text-muted"}>
            {p.saveState}
          </span>
        </span>
      </div>
      </div>
        {rec.ok ? (
          <p className="text-xs tabular-nums text-muted" data-testid="reconcile-review">
            {reviewReconcileText(rec)}
            {rec.skipped > 0 ? ` (${rec.skipped} skipped)` : ""}
          </p>
        ) : (
          <p role="note" className="text-xs font-medium text-fail" data-testid="reconcile-mismatch">
            <span aria-hidden="true">✕ </span>
            {MISMATCH(reviewMismatchDetail(rec))}
          </p>
        )}
        {p.docs
          .filter((d) => d.state === "pending" || d.stale)
          .map((d) => (
            <span key={d.doc_id} data-testid="doc-chip" className="mr-2 mt-1 inline-block rounded-full bg-needs-wash px-2 py-px text-2xs font-semibold text-needs-ink">
              {d.state === "pending" ? `${d.doc_id}: preparing${d.waiting_for ? ` (${d.waiting_for})` : ""}` : `${d.doc_id}: re-scoring`}
            </span>
          ))}
      
    </section>
  );
}
