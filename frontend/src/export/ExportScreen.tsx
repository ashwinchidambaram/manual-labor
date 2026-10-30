import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, client, unwrap } from "../api/client";
import { invalidateReviewCounts, qk, trackJob, useExportStatus } from "../api/queries";
import type { ExportStatus, ExportSummary, Override } from "../api/schema";
import { useJobWatch } from "../hooks/useJobsPolling";
import Hint from "../onboarding/Hint";
import { useBlockTitles } from "../shell/blockTitles";
import { AttentionIcon } from "../shell/Icon";
import { openInVerify } from "../shell/openInVerify";

/** The server lists at most this many blockers (manuallabor/export/types.py BLOCKER_LIMIT). */
export const BLOCKER_LIMIT = 20;
const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";
const LINK = `font-medium text-act-ink underline underline-offset-2 hover:text-act-hover ${FOCUS}`;
const BTN = `inline-flex min-h-[2.5rem] items-center rounded-xl border border-line-strong bg-raised px-4 text-sm font-semibold text-ink hover:bg-sunk disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS} focus-visible:ring-offset-2`;
const PRIMARY = `inline-flex min-h-[2.75rem] items-center rounded-xl bg-act px-5 text-base font-semibold text-act-on transition-colors duration-150 ease-out-quart hover:bg-act-hover disabled:cursor-not-allowed disabled:bg-line disabled:text-muted ${FOCUS} focus-visible:ring-offset-2`;
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
  const { titles, ready: titlesReady } = useBlockTitles(blockers.length > 0);
  const truncated = blockers.length >= BLOCKER_LIMIT;
  // consecutive blockers from the same section form one group: the server's order (and every id) is kept
  const groups: { key: string; title: string | null; ids: string[] }[] = [];
  for (const id of blockers) {
    const t = titles.get(id);
    const key = t ? `${t.doc}\u0000${t.title}` : "";
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.ids.push(id);
    else groups.push({ key, title: t ? t.title : null, ids: [id] });
  }
  return (
    <section aria-labelledby="export-locked" data-testid="export-locked" className="space-y-5">
      <div className="flex gap-4">
        <span aria-hidden="true" className="mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-needs-wash text-lg text-needs-ink">
          <AttentionIcon />
        </span>
        <div>
          <h3 id="export-locked" className="text-xl font-semibold text-ink">
            Export is locked
          </h3>
          <p className="mt-1 max-w-[62ch] text-base text-muted">
            Why: the export only contains text a person or the checks have accepted. These must be resolved first, or overridden with a reason.
          </p>
        </div>
      </div>
      <ul className="space-y-2 text-base" data-testid="export-reasons">
        {st.open_flags > 0 ? (
          <li data-testid="reason-flags" className="rounded-xl bg-raised px-4 py-3 ring-1 ring-inset ring-line">
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
          <li data-testid="reason-queued" className="rounded-xl bg-needs-wash px-4 py-3">
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
          <h4 className="text-sm font-semibold text-ink">
            Blocking blocks{" "}
            <span className="font-normal text-muted" data-testid="blocker-count">
              ({truncated ? `first ${blockers.length} listed by the server` : plural(blockers.length, "block")})
            </span>
          </h4>
          {/* a cut-off list cannot give a section's total: its groups count only what is listed (a per-section server
              count is a recorded follow-up) */}
          <p className="mt-0.5 text-xs text-muted" data-testid="blocker-groups-note">
            {truncated ? `Of the first ${blockers.length} the server lists, grouped by section:` : "Grouped by the section they are in."} Each one opens in Verify.
          </p>
          {!titlesReady ? (
            <p className="mt-3 rounded-xl border border-line bg-raised px-4 py-3 text-sm text-muted" data-testid="blocker-list-loading" role="status" aria-busy="true">
              Naming the blocks by their section...
            </p>
          ) : null}
          <ul className="mt-3 divide-y divide-line-soft overflow-hidden rounded-xl border border-line bg-raised" data-testid="blocker-list" hidden={!titlesReady}>
            {groups.map((g, gi) => (
              <li key={`${g.key}-${gi}`} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-baseline sm:gap-4">
                <p className="min-w-0 text-sm sm:w-56 sm:shrink-0">
                  <span className="font-semibold text-ink">{g.title ?? "Blocks"}</span>{" "}
                  <span className="text-muted">· {truncated ? `${g.ids.length} of these ${blockers.length}` : plural(g.ids.length, "block")}</span>
                </p>
                <span className="flex flex-wrap gap-1.5">
                  {g.ids.map((id) => (
                    <a
                      key={id}
                      href="/verify"
                      data-testid="blocker-link"
                      aria-label={`Open ${id} in Verify`}
                      aria-busy={opening === id}
                      onClick={(e) => {
                        e.preventDefault();
                        void open(id);
                      }}
                      className={`inline-flex min-h-[1.75rem] items-center rounded-md bg-sunk px-2 font-mono text-2xs text-ink ring-1 ring-inset ring-line hover:bg-act-wash hover:ring-act-line ${FOCUS}`}
                    >
                      {id}
                    </a>
                  ))}
                </span>
              </li>
            ))}
          </ul>
          {error ? (
            <p role="alert" className="mt-2 text-sm text-fail">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/**
 * Export anyway: one override per listed blocker (review M12 #6). A blanket override (no target) would also cover
 * blocks and flags that start blocking later, until the next export; per-blocker overrides cover exactly what the
 * reader saw: the block's queued state and the flags open on it now (a flag raised on it afterwards blocks again,
 * design 11 P3). Request ids are stable per form and blocker, so a retry after a partial failure records nothing
 * twice. The status is refreshed first and after every write: a block that no longer blocks is skipped. A 422 on one
 * block (it vanished or its id is unknown) is reported and the rest are still recorded; any other failure stops.
 */
function OverrideForm({ blockers, onDone }: { blockers: string[]; onDone: (st: ExportStatus) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rid, setRid] = useState(() => crypto.randomUUID());
  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (!reason.trim()) {
      setError("Please write why you are exporting without a review.");
      return;
    }
    setBusy(true);
    setError(null);
    const targets = [...blockers];
    let latest: ExportStatus;
    try {
      latest = unwrap(await client.GET("/api/export/status"));
    } catch (err) {
      setError(`Could not refresh the export status: ${errText(err)}. Nothing recorded; try again.`);
      setBusy(false);
      return;
    }
    let recorded = 0;
    let skipped = 0;
    const rejected: string[] = [];
    let stopped: string | null = null;
    for (const id of targets) {
      if (!(latest.blockers ?? []).includes(id)) {
        skipped++;
        continue;
      }
      try {
        latest = unwrap(await client.POST("/api/export/override", { body: { reason: reason.trim(), target_id: id, flag_id: null, request_id: `${rid}:${id}` } }));
        recorded++;
      } catch (err) {
        if (err instanceof ApiError && err.status === 422) {
          rejected.push(`${id} (${errText(err)})`);
          continue;
        }
        stopped = `Override not recorded for ${id}: ${errText(err)}.`;
        break;
      }
    }
    onDone(latest);
    const tally = `${recorded} of ${targets.length} recorded${skipped ? `, ${skipped} skipped because they no longer block` : ""}.`;
    if (stopped) setError(`${stopped} ${tally} Record overrides again to retry the rest.`);
    else if (rejected.length) setError(`Override refused for ${rejected.join(", ")}. ${tally}`);
    else {
      setReason("");
      setRid(crypto.randomUUID());
    }
    setBusy(false);
  };
  const n = blockers.length;
  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3 rounded-2xl border border-dashed border-line-strong p-5" data-testid="override-form" aria-labelledby="override-title">
      <h3 id="override-title" className="text-base font-semibold text-ink">
        Export before review is finished
      </h3>
      <p className="max-w-[68ch] text-sm text-muted">
        Records one override for each of the {plural(n, "block")} listed above, with your reason. Each is exported unreviewed, with its machine-cleaned text, and listed in manifest.json. Each covers its block as it is now: a flag raised on it after you record the override blocks the export again, and a block that starts blocking later is not covered.
        {n >= BLOCKER_LIMIT ? ` The server lists at most ${BLOCKER_LIMIT} at a time; record again for the next ones.` : ""}
      </p>
      <label htmlFor="override-reason" className="block text-sm font-medium text-ink">
        Reason <span className="font-normal text-muted">(required, written into manifest.json)</span>
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
          className={`block w-full max-w-xl rounded-xl border border-line-strong bg-raised p-3 text-sm text-ink ${FOCUS}`}
        />
      </Hint>
      {error ? (
        <p id="override-error" role="alert" className="text-sm text-fail">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={busy || n === 0} data-testid="override-submit" className={BTN}>
        {busy ? "Recording..." : n === 1 ? "Record override" : `Record ${n} overrides`}
      </button>
    </form>
  );
}

function Overrides({ list }: { list: Override[] }) {
  if (!list.length) return null;
  return (
    <section aria-labelledby="overrides-title" data-testid="overrides">
      <h3 id="overrides-title" className="text-base font-semibold text-ink">
        Active overrides <span className="text-sm font-normal text-muted">(recorded in manifest.json)</span>
      </h3>
      <ul className="mt-2 space-y-1.5 text-sm">
        {list.map((o, i) => (
          <li key={`${o.at}-${i}`} className="text-ink">
            <span className="text-muted">{fmtTime(o.at)}</span> · {o.target_id ? <span className="font-mono text-xs">{o.target_id}</span> : "blanket: every block blocking the next export, including blocks and flags that start blocking after it was recorded"}:{" "}
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
    <section aria-labelledby="summary-title" data-testid="export-summary" className="space-y-3 rounded-2xl border border-line bg-raised p-5 shadow-lift">
      <h3 id="summary-title" className="text-base font-semibold text-ink">
        <span aria-hidden="true" className="mr-1.5 inline-grid h-6 w-6 place-items-center rounded-full bg-done-wash text-xs font-bold text-done-ink">
          ✓
        </span>
        Last export <span className="text-sm font-normal text-muted">{fmtTime(s.generated_at)}</span>
      </h3>
      <dl className="grid max-w-md grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-base">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink">{k}</dt>
            <dd className="text-right font-bold tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted">
        SHA-256 <span className="break-all font-mono" data-testid="export-sha">{s.zip_sha256}</span>
      </p>
      {(s.warnings ?? []).length ? (
        <ul role="note" className="list-disc space-y-0.5 pl-5 text-sm text-needs-ink">
          {(s.warnings ?? []).map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      <a href="/api/export/download" download data-testid="export-download" className={PRIMARY}>
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
    <main className="w-full max-w-5xl space-y-7 px-4 pb-16 pt-5 wide:px-8 wide:pt-6" data-testid="export-screen">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold tracking-[-0.01em] text-ink">Export the reviewed knowledge base</h2>
        <Link className={`text-sm ${LINK}`} to="/scope">
          Back to Scope
        </Link>
      </div>
      {status.isLoading ? (
        <div aria-busy="true" className="h-24 animate-pulse rounded-2xl bg-sunk" />
      ) : status.isError ? (
        <div role="alert" className="rounded-xl border border-fail-line bg-fail-wash p-3 text-sm text-ink">
          <span aria-hidden="true" className="font-bold text-fail">
            ✕{" "}
          </span>
          Could not read the export status: {errText(status.error)}{" "}
          <button type="button" onClick={() => void status.refetch()} className={`ml-1 min-h-[2rem] rounded-lg border border-line-strong bg-raised px-2.5 ${FOCUS}`}>
            Retry
          </button>
        </div>
      ) : st ? (
        <>
          {locked ? (
            <>
              <Locked st={st} />
              <OverrideForm
                blockers={st.blockers ?? []}
                onDone={(next) => {
                  qc.setQueryData(qk.exportStatus, next);
                  invalidateReviewCounts(qc);
                }}
              />
            </>
          ) : (
            <section aria-labelledby="export-ready" data-testid="export-ready" className="space-y-3">
              <h3 id="export-ready" className="flex items-center gap-2 text-xl font-semibold text-ink">
                <span aria-hidden="true" className="grid h-8 w-8 place-items-center rounded-full bg-done-wash text-sm font-bold text-done-ink">
                  ✓
                </span>
                Ready to export
              </h3>
              <p className="max-w-[62ch] text-base text-muted">
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
                  className={PRIMARY}
                >
                  {running ? "Exporting..." : "Export knowledge base"}
                </button>
              </Hint>
              {running ? (
                <p role="status" className="text-sm text-muted">
                  Building the export. Progress is shown in the jobs bar; you can leave this screen.
                </p>
              ) : null}
              {job.data?.status === "failed" ? (
                <p role="alert" className="text-sm text-fail">
                  Export failed: {job.data.error ?? job.data.message ?? "no details"}
                </p>
              ) : null}
              {startError ? (
                <p role="alert" className="text-sm text-fail">
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
