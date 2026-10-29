import type { ScopeSummary } from "../api/schema";

function Stat({ id, label, value }: { id: string; label: string; value: number }) {
  return (
    <div className="flex justify-between gap-4">
      <dt>{label}</dt>
      <dd className="tabular-nums font-semibold" data-testid={id}>
        {value}
      </dd>
    </div>
  );
}

export default function SelectionSummary({ summary, processing }: { summary: ScopeSummary; processing: number }) {
  const r = summary.review_load;
  return (
    <section
      aria-label="What you will get"
      data-zone="summary"
      tabIndex={0}
      className="rounded border border-slate-300 bg-white p-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
      data-testid="selection-summary"
    >
      <h2 className="mb-1 text-sm font-semibold">What you will get</h2>
      <dl className="text-sm" aria-live="polite">
        <Stat id="sum-articles" label="Articles" value={summary.articles} />
        <Stat id="sum-docs" label="Documents" value={summary.docs} />
        <Stat id="sum-blocks" label="Blocks" value={summary.blocks} />
        <Stat id="sum-figures" label="Figures" value={summary.figures} />
        <Stat id="sum-pages" label="Pages" value={summary.pages} />
      </dl>
      <p className="mt-2 text-sm text-slate-700">
        Estimated review:{" "}
        <span className="tabular-nums font-semibold" data-testid="sum-queued">
          {r.queued}
        </span>{" "}
        blocks (<span data-testid="sum-numeric">{r.numeric_queued}</span> with numeric specs) under threshold{" "}
        <span className="tabular-nums">{r.threshold}</span>
      </p>
      {processing > 0 ? (
        <p className="mt-1 text-xs text-amber-800" data-testid="docs-processing">
          {processing} document{processing === 1 ? "" : "s"} still processing
        </p>
      ) : null}
    </section>
  );
}
