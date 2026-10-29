import { useRef } from "react";
import { useRerun, useUploadSources } from "../api/queries";
import type { JobInfo, ProjectStatus, SourceInfo } from "../api/schema";

export function sourceChip(s: SourceInfo, jobs: readonly JobInfo[]): { text: string; tone: "ok" | "busy" | "bad" } {
  const failed = s.nodes.find((n) => n.state === "failed");
  if (failed) return { text: `Failed: ${failed.node}`, tone: "bad" };
  const busy = jobs.some((j) => j.doc === s.slug);
  const open = s.nodes.find((n) => n.state === "stale" || n.state === "missing");
  if (open || busy) return { text: `Processing ${(open ?? s.nodes.find((n) => n.state !== "fresh"))?.node ?? jobs.find((j) => j.doc === s.slug)?.node ?? ""}`.trim(), tone: "busy" };
  return { text: "Ready", tone: "ok" };
}

const TONE = {
  ok: "bg-green-100 text-green-900",
  busy: "bg-sky-100 text-sky-900",
  bad: "bg-red-100 text-red-900",
};
const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";

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
      <button
        type="button"
        onClick={() => input.current?.click()}
        className={`rounded border border-slate-400 bg-white px-2 py-1 text-sm hover:bg-slate-100 ${FOCUS}`}
      >
        {label}
      </button>
      {upload.isError ? (
        <p role="alert" className="text-xs text-red-800">
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
  const needsRerun = sources.some((s) => s.nodes.some((n) => n.state === "stale" || n.state === "failed"));
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
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Sources</h2>
        <UploadButton />
      </div>
      <ul className="flex flex-col gap-1" onKeyDown={onKeyDown}>
        {sources.map((s, i) => {
          const chip = sourceChip(s, jobs);
          return (
            <li key={s.slug} className="rounded border border-slate-300 bg-white" data-testid="source-row" data-slug={s.slug}>
              <button
                type="button"
                data-source={s.slug}
                tabIndex={i === 0 ? 0 : -1}
                onClick={() => onGoTo(s.slug)}
                className={`w-full px-2 py-1 text-left ${FOCUS}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium" title={s.filename}>
                    {s.filename}
                  </span>
                  <span className={`shrink-0 rounded px-1.5 text-xs ${TONE[chip.tone]}`} data-testid="source-chip">
                    {chip.text}
                  </span>
                </div>
                <div className="text-xs text-slate-600">
                  <span className="mr-2 rounded bg-slate-100 px-1">{s.kind.replace(/_/g, " ")}</span>
                  {s.pages} page{s.pages === 1 ? "" : "s"}
                  {s.kind === "scanned_pdf" ? (
                    <span className="ml-2 rounded bg-amber-100 px-1 text-amber-900" data-testid="scanned-badge">
                      Scanned: OCR text
                    </span>
                  ) : null}
                </div>
              </button>
              {s.ocr_warning ? (
                <p role="note" className="px-2 pb-1 text-xs text-amber-900" data-testid="ocr-warning">
                  OCR: {s.ocr_warning}
                </p>
              ) : null}
            </li>
          );
        })}
        {(status?.unregistered_sources ?? []).map((f) => (
          <li key={f} className="rounded border border-dashed border-slate-300 px-2 py-1 text-sm text-slate-600" data-testid="unregistered">
            {f}: Not ingested
          </li>
        ))}
      </ul>
      {needsRerun ? (
        <button
          type="button"
          onClick={() => rerun.mutate()}
          disabled={jobs.length > 0}
          className={`mt-2 rounded border border-slate-400 bg-white px-2 py-1 text-sm hover:bg-slate-100 disabled:opacity-50 ${FOCUS}`}
        >
          Re-run
        </button>
      ) : null}
    </section>
  );
}
