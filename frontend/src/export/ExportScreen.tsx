import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, client, unwrap } from "../api/client";
import { invalidateReviewCounts, qk, trackJob, useExportStatus } from "../api/queries";
import type { ExportStatus, ExportSummary, Override } from "../api/schema";
import { useJobWatch } from "../hooks/useJobsPolling";
import Hint from "../onboarding/Hint";
import { openInVerify } from "../shell/openInVerify";

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
const LINK = `text-blue-700 underline underline-offset-2 hover:text-blue-900 ${FOCUS}`;
const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;
const errText = (e: unknown): string => (e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e));

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} bytes`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function fmtTime(s: string): string {
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString();
}

/** The locked view: the gate's counts and the blocks behind them, each one link away (design 12 section 2.7). */
function Locked({ st }: { st: ExportStatus }) {
  const nav = useNavigate();
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const blockers = st.blockers ?? [];
  const queued = st.queued ?? 0;
  const open = async (id: string): Promise<void> => {
    setOpening(id);
    setError(null);
    try {
      await openInVerify(id);
      nav("/verify");
    } catch (e) {
      setError(`Could not open ${id}: ${errText(e)}`);
      setOpening(null);
    }
  };
  return (
    <section aria-labelledby="export-locked" data-testid="export-locked" className="space-y-4">
      <div>
        <h3 id="export-locked" className="text-lg font-semibold text-slate-950">
          Export is locked
        </h3>
        <p className="mt-1 max-w-prose text-sm text-slate-700">
          Why: the export only contains text a person or the checks have accepted. These must be resolved first, or overridden with a reason.
        </p>
      </div>
      <ul className="space-y-1.5 text-sm" data-testid="export-reasons">
        {st.open_flags > 0 ? (
          <li data-testid="reason-flags">
            <span className="font-semibold tabular-nums">{plural(st.open_flags, "open flag")}</span>: resolve on the{" "}
            <Link className={LINK} to="/agent">
              Agent screen
            </Link>{" "}
            or in{" "}
            <Link className={LINK} to="/verify">
              Verify
            </Link>
            .
          </li>
        ) : null}
        {queued > 0 ? (
          <li data-testid="reason-queued">
            <span className="font-semibold tabular-nums">{plural(queued, "block")}</span> still to review:{" "}
            <Link className={LINK} to="/verify">
              go to Verify
            </Link>
            .
          </li>
        ) : null}
      </ul>
      {blockers.length ? (
        <div>
          <h4 className="text-sm font-semibold text-slate-800">
            Blocking blocks{" "}
            <span className="font-normal text-slate-600">
              ({blockers.length < queued + st.open_flags ? `first ${blockers.length} listed by the server` : plural(blockers.length, "block")})
            </span>
          </h4>
          <ul className="mt-1 flex flex-wrap gap-1.5" data-testid="blocker-list">
            {blockers.map((id) => (
              <li key={id}>
                <a
                  href="/verify"
                  data-testid="blocker-link"
                  aria-label={`Open ${id} in Verify`}
                  aria-busy={opening === id}
                  onClick={(e) => {
                    e.preventDefault();
                    void open(id);
                  }}
                  className={`inline-block rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono text-xs text-blue-800 hover:border-blue-400 hover:bg-blue-50 ${FOCUS}`}
                >
                  {id}
                </a>
              </li>
            ))}
          </ul>
          {error ? (
            <p role="alert" className="mt-1 text-sm text-red-800">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function OverrideForm({ onDone }: { onDone: (st: ExportStatus) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rid] = useState(() => crypto.randomUUID());
  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (!reason.trim()) {
      setError("Please write why you are exporting without a review.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onDone(unwrap(await client.POST("/api/export/override", { body: { reason: reason.trim(), request_id: rid } })));
      setReason("");
    } catch (err) {
      setError(`Override not recorded: ${errText(err)}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-2 rounded border border-slate-300 bg-white p-3" data-testid="override-form" aria-labelledby="override-title">
      <h3 id="override-title" className="text-sm font-semibold text-slate-900">
        Export anyway
      </h3>
      <p className="max-w-prose text-sm text-slate-700">
        An override exports the blocking blocks with their machine-cleaned text, unreviewed. Each one is listed in manifest.json with your reason.
      </p>
      <label htmlFor="override-reason" className="block text-sm font-medium text-slate-800">
        Reason <span className="font-normal text-slate-600">(required)</span>
      </label>
      <Hint id="overrideReason">
        <textarea
          id="override-reason"
          data-testid="override-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          aria-invalid={error !== null}
          aria-describedby={error ? "override-error" : undefined}
          className={`block w-full max-w-xl rounded border border-slate-400 p-2 text-sm ${FOCUS}`}
        />
      </Hint>
      {error ? (
        <p id="override-error" role="alert" className="text-sm text-red-800">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={busy} data-testid="override-submit" className={`rounded border border-slate-500 bg-white px-3 py-1 text-sm hover:bg-slate-100 disabled:opacity-50 ${FOCUS}`}>
        {busy ? "Recording..." : "Record override"}
      </button>
    </form>
  );
}

function Overrides({ list }: { list: Override[] }) {
  if (!list.length) return null;
  return (
    <section aria-labelledby="overrides-title" data-testid="overrides">
      <h3 id="overrides-title" className="text-sm font-semibold text-slate-900">
        Active overrides <span className="font-normal text-slate-600">(recorded in manifest.json)</span>
      </h3>
      <ul className="mt-1 space-y-1 text-sm">
        {list.map((o, i) => (
          <li key={`${o.at}-${i}`} className="text-slate-800">
            <span className="text-slate-600">{fmtTime(o.at)}</span> · {o.target_id ? <span className="font-mono text-xs">{o.target_id}</span> : "every blocking block"}:{" "}
            <q>{o.reason}</q>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Summary({ s }: { s: ExportSummary }) {
  const rows: [string, string][] = [
    ["Articles", String(s.articles)],
    ["Figures", String(s.figures)],
    ["Pages covered", String(s.pages_covered)],
    ["Documents", String(s.docs)],
    ["Approved by you", String(s.review.approved)],
    ["Edited by you", String(s.review.edited)],
    ["Auto-approved", String(s.review.auto_approved)],
    ["Numbers verified by you", String(s.review.numbers_verified)],
    ["Overridden", String(s.review.overrides)],
    ["Zip size", fmtBytes(s.zip_bytes)],
  ];
  return (
    <section aria-labelledby="summary-title" data-testid="export-summary" className="space-y-2">
      <h3 id="summary-title" className="text-sm font-semibold text-slate-900">
        Last export <span className="font-normal text-slate-600">{fmtTime(s.generated_at)}</span>
      </h3>
      <dl className="grid max-w-md grid-cols-[1fr_auto] gap-x-6 gap-y-0.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-slate-700">{k}</dt>
            <dd className="text-right tabular-nums font-medium">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-slate-700">
        SHA-256 <span className="break-all font-mono" data-testid="export-sha">{s.zip_sha256}</span>
      </p>
      {(s.warnings ?? []).length ? (
        <ul role="note" className="list-disc space-y-0.5 pl-5 text-sm text-amber-900">
          {(s.warnings ?? []).map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      <a href="/api/export/download" download data-testid="export-download" className={`inline-block rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 ${FOCUS} focus-visible:ring-offset-2`}>
        Download zip
      </a>
    </section>
  );
}

export default function ExportScreen() {
  const qc = useQueryClient();
  const status = useExportStatus();
  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const job = useJobWatch(jobId);
  const st = status.data;
  const locked = !!st && (st.blockers ?? []).length > 0;
  const running = !!job.data && (job.data.status === "queued" || job.data.status === "running");

  const start = async (): Promise<void> => {
    setStarting(true);
    setStartError(null);
    try {
      const j = unwrap(await client.POST("/api/export", { body: { request_id: crypto.randomUUID() } }));
      trackJob(qc, j);
      setJobId(j.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.code === "export_locked") {
        // the gate closed since the status was read: show the locked view from the refusal itself
        const b = (e.body ?? {}) as { open_flags?: number; queued?: number; blockers?: string[] };
        qc.setQueryData<ExportStatus>(qk.exportStatus, (old) => ({
          overrides: [],
          ...old,
          unlocked: false,
          open_flags: b.open_flags ?? old?.open_flags ?? 0,
          queued: b.queued ?? old?.queued ?? 0,
          blockers: b.blockers ?? old?.blockers ?? [],
        }));
      } else setStartError(`Export not started: ${errText(e)}`);
    } finally {
      setStarting(false);
    }
  };

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-testid="export-screen">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold">Export</h2>
        <Link className={`text-sm ${LINK}`} to="/scope">
          Back to Scope
        </Link>
      </div>
      {status.isLoading ? (
        <div aria-busy="true" className="h-24 animate-pulse rounded bg-slate-200" />
      ) : status.isError ? (
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          Could not read the export status: {errText(status.error)}{" "}
          <button type="button" onClick={() => void status.refetch()} className={`ml-1 rounded border border-red-400 px-2 ${FOCUS}`}>
            Retry
          </button>
        </div>
      ) : st ? (
        <>
          {locked ? (
            <>
              <Locked st={st} />
              <OverrideForm
                onDone={(next) => {
                  qc.setQueryData(qk.exportStatus, next);
                  invalidateReviewCounts(qc);
                }}
              />
            </>
          ) : (
            <section aria-labelledby="export-ready" data-testid="export-ready" className="space-y-2">
              <h3 id="export-ready" className="text-lg font-semibold text-slate-950">
                Ready to export
              </h3>
              <p className="max-w-prose text-sm text-slate-700">
                {st.unlocked
                  ? "No flag is open and nothing in scope is waiting for review."
                  : "Overrides cover every remaining block; they will be exported unreviewed and listed in manifest.json."}{" "}
                The zip contains the articles, their figures, manifest.json and a README.
              </p>
              <Hint id="exportButton">
                <button
                  type="button"
                  onClick={() => void start()}
                  disabled={starting || running}
                  data-testid="export-start"
                  className={`rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-400 ${FOCUS} focus-visible:ring-offset-2`}
                >
                  {running ? "Exporting..." : "Export knowledge base"}
                </button>
              </Hint>
              {running ? (
                <p role="status" className="text-sm text-slate-700">
                  Building the export. Progress is shown in the jobs bar; you can leave this screen.
                </p>
              ) : null}
              {job.data?.status === "failed" ? (
                <p role="alert" className="text-sm text-red-800">
                  Export failed: {job.data.error ?? job.data.message ?? "no details"}
                </p>
              ) : null}
              {startError ? (
                <p role="alert" className="text-sm text-red-800">
                  {startError}
                </p>
              ) : null}
            </section>
          )}
          <Overrides list={st.overrides ?? []} />
          {st.summary ? <Summary s={st.summary} /> : null}
        </>
      ) : null}
    </main>
  );
}
