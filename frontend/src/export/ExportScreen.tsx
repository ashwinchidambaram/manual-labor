import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, client, unwrap } from "../api/client";
import { invalidateReviewCounts, qk, trackJob, useExportStatus, useOpenFlags } from "../api/queries";
import type { ExportStatus, ExportSummary, Override } from "../api/schema";
import { useJobWatch } from "../hooks/useJobsPolling";
import Hint from "../onboarding/Hint";
import { useBlockTitles } from "../shell/blockTitles";
import { AttentionIcon } from "../shell/Icon";
import { openInVerify } from "../shell/openInVerify";
import { FLAG_CATEGORIES, FLAG_RESOLUTION } from "../verify/labels";
import { blockingFlagsOf, scopeTerms, toReviewOf } from "../shell/scopeTerms";

/** The server lists at most this many blockers (manuallabor/export/types.py BLOCKER_LIMIT). */
export const BLOCKER_LIMIT = 20;
const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";
const LINK = `font-medium text-act-ink underline underline-offset-2 hover:text-act-hover ${FOCUS}`;
const BTN = `inline-flex min-h-[2.5rem] items-center rounded-xl border border-line-strong bg-raised px-4 text-sm font-semibold text-ink hover:bg-sunk disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS} focus-visible:ring-offset-2`;
const PRIMARY = `inline-flex min-h-[2.75rem] items-center rounded-xl bg-act px-5 text-base font-semibold text-act-on transition-colors duration-150 ease-out-quart hover:bg-act-hover disabled:cursor-not-allowed disabled:bg-line disabled:text-muted ${FOCUS} focus-visible:ring-offset-2`;
const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;
const errText = (e: unknown): string => (e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e));

type ScopeCounts = NonNullable<ExportStatus["counts"]>;
type FlagBlocker = NonNullable<ExportStatus["flag_blockers"]>[number];
const flagLabel = (c: string): string => FLAG_CATEGORIES.find((x) => x.id === c)?.label ?? c.replace(/_/g, " ");
const LEFT_OUT: Record<string, string> = {
  header_footer: "page headers and footers",
  not_selected: "not selected",
  empty: "empty",
  rejected: "rejected",
};

/**
 * The gate's partition of the scope, as one equation (design 11 section 14): every in-scope block is in exactly one
 * term, so the line adds up to the Verify screen's "in scope" and "still blocking" moves as overrides are recorded.
 */
function ScopeLine({ c }: { c: ScopeCounts }) {
  const terms: string[] = [`${c.auto_approved} auto-approved`, `${c.approved} approved by you`, `${c.edited} edited by you`];
  if (c.rejected) terms.push(`${c.rejected} rejected`);
  // the words the Verify strip and the rail use (design 11 section 17); an older server says only "still blocking"
  const split = typeof c.to_review === "number" && typeof c.flagged === "number";
  terms.push(`${c.overridden} overridden`, ...(split ? [`${c.to_review} to review`, `${c.flagged} flagged`] : [`${c.blocking} still blocking`]));
  const sum = c.auto_approved + c.approved + c.edited + c.rejected + c.overridden + c.blocking;
  return (
    <p className="text-sm tabular-nums text-muted" data-testid="export-reconcile">
      {plural(c.in_scope, "block")} in scope = {terms.join(" + ")}
      {sum !== c.in_scope ? <span className="ml-1 font-semibold text-fail"> (these counts do not add up: {sum}; please report this)</span> : null}
    </p>
  );
}

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
function Locked({ st, after }: { st: ExportStatus; after: ExportSummary | null }) {
  const nav = useNavigate();
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const blockers = st.blockers ?? [];
  // design 11 section 17: "to review" never counts a block an override covers; a flag counts while it holds the export
  const queued = toReviewOf(st);
  const flags = blockingFlagsOf(st);
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
  const { titles, ready: titlesReady } = useBlockTitles(blockers);
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
          <h3 id="export-locked" tabIndex={-1} className={`text-xl font-semibold text-ink ${FOCUS}`}>
            {after ? "A new export is locked" : "Export is locked"}
          </h3>
          {after ? (
            <p className="mt-1 max-w-[62ch] text-base text-muted" data-testid="export-locked-after">
              The last export above is done and can still be downloaded.
              {after.review.overrides
                ? ` It used up its ${plural(after.review.overrides, "override")}: each export spends the overrides it was built with, so a new export needs these blocks reviewed or overridden again.`
                : ""}
            </p>
          ) : null}
          <p className="mt-1 max-w-[62ch] text-base text-muted">
            Why: the export only contains text a person or the checks have accepted. These must be resolved first, or overridden with a reason.
          </p>
        </div>
      </div>
      <ul className="space-y-2 text-base" data-testid="export-reasons">
        {flags > 0 ? (
          <li data-testid="reason-flags" className="rounded-xl bg-raised px-4 py-3 ring-1 ring-inset ring-line">
            <span className="font-semibold tabular-nums">{plural(flags, "open flag")}</span>. {FLAG_RESOLUTION}{" "}
            <Link className={LINK} to="/agent">
              Go to the Agent screen
            </Link>
            , where each flag opens in Verify.
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
      {st.counts ? <ScopeLine c={st.counts} /> : null}
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
 * Export before review is finished: one decision, one reason, every unflagged blocker (design 11 section 18). The
 * server lists at most BLOCKER_LIMIT blockers at a time (a rule of the status, which is polled after every approve);
 * one click therefore runs successive rounds: override every listed blocker that no uncovered flag holds in the latest
 * status, then take the next page from the last answer (every override POST answers with the status), until no
 * unflagged blocker is listed. A round that records nothing ends the run, so it cannot loop. A block override never
 * covers a flag (section 14): a flagged block is left out, said so, and gets its own decision in FlagOverrides; the
 * server refuses one anyway (422). Per-block overrides cover exactly the blocks blocking now: a flag raised on one
 * afterwards blocks again, and a block that starts blocking later is not covered (P3). Request ids are `<run>:<block>`
 * and the run id is renewed only after a run that recorded everything, so a retry after a stop records nothing twice.
 * The reason stays in the box until the person clears it. A 422 on one block is reported and the rest are still
 * recorded; any other failure stops the run.
 */
function OverrideForm({ st, onDone }: { st: ExportStatus; onDone: (st: ExportStatus) => void }) {
  const flagged = new Set((st.flag_blockers ?? []).map((f) => f.block_id));
  const listed = (st.blockers ?? []).filter((id) => !flagged.has(id));
  // every unflagged blocker, not only the listed ones; an older server without the partition: what is listed
  const terms = scopeTerms(st);
  const remaining = terms ? terms.toReview : listed.length;
  const leftOut = terms ? terms.flagged : (st.blockers ?? []).length - listed.length;
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ done: number; of: number; final: boolean } | null>(null);
  const [rid, setRid] = useState(() => crypto.randomUUID());
  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (!reason.trim()) {
      setError("Please write why you are exporting without a review.");
      return;
    }
    setBusy(true);
    setError(null);
    let latest: ExportStatus;
    try {
      latest = unwrap(await client.GET("/api/export/status"));
    } catch (err) {
      setError(`Could not refresh the export status: ${errText(err)}. Nothing recorded; try again.`);
      setBusy(false);
      return;
    }
    const unflagged = (x: ExportStatus): string[] => {
      const held = new Set((x.flag_blockers ?? []).map((f) => f.block_id));
      return (x.blockers ?? []).filter((id) => !held.has(id));
    };
    // never more than the button named when it was pressed, nor more than the server says are left now
    const of = Math.min(n, scopeTerms(latest)?.toReview ?? unflagged(latest).length);
    let recorded = 0;
    const tried = new Set<string>();
    const rejected: string[] = [];
    let stopped: string | null = null;
    setProgress({ done: 0, of, final: false });
    // never more than the button named: a block that starts blocking during the run needs its own decision (P3)
    while (recorded < of) {
      const todo = unflagged(latest).filter((id) => !tried.has(id));
      if (!todo.length) break;
      const before = recorded;
      for (const id of todo) {
        if (recorded >= of) break;
        // the last answer is newer than this page: a block approved or flagged since is not overridden
        if (!unflagged(latest).includes(id) && (latest.blockers ?? []).length < BLOCKER_LIMIT) continue;
        tried.add(id);
        try {
          latest = unwrap(await client.POST("/api/export/override", { body: { reason: reason.trim(), target_id: id, flag_id: null, request_id: `${rid}:${id}` } }));
          recorded++;
          setProgress({ done: recorded, of, final: false });
        } catch (err) {
          if (err instanceof ApiError && err.status === 422) {
            rejected.push(`${id} (${errText(err)})`);
            continue;
          }
          stopped = `Override not recorded for ${id}: ${errText(err)}.`;
          break;
        }
      }
      if (stopped || recorded === before) break;
    }
    onDone(latest);
    setProgress({ done: recorded, of, final: true });
    const tally = `Recorded ${recorded} of ${of}.`;
    // what still waits after the run, said rather than left for the reader to find (design 11 section 18)
    const left = scopeTerms(latest)?.toReview ?? unflagged(latest).length;
    const isAre = (n: number): string => (n === 1 ? "is" : "are");
    if (stopped) setError(`${stopped} ${tally} Press the button again to record the rest.`);
    else if (rejected.length) setError(`Override refused for ${rejected.join(", ")}. ${tally}`);
    else if (left > 0 && recorded >= of)
      setError(
        `${tally} ${plural(left, "block")} still to review ${isAre(left)} not covered (${left === 1 ? "it" : "they"} started blocking after you pressed the button): press it again to override ${left === 1 ? "it" : "them"} too.`,
      );
    else if (left > 0)
      setError(
        `${tally} ${plural(left, "block")} still to review ${isAre(left)} not listed yet: the server lists blockers ${BLOCKER_LIMIT} at a time and the first ones are flagged. Decide on the flags below, then press the button again.`,
      );
    else {
      // done; blocks reviewed elsewhere during the run needed no override, and the tally says why it is short
      if (recorded < of) setError(`${tally} ${plural(of - recorded, "block")} no longer needed an override: reviewed or changed meanwhile.`);
      setRid(crypto.randomUUID());
    }
    setBusy(false);
  };
  const n = remaining;
  const label = busy ? "Recording..." : n === 0 ? "Nothing left to override" : n === 1 ? "Override the remaining block with this reason" : `Override the remaining ${n} with this reason`;
  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3 rounded-2xl border border-dashed border-line-strong p-5" data-testid="override-form" aria-labelledby="override-title">
      <h3 id="override-title" className="text-base font-semibold text-ink">
        Export before review is finished
      </h3>
      <p className="max-w-[68ch] text-sm text-muted">
        Records one override for each of the {plural(n, "block")} still to review (every one, not only those listed), all with your reason. Each is
        exported unreviewed, with its machine-cleaned text, and listed in manifest.json. Each covers its block as it is now: a flag raised on it after
        you record the override blocks the export again, and a block that starts blocking later is not covered.
      </p>
      {leftOut ? (
        <p className="max-w-[68ch] rounded-xl bg-needs-wash px-3 py-2 text-sm text-ink" data-testid="override-left-out">
          <span className="font-semibold">{leftOut === 1 ? "1 flagged block is left out" : `${leftOut} flagged blocks are left out`}</span>: a block
          override never covers a flag; each flag needs its own decision, below.
        </p>
      ) : null}
      <label htmlFor="override-reason" className="block text-sm font-medium text-ink">
        Reason <span className="font-normal text-muted">(required, written into manifest.json; it stays here until you clear it)</span>
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
      {progress ? (
        <div className="flex max-w-xl items-center gap-3">
          {!progress.final ? (
            <progress aria-label="Recording overrides" max={progress.of} value={progress.done} className="h-2 min-w-0 flex-1 accent-[var(--act)]" />
          ) : null}
          <p role="status" className="text-sm tabular-nums text-muted" data-testid="override-progress">
            Recorded {progress.done} of {progress.of}
            {progress.final ? "." : "..."}
          </p>
        </div>
      ) : null}
      <button type="submit" disabled={busy || n === 0} data-testid="override-submit" className={BTN}>
        {label}
      </button>
    </form>
  );
}

/** One open flag, one explicit decision: an override that names the flag (design 11 P3, section 14). */
function FlagOverride({ f, onDone }: { f: FlagBlocker; onDone: (f: FlagBlocker, st: ExportStatus) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rid, setRid] = useState(() => crypto.randomUUID());
  const rId = `flag-reason-${f.flag_id}`;
  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (!reason.trim()) {
      setError("Please write why you are exporting this block despite its flag.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = unwrap(await client.POST("/api/export/override", { body: { reason: reason.trim(), flag_id: f.flag_id, target_id: null, request_id: `${rid}:${f.flag_id}` } }));
      onDone(f, next);
      setReason("");
      setRid(crypto.randomUUID());
    } catch (err) {
      setError(`Override not recorded for this flag: ${errText(err)}.`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <li data-testid="flag-override" className="space-y-2 rounded-xl bg-needs-wash px-4 py-3">
      <p className="text-sm text-ink">
        <span className="font-semibold">{flagLabel(f.category)}</span> on <span className="font-mono text-xs">{f.block_id}</span>
        {f.note ? (
          <>
            {" "}
            · <q>{f.note}</q>
          </>
        ) : null}
      </p>
      <form onSubmit={(e) => void submit(e)} className="space-y-2">
        <label htmlFor={rId} className="block text-sm font-medium text-ink">
          Reason for exporting <span className="font-mono text-xs">{f.block_id}</span> despite its flag{" "}
          <span className="font-normal text-muted">(required, written into manifest.json)</span>
        </label>
        <textarea
          id={rId}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          aria-invalid={error !== null}
          aria-describedby={error ? `${rId}-error` : undefined}
          className={`block w-full max-w-xl rounded-xl border border-line-strong bg-raised p-3 text-sm text-ink ${FOCUS}`}
        />
        {error ? (
          <p id={`${rId}-error`} role="alert" className="text-sm text-fail">
            {error}
          </p>
        ) : null}
        <button type="submit" disabled={busy} aria-label={`Export ${f.block_id} despite its flag`} className={BTN}>
          {busy ? "Recording..." : "Export despite this flag"}
        </button>
      </form>
    </li>
  );
}

function FlagOverrides({ list, onDone }: { list: FlagBlocker[]; onDone: (f: FlagBlocker, st: ExportStatus) => void }) {
  if (!list.length) return null;
  return (
    <section aria-labelledby="flag-overrides-title" data-testid="flag-overrides" className="space-y-3 rounded-2xl border border-dashed border-line-strong p-5">
      <h3 id="flag-overrides-title" className="text-base font-semibold text-ink">
        {plural(list.length, "open flag")}: each needs its own decision
      </h3>
      <p className="max-w-[68ch] text-sm text-muted">
        A flag says a reviewer thinks this block may be wrong. {FLAG_RESOLUTION} Exporting a block despite its flag sends its machine-cleaned text,
        and manifest.json records your reason with the flag.{" "}
        <Link className={LINK} to="/agent">
          Go to the Agent screen
        </Link>
        .
      </p>
      <ul className="space-y-2">
        {list.map((f) => (
          <FlagOverride key={f.flag_id} f={f} onDone={onDone} />
        ))}
      </ul>
    </section>
  );
}

function Overrides({ list }: { list: Override[] }) {
  // a flag override keeps its flag open, so the open flags name its block
  const flags = useOpenFlags();
  const blockOf = new Map((flags.data ?? []).map((f) => [f.id, f.target_id]));
  if (!list.length) return null;
  return (
    <section aria-labelledby="overrides-title" data-testid="overrides">
      <h3 id="overrides-title" className="text-base font-semibold text-ink">
        Active overrides <span className="text-sm font-normal text-muted">(recorded in manifest.json)</span>
      </h3>
      <ul className="mt-2 space-y-1.5 text-sm">
        {list.map((o, i) => (
          <li key={`${o.at}-${i}`} className="text-ink">
            <span className="text-muted">{fmtTime(o.at)}</span> ·{" "}
            {o.flag_id ? (
              <>
                flag <span className="font-mono text-xs">{o.flag_id}</span>
                {blockOf.get(o.flag_id) ? (
                  <>
                    {" "}
                    on <span className="font-mono text-xs">{blockOf.get(o.flag_id)}</span>
                  </>
                ) : null}
              </>
            ) : o.target_id ? (
              <span className="font-mono text-xs">{o.target_id}</span>
            ) : (
              "an override for everything: every block blocking the next export, including blocks and flags that start blocking after it was recorded"
            )}
            :{" "}
            <q>{o.reason}</q>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The last export, on top of the screen whenever there is one (design 11 section 14): its download, and its blocks as
 * two equations that add up (exported = one bucket each; parsed = exported + left out by reason).
 */
const EXPORT_FINISHED = "Export finished. Download the zip below.";

function Summary({ s, fresh }: { s: ExportSummary; fresh: boolean }) {
  const r = s.review;
  const rows: [string, string][] = [
    ["Articles", String(s.articles)],
    ["Figures", String(s.figures)],
    ["Pages covered", String(s.pages_covered)],
    ["Documents", String(s.docs)],
    ["Numbers verified by you", String(r.numbers_verified)],
    ["Zip size", fmtBytes(s.zip_bytes)],
  ];
  const leftOut = Object.entries(r.left_out ?? {}).filter(([, n]) => n > 0);
  const leftTotal = leftOut.reduce((a, [, n]) => a + n, 0);
  const bucketSum = r.auto_approved + r.approved + r.edited + r.overrides;
  const adds = bucketSum === r.blocks && r.blocks + leftTotal === r.total_blocks;
  return (
    <section aria-labelledby="summary-title" data-testid="export-summary" className="space-y-3 rounded-2xl border border-line bg-raised p-5 shadow-lift">
      <h3 id="summary-title" tabIndex={-1} className={`text-xl font-semibold text-ink ${FOCUS}`}>
        <span aria-hidden="true" className="mr-1.5 inline-grid h-7 w-7 place-items-center rounded-full bg-done-wash text-sm font-bold text-done-ink">
          ✓
        </span>
        Last export <span className="text-sm font-normal text-muted">{fmtTime(s.generated_at)}</span>
      </h3>
      {fresh ? (
        <p className="text-base text-ink" data-testid="export-fresh">
          {EXPORT_FINISHED}
        </p>
      ) : null}
      <a href="/api/export/download" download data-testid="export-download" className={PRIMARY}>
        Download zip
      </a>
      <p className="text-sm tabular-nums text-ink" data-testid="summary-reconcile">
        {plural(r.blocks, "block")} exported = {r.auto_approved} auto-approved + {r.approved} approved by you + {r.edited} edited by you + {r.overrides} overridden
      </p>
      <p className="text-sm tabular-nums text-muted" data-testid="summary-left-out">
        {leftTotal
          ? `${r.total_blocks} parsed blocks = ${r.blocks} exported + ${leftTotal} left out (${leftOut.map(([k, n]) => `${n} ${LEFT_OUT[k] ?? k.replace(/_/g, " ")}`).join(", ")})`
          : `${plural(r.total_blocks, "parsed block")}, all exported`}
      </p>
      {r.overrides ? (
        <p className="text-sm text-muted">
          The {plural(r.overrides, "overridden block")} went out unreviewed, with machine-cleaned text; manifest.json lists each one with its reason. The article text
          itself carries no marker.
        </p>
      ) : null}
      {!adds ? (
        <p role="alert" className="text-sm font-semibold text-fail">
          These counts do not add up. Please report this.
        </p>
      ) : null}
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
  // the second column holds the override forms (locked) and the active overrides; it is left out when empty
  const side = !!st && (locked || (st.overrides ?? []).length > 0);
  const running = !!job.data && (job.data.status === "queued" || job.data.status === "running");
  const jobDone = job.data?.status === "done";
  // One live region, mounted with the screen, so a result is announced (a status node inserted together with its text
  // often is not). Focus moves only after the reader's own action, when the control they used leaves the screen.
  const [live, setLive] = useState("");
  const [focusTo, setFocusTo] = useState<string | null>(null);
  useEffect(() => {
    if (!focusTo) return;
    const el = document.getElementById(focusTo);
    if (el) {
      el.focus();
      setFocusTo(null);
    }
  });
  useEffect(() => {
    // the export just finished: read the gate and the new summary now, not on the next navigation. The Ready section
    // with the Export button may be replaced by the lock (the export spent its overrides): focus goes to the result.
    if (!jobDone) return;
    void qc.invalidateQueries({ queryKey: qk.exportStatus });
    setLive(EXPORT_FINISHED);
    setFocusTo("summary-title");
  }, [jobDone, qc]);
  const recorded = (next: ExportStatus): void => {
    qc.setQueryData(qk.exportStatus, next);
    invalidateReviewCounts(qc);
  };
  // a flag decision unmounts its own row: focus goes to the next flag's reason, else to what the screen shows now
  const flagRecorded = (f: FlagBlocker, next: ExportStatus): void => {
    const at = (st?.flag_blockers ?? []).findIndex((x) => x.flag_id === f.flag_id);
    const left = next.flag_blockers ?? [];
    recorded(next);
    const nextFlag = left.length ? left[Math.min(Math.max(0, at), left.length - 1)] : null;
    setFocusTo(nextFlag ? `flag-reason-${nextFlag.flag_id}` : (next.blockers ?? []).length ? "export-locked" : "export-start");
    setLive(`Override recorded for the flag on ${f.block_id}. ${left.length ? `${plural(left.length, "flag")} still ${left.length === 1 ? "needs" : "need"} a decision.` : "No flag needs a decision now."}`);
  };

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
        // the refusal has no scope partition: read the whole status, so the reasons do not mix old and new counts
        void qc.invalidateQueries({ queryKey: qk.exportStatus });
      } else setStartError(`Export not started: ${errText(e)}`);
    } finally {
      setStarting(false);
    }
  };

  return (
    <main className="w-full space-y-7 px-4 pb-16 pt-5 wide:px-8 wide:pt-6" data-testid="export-screen">
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
        // fluid layout (design 13 section 9.4): from `xl` the gate and the overrides sit side by side and use the width
        // beside the rail; the side column is left out when it would be empty
        <div className={`grid grid-cols-1 gap-x-10 gap-y-7 ${side ? "xl:grid-cols-[minmax(0,1fr)_var(--export-side-w)]" : ""}`}>
          <div className="min-w-0 space-y-7" data-testid="export-main">
            {/* the last export first: after a success the result and its download are what the reader looks for, and
                the gate below says what a new export needs (each export spends its overrides, design 11 P3) */}
            {st.summary ? <Summary s={st.summary} fresh={jobDone} /> : null}
            {locked ? (
              <Locked st={st} after={st.summary ?? null} />
            ) : (
              <section aria-labelledby="export-ready" data-testid="export-ready" className="space-y-3">
                <h3 id="export-ready" className="flex items-center gap-2 text-xl font-semibold text-ink">
                  <span aria-hidden="true" className="grid h-8 w-8 place-items-center rounded-full bg-done-wash text-sm font-bold text-done-ink">
                    ✓
                  </span>
                  {st.summary ? "Ready to export again" : "Ready to export"}
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
                    id="export-start"
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
          </div>
          {side ? (
            <div className="min-w-0 space-y-7" data-testid="export-side">
              {locked ? (
                <>
                  <OverrideForm st={st} onDone={recorded} />
                  <FlagOverrides list={st.flag_blockers ?? []} onDone={flagRecorded} />
                </>
              ) : null}
              <Overrides list={st.overrides ?? []} />
            </div>
          ) : null}
        </div>
      ) : null}
      <p role="status" className="sr-only" data-testid="export-live">
        {live}
      </p>
    </main>
  );
}
