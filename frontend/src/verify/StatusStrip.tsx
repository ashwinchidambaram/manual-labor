import { useState } from "react";
import { Link } from "react-router-dom";
import type { DocReadiness, QueueSort, ReviewCounts } from "../api/schema";
import Hint from "../onboarding/Hint";
import { MISMATCH } from "../onboarding/reconcile";
import { scopeEquation, scopeMismatch, stripTerms, type ScopeTerms } from "../shell/scopeTerms";
import { STAGE_WORDS } from "../shell/jobStep";
import { FOCUS } from "./labels";
import { normalizeView, sliderCopy } from "./sliderCopy";

const SORTS: { id: QueueSort; label: string }[] = [
  { id: "worst_first", label: "Most doubtful first" },
  { id: "by_page", label: "By page" },
  { id: "figures_only", label: "Figures only" },
];

export interface StatusStripProps {
  counts: ReviewCounts;
  /**
   * The export gate's partition (`shell/scopeTerms`, design 11 section 17): what the rail and the next-step card read.
   * Combined with the list's own `counts` by `stripTerms`: the gate's terms when both reads agree, the list's buckets
   * with the gate's overrides kept apart after a write the gate has not seen yet, the list's counts alone when the scope
   * differs (a document scored between the two reads).
   */
  scope?: ScopeTerms | null;
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
  /** why the review estimate moved when a job finished ("2 more blocks queued after scoring finished"), or null */
  change?: string | null;
  /** a queued or running job will prepare this document; a pending document no job covers is "not scored yet" */
  busy?: (doc: string) => boolean;
  /** a job re-scores this document now (not a reading job); a stale document with none is "scores out of date" */
  rescoring?: (doc: string) => boolean;
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
  const t: ScopeTerms = stripTerms(p.scope, p.counts);
  const fromGate = t.source === "export" || t.overridden > 0;
  const filtered = p.appliedView !== null;
  const queuedPartial = !fromGate && filtered && p.viewAddedPartial;
  // the gate's `to_review` is exact; the queue's fallback derives it from the list as before
  const queued = fromGate ? t.toReview : Math.max(0, p.counts.pending - (!filtered ? 0 : queuedPartial ? p.counts.auto_approved : p.viewAdded));
  const T = p.threshold;
  const done = t.done;
  // on a short window (200% zoom) the block folds to the bar and one line; the rest is one button away
  const [details, setDetails] = useState(false);
  // The bar is drawn from the server's independent buckets over in scope (owner decision D1a), every segment from its
  // own count, so the bar adds up only when the counts do. When they do not, it is drawn empty (grey) and the line
  // under it says why: a bar that "fills" with whatever is left would hide the mismatch.
  const total = Math.max(1, t.inScope);
  const flaggedN = t.flagged + t.rejected;
  const flagWords = t.rejected > 0 ? `${flaggedN} flagged or rejected` : `${t.flagged} flagged`;
  const segs = t.ok
    ? [
        { key: "done", n: done, cls: "bg-done-mid" },
        { key: "auto", n: t.auto, cls: "hatch-cleared" },
        { key: "flagged", n: flaggedN, cls: "hatch-flag" },
        // overridden: will be exported unreviewed; neither cleared nor waiting (design 11 section 17)
        ...(t.overridden > 0 ? [{ key: "overridden", n: t.overridden, cls: "hatch-overridden" }] : []),
        { key: "queued", n: t.toReview, cls: "bg-needs-fill" },
      ]
    : [];
  let at = 0;
  const yours = done + t.toReview + t.overridden + t.flagged + t.rejected;
  const overriddenWords = t.overridden > 0 ? `, ${t.overridden} overridden and not reviewed` : "";
  // Work is claimed only while a job does it (CLAUDE.md "Claiming work is happening"): a pending document no job covers
  // is "not scored yet", a stale one no job re-scores is "scores out of date", and both point at Scope.
  const chips = p.docs
    .filter((d) => d.state === "pending" || d.stale)
    .map((d) => {
      const working = d.state === "pending" ? !!p.busy?.(d.doc_id) : !!p.rescoring?.(d.doc_id);
      const text =
        d.state === "pending"
          ? working
            ? `${d.doc_id}: preparing${d.waiting_for ? ` (${(STAGE_WORDS[d.waiting_for] ?? d.waiting_for).toLowerCase()})` : ""}`
            : `${d.doc_id}: not scored yet`
          : working
            ? `${d.doc_id}: re-scoring`
            : `${d.doc_id}: scores out of date`;
      return { doc: d.doc_id, text, working };
    });
  const idle = chips.filter((x) => !x.working).length;
  return (
    <section aria-label="Review status" className="flex shrink-0 flex-col gap-2 border-b border-line bg-raised px-4 py-3 low:gap-1.5 low:py-2 wide:px-7">
      <div className="flex items-center gap-3">
        <div
          role="img"
          aria-label={
            t.ok
              ? `${done} of ${yours} checked by you, ${t.auto} cleared by the checks, ${t.toReview} waiting for you${overriddenWords}, ${flagWords}, ${t.inScope} in scope`
              : `Progress not drawn: the review counts do not add up to the ${t.inScope} in scope`
          }
          className="relative h-3 min-w-0 flex-1 overflow-hidden rounded-full bg-line-soft shadow-[inset_0_0_0_1px_var(--line)] short:min-w-[5rem]"
          data-testid="review-bar"
          data-reconciled={t.ok ? "true" : "false"}
        >
          {segs.map((s) => {
            const start = at / total;
            at += s.n;
            return <Segment key={s.key} start={start} size={s.n / total} className={s.cls} />;
          })}
        </div>
        {/* on a short window the totals note joins this one line (cut to fit, whole in its title and under the details) */}
        <p className="hidden min-w-0 truncate whitespace-nowrap text-sm text-muted short:block" data-testid="review-summary" title={p.change ?? undefined}>
          <span className="font-bold tabular-nums text-ink">{done}</span> of <span className="tabular-nums">{yours}</span> checked by you
          {p.saveState !== "Saved" ? <span className={p.saveState === "Not saved" ? "font-semibold text-fail" : ""}> · {p.saveState}</span> : null}
          {p.change ? (
            <span aria-hidden="true" className="text-needs-ink">
              {" "}
              · {p.change}
            </span>
          ) : null}
        </p>
        <button
          type="button"
          aria-expanded={details}
          aria-controls="review-details"
          onClick={() => setDetails((d) => !d)}
          className={`hidden min-h-[1.75rem] shrink-0 rounded-lg border border-line px-2 text-xs font-medium text-ink hover:bg-sunk short:inline-block ${FOCUS}`}
        >
          {details ? "Fewer details" : "Counts and filters"}
        </button>
      </div>
      <div id="review-details" className={`flex flex-col gap-2 ${details ? "" : "short:hidden"}`}>
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
          <Stat id="cnt-auto" label="cleared by the checks" value={t.auto} swatch="hatch-cleared ring-1 ring-inset ring-done-mid" />
          <Stat id="cnt-queued" label="waiting for you" value={queued} partial={queuedPartial} swatch="bg-needs-fill ring-1 ring-inset ring-needs-line" />
          {t.overridden > 0 ? (
            <Stat id="cnt-overridden" label="overridden, not reviewed" value={t.overridden} swatch="hatch-overridden ring-1 ring-inset ring-line-strong" />
          ) : null}
          <Stat id="cnt-flagged" label="flagged" value={t.flagged} swatch="hatch-flag" />
          {t.rejected > 0 ? (
            <span className="-ml-3 inline-flex items-baseline gap-1.5 whitespace-nowrap text-sm text-muted">
              and
              <span className="font-bold tabular-nums text-ink" data-testid="cnt-rejected">
                {t.rejected}
              </span>
              rejected
            </span>
          ) : null}
          <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
            <span className="text-sm font-bold tabular-nums text-ink" data-testid="cnt-scope">
              {t.inScope}
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
        {t.ok ? (
          <p className="text-xs tabular-nums text-muted" data-testid="reconcile-review">
            {scopeEquation(t)}
            {p.counts.skipped > 0 ? ` (${p.counts.skipped} skipped)` : ""}
          </p>
        ) : (
          <p role="note" className="text-xs font-medium text-fail" data-testid="reconcile-mismatch">
            <span aria-hidden="true">✕ </span>
            {MISMATCH(scopeMismatch(t))}
          </p>
        )}
        {chips.map((c) => (
          <span key={c.doc} data-testid="doc-chip" className="mr-2 mt-1 inline-block rounded-full bg-needs-wash px-2 py-px text-2xs font-semibold text-needs-ink">
            {c.text}
          </span>
        ))}
        {idle ? (
          <Link
            to="/scope"
            className={`mt-1 inline-block text-2xs font-medium text-act-ink underline underline-offset-2 hover:text-act-hover ${FOCUS}`}
          >
            {idle === 1 ? "Score it on Scope" : "Score them on Scope"}
          </Link>
        ) : null}
      </div>
      {/* Mounted with the strip and only its text changes, so a moved total is announced (a status node inserted together
          with its text often is not). The visible note below repeats it, and folds into the summary line when short. */}
      <p role="status" className="sr-only" data-testid="review-change-live">
        {p.change ?? ""}
      </p>
      {p.change ? (
        <p aria-hidden="true" className={`text-xs text-needs-ink ${details ? "" : "short:hidden"}`} data-testid="review-change">
          {p.change}
        </p>
      ) : null}
    </section>
  );
}
