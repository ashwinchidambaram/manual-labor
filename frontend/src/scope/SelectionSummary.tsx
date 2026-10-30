import type { ScopeSummary } from "../api/schema";

function Stat({ id, label, value }: { id: string; label: string; value: number }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-0.5">
      <dt className="text-ink">{label}</dt>
      <dd className="font-bold tabular-nums text-ink" data-testid={id}>
        {value}
      </dd>
    </div>
  );
}

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

/** "What you will get": the server's counts for the current selection, and the estimated review as a sentence. */
export default function SelectionSummary({ summary, processing }: { summary: ScopeSummary; processing: number }) {
  const r = summary.review_load;
  // the rest of the estimate are blocks that scored under the line: the server's queued minus its numeric_queued
  const rest = r.queued - r.numeric_queued;
  return (
    <section
      aria-label="What you will get"
      data-zone="summary"
      tabIndex={0}
      className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-4"
      data-testid="selection-summary"
    >
      <h2 className="mb-2 text-lg font-semibold text-ink">What you will get</h2>
      <dl className="text-base" aria-live="polite">
        <Stat id="sum-articles" label="Articles" value={summary.articles} />
        <Stat id="sum-blocks" label="Blocks" value={summary.blocks} />
        <Stat id="sum-figures" label="Figures" value={summary.figures} />
        <Stat id="sum-pages" label="Pages" value={summary.pages} />
        <Stat id="sum-docs" label="Documents" value={summary.docs} />
      </dl>
      <div className="mt-4 rounded-xl bg-needs-wash px-4 py-3.5">
        <p className="text-base font-semibold text-ink">
          Estimated review:{" "}
          <span className="tabular-nums" data-testid="sum-queued">
            {r.queued}
          </span>{" "}
          {r.queued === 1 ? "block" : "blocks"}
        </p>
        <p className="mt-1 text-sm leading-snug text-needs-ink">
          <span className="tabular-nums" data-testid="sum-numeric">
            {r.numeric_queued}
          </span>{" "}
          {r.numeric_queued === 1 ? "contains" : "contain"} numbers, which a person always checks
          {rest > 0 ? (
            <>
              ; the other {plural(rest, "block")} scored under <span className="tabular-nums">{r.threshold.toFixed(2)}</span>, the auto-approve line.
            </>
          ) : (
            "."
          )}
        </p>
      </div>
      {processing > 0 ? (
        <p className="mt-2 text-xs font-medium text-needs-ink" data-testid="docs-processing">
          {processing} document{processing === 1 ? "" : "s"} still processing
        </p>
      ) : null}
      {processing > 0 ? (
        <p className="mt-0.5 text-xs text-muted" data-testid="docs-processing-hint">
          You can choose topics as soon as a document is ready.
        </p>
      ) : null}
    </section>
  );
}
