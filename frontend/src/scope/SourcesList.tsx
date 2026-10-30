import { useRef } from "react";
import { useRerun, useUploadSources } from "../api/queries";
import type { JobInfo, ProjectStatus, SourceInfo } from "../api/schema";
import Hint from "../onboarding/Hint";

/** The stages Scope is responsible for. `clean` and `score2` run when the scope is confirmed, so on
 *  this screen they are legitimately missing after an upload and are not "open" here. */
export const SCOPE_STAGES: ReadonlySet<string> = new Set(["ingest", "parse", "figures", "score", "group"]);

/** Whether a queued or running job will touch this manual. `JobInfo.doc` is only the document of
 *  the last progress event (null while queued), so the plan's document list is what counts. */
export function jobCovers(j: JobInfo, slug: string): boolean {
  const docs = (j.plan as { docs?: unknown } | undefined)?.docs;
  if (Array.isArray(docs) && docs.length) return docs.includes(slug);
  return true; // no document filter: a project-wide plan
}

export function openScopeStage(s: SourceInfo): { node: string; state: string } | undefined {
  return s.nodes.find((n) => SCOPE_STAGES.has(n.node) && (n.state === "stale" || n.state === "missing"));
}

export function sourceChip(s: SourceInfo, jobs: readonly JobInfo[]): { text: string; tone: "ok" | "busy" | "bad" } {
  const failed = s.nodes.find((n) => n.state === "failed");
  if (failed) return { text: `Failed: ${failed.node}`, tone: "bad" };
  const busy = jobs.some((j) => jobCovers(j, s.slug));
  const open = openScopeStage(s);
  if (busy) return { text: `Processing ${(open ?? s.nodes.find((n) => n.state !== "fresh"))?.node ?? jobs.find((j) => jobCovers(j, s.slug))?.node ?? ""}`.trim(), tone: "busy" };
  // Nothing is running: say so. "Processing" with no job would leave a CLI user waiting forever.
  if (open) return { text: `${open.state === "missing" ? "Not run yet" : "Needs a run"}: ${open.node}`, tone: "busy" };
  return { text: "Ready", tone: "ok" };
}

const TONE = {
  ok: "text-done-ink",
  busy: "text-needs-ink",
  bad: "text-fail",
};
const MARK = { ok: "✓", busy: "◔", bad: "✕" };
const KIND: Record<string, string> = { born_digital_pdf: "Text PDF", scanned_pdf: "Scanned PDF", docx: "Word document" };
const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";

export function UploadButton({ label = "Add documents" }: { label?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const upload = useUploadSources();
  return (
    <>
      <input
        ref={input}
        type="file"
        multiple
        accept=".pdf,.docx"
        className="sr-only"
        tabIndex={-1}
        aria-label="Choose documents"
        data-testid="upload-input"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) upload.mutate(files);
          e.target.value = "";
        }}
      />
      <Hint id="addDocuments">
        <button
          type="button"
          onClick={() => input.current?.click()}
          className={`min-h-[2.25rem] rounded-lg border border-line bg-raised px-3 text-sm font-medium text-ink hover:bg-sunk ${FOCUS}`}
        >
          {label}
        </button>
      </Hint>
      {upload.isError ? (
        <p role="alert" className="text-xs text-fail">
          {upload.error.message}
        </p>
      ) : null}
    </>
  );
}

export default function SourcesList({
  sources,
  status,
  jobs,
  onGoTo,
}: {
  sources: SourceInfo[];
  status: ProjectStatus | undefined;
  jobs: readonly JobInfo[];
  onGoTo: (slug: string) => void;
}) {
  const rerun = useRerun();
  // The button posts a plan up to `group`, so only Scope's stages can make it appear (§9 of design 08).
  const needsRerun = sources.some((s) => s.nodes.some((n) => SCOPE_STAGES.has(n.node) && (n.state === "stale" || n.state === "failed")));
  // Ingested from the CLI and never run: the stages are "missing" and no job exists. Offer to run it.
  const neverRun = jobs.length === 0 && sources.some((s) => openScopeStage(s)?.state === "missing");
  const onKeyDown = (e: React.KeyboardEvent<HTMLUListElement>): void => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>("button[data-source]"));
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (i < 0) return;
    e.preventDefault();
    items[Math.min(items.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))].focus();
  };
  return (
    <section aria-label="Sources" data-zone="sources" data-testid="sources">
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <h3 className="text-2xs font-semibold uppercase tracking-[0.07em] text-muted">Your manuals</h3>
        <UploadButton />
      </div>
      <ul className="grid gap-px overflow-hidden rounded-xl border border-line bg-line-soft [grid-template-columns:repeat(auto-fit,minmax(13.5rem,1fr))]" onKeyDown={onKeyDown}>
        {sources.map((s, i) => {
          const chip = sourceChip(s, jobs);
          return (
            <li key={s.slug} className="flex flex-col bg-raised" data-testid="source-row" data-slug={s.slug}>
              <button
                type="button"
                data-source={s.slug}
                tabIndex={i === 0 ? 0 : -1}
                onClick={() => onGoTo(s.slug)}
                className={`w-full px-4 pb-2 pt-3 text-left hover:bg-sunk focus-visible:ring-inset ${FOCUS}`}
              >
                <span className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-base font-semibold text-ink" title={s.filename}>
                    {s.filename}
                  </span>
                  <span className={`flex shrink-0 items-baseline gap-1 text-xs font-semibold ${TONE[chip.tone]}`}>
                    <span aria-hidden="true">{MARK[chip.tone]}</span>
                    <span data-testid="source-chip">{chip.text}</span>
                  </span>
                </span>
                <span className="mt-0.5 block text-xs text-muted">
                  {s.kind === "scanned_pdf" ? (
                    <span data-testid="scanned-badge">Scanned PDF</span>
                  ) : (
                    KIND[s.kind] ?? s.kind.replace(/_/g, " ")
                  )}
                  {" · "}
                  {s.pages} page{s.pages === 1 ? "" : "s"}
                </span>
              </button>
              {s.ocr_warning ? (
                <p role="note" className="mx-4 mb-3 flex gap-2 text-xs leading-snug text-ink" data-testid="ocr-warning">
                  <span aria-hidden="true" className="text-act-ink">
                    ◐
                  </span>
                  <span>
                    <strong className="font-semibold">Read from scans.</strong> OCR: {s.ocr_warning}, so more of this manual will come to you to check.
                  </span>
                </p>
              ) : null}
            </li>
          );
        })}
        {(status?.unregistered_sources ?? []).map((f) => (
          <li key={f} className="bg-raised px-4 py-3 text-sm text-muted" data-testid="unregistered">
            {f}: Not ingested
          </li>
        ))}
      </ul>
      {needsRerun || neverRun ? (
        <button
          type="button"
          onClick={() => rerun.mutate()}
          disabled={jobs.length > 0}
          className={`mt-2 min-h-[2.25rem] rounded-lg border border-line bg-raised px-3 text-sm font-medium hover:bg-sunk disabled:opacity-50 ${FOCUS}`}
        >
          {needsRerun ? "Re-run" : "Run"}
        </button>
      ) : null}
    </section>
  );
}
