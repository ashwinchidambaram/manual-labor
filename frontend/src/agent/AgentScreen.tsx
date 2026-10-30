import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, client, unwrap } from "../api/client";
import { invalidateReviewCounts, trackJob, useAgentItems, useCalibration, useOpenFlags, useProposals } from "../api/queries";
import type { AgentItemView, CalibrationReport, Flag, Proposal } from "../api/schema";
import Copy from "../onboarding/Copy";
import { useBlockTitles, type BlockTitle } from "../shell/blockTitles";
import { openInVerify } from "../shell/openInVerify";
import { FLAG_CATEGORIES } from "../verify/labels";

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";
const LINK = `font-medium text-act-ink underline underline-offset-2 hover:text-act-hover ${FOCUS}`;
const BTN = `inline-flex min-h-[2.25rem] items-center rounded-lg border border-line-strong bg-raised px-3 text-sm font-semibold text-ink hover:bg-sunk disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS}`;
const PRIMARY = `inline-flex min-h-[2.25rem] items-center rounded-lg bg-act px-3 text-sm font-semibold text-act-on hover:bg-act-hover disabled:cursor-not-allowed disabled:bg-line disabled:text-muted ${FOCUS} focus-visible:ring-offset-2`;
const H = "text-2xs font-semibold uppercase tracking-[0.07em] text-muted";
const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;
const errText = (e: unknown): string => (e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e));
const CATEGORY = new Map(FLAG_CATEGORIES.map((c) => [c.id, c.label]));
const isBlock = (id: string): boolean => id.startsWith("b-");

function Target({ id }: { id: string }) {
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  if (!isBlock(id)) return <span className="font-mono text-xs">{id}</span>;
  return (
    <>
      <a
        href="/verify"
        aria-label={`Open ${id} in Verify`}
        onClick={(e) => {
          e.preventDefault();
          setError(null);
          openInVerify(id)
            .then(() => nav("/verify"))
            .catch((err: unknown) => setError(`Could not open ${id} in Verify: ${errText(err)}`));
        }}
        className={`font-mono text-xs ${LINK}`}
      >
        {id}
      </a>
      {error ? (
        <span role="alert" className="basis-full text-xs text-fail">
          {error}
        </span>
      ) : null}
    </>
  );
}

function FlagsSection({ flags, items, error, titles }: { flags: Flag[] | undefined; items: Map<string, AgentItemView>; error: unknown; titles: Map<string, BlockTitle> }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; failed: boolean } | null>(null);
  const run = async (): Promise<void> => {
    setBusy(true);
    setMsg(null);
    try {
      const job = unwrap(await client.POST("/api/agent/run", { body: { request_id: crypto.randomUUID() } }));
      trackJob(qc, job);
      setMsg({ text: "Agent pass started. Proposals appear below as each item finishes; you can keep reviewing meanwhile.", failed: false });
    } catch (e) {
      setMsg({ text: `Agent pass not started: ${errText(e)}`, failed: true });
    } finally {
      setBusy(false);
    }
  };
  const n = flags?.length ?? 0;
  // a disabled Run button points at the sentence that says why
  const why = error ? "agent-flags-error" : flags && n === 0 ? "agent-empty" : !flags ? "agent-flags-loading" : undefined;
  return (
    <section aria-labelledby="flags-title" className="space-y-3" data-testid="agent-flags">
      <div className="flex flex-wrap items-center gap-3">
        <h3 id="flags-title" className="text-lg font-semibold text-ink">
          Open flags <span className="font-normal tabular-nums text-muted">{flags ? n : ""}</span>
        </h3>
        <button type="button" onClick={() => void run()} disabled={busy || n === 0} aria-describedby={n === 0 ? why : undefined} data-testid="agent-run" className={`ml-auto ${PRIMARY}`}>
          {busy ? "Starting..." : n ? `Run agent pass on ${plural(n, "flag")}` : "Run agent pass"}
        </button>
      </div>
      {msg ? (
        <p role={msg.failed ? "alert" : "status"} className={`text-sm ${msg.failed ? "text-fail" : "text-muted"}`}>
          {msg.text}
        </p>
      ) : null}
      {error ? (
        <p role="alert" id="agent-flags-error" className="text-sm text-fail">
          Could not list the open flags: {errText(error)}
        </p>
      ) : flags && n === 0 ? (
        <div className="rounded-xl border border-dashed border-line-strong px-4 py-4 text-sm" id="agent-empty" data-testid="agent-empty">
          <p className="font-semibold text-ink">
            <Copy text="No open flags. Flag a block in Verify ({vFlag}) when its text, figure, grouping or table is wrong." />
          </p>
          <p className="mt-1 text-muted">Flags are for blocks you would rather not fix by hand. Each one comes here, a model proposes a fix, and you decide.</p>
          <Link className={`mt-2 inline-block text-sm ${LINK}`} to="/verify">
            Go to Verify
          </Link>
        </div>
      ) : flags ? (
        <ul className="divide-y divide-line-soft overflow-hidden rounded-xl border border-line bg-raised text-sm">
          {flags.map((f) => {
            const it = items.get(f.id);
            const t = titles.get(f.target_id);
            return (
              <li key={f.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3" data-testid="agent-flag">
                {t ? (
                  <span className="basis-full font-semibold text-ink">
                    {t.title} <span className="font-normal text-muted">· p.{t.page}</span>
                  </span>
                ) : null}
                <span className="font-medium text-ink">{CATEGORY.get(f.category) ?? f.category}</span>
                <Target id={f.target_id} />
                {f.note ? <q className="text-muted">{f.note}</q> : null}
                <span className="ml-auto text-xs text-muted">
                  {it ? (it.round > 0 ? `round ${it.round}${it.last_outcome ? `, last: ${it.last_outcome}` : ""}` : "not tried yet") : null}
                  {it?.pending_proposal_id ? " · proposal waiting" : ""}
                </span>
                {it?.last_detail ? <span className="basis-full text-xs text-muted">{it.last_detail}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <div aria-busy="true" id="agent-flags-loading" aria-label="Loading the open flags" className="h-16 animate-pulse rounded-xl bg-sunk" />
      )}
    </section>
  );
}

function ProposalItem({ p }: { p: Proposal }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"idle" | "edit" | "reject">("idle");
  const [text, setText] = useState(p.proposal_text ?? "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const act = async (fn: () => Promise<unknown>): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      invalidateReviewCounts(qc);
    } catch (e) {
      if (e instanceof ApiError && e.code === "edit_conflict") setConflict(true);
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };
  const path = { params: { path: { proposal_id: p.id } } };
  const accept = () => act(async () => unwrap(await client.POST("/api/agent/proposals/{proposal_id}/accept", { ...path, body: { request_id: crypto.randomUUID() } })));
  const reject = () =>
    act(async () => unwrap(await client.POST("/api/agent/proposals/{proposal_id}/reject", { ...path, body: { reason: reason.trim() || null, request_id: crypto.randomUUID() } })));
  const edit = (confirm: boolean) =>
    act(async () =>
      unwrap(await client.POST("/api/agent/proposals/{proposal_id}/edit", { ...path, body: { text, confirm_content_change: confirm, request_id: crypto.randomUUID() } })),
    );
  const failed = (p.rechecks ?? []).filter((r) => !r.passed).length;
  // the export trusts what a person accepts: a proposal the checks did not clear is edited or rejected, never accepted
  const acceptOff =
    failed > 0
      ? `Accept is off: ${plural(failed, "re-check")} failed. Edit the proposal or reject it.`
      : (p.rechecks ?? []).length === 0
        ? "Accept is off: no re-check was reported for this proposal. Edit it or reject it."
        : null;
  return (
    <li className="space-y-3 px-4 py-4" data-testid="proposal" data-proposal-id={p.id}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
        <Target id={p.target_id} />
        <span className="text-ink">{p.kind} proposal</span>
        <span className="text-xs text-muted">
          round {p.round} · {p.model}
        </span>
        <span
          className={`ml-auto rounded-full px-2 py-px text-2xs font-semibold ${
            failed ? "bg-fail-wash text-fail" : (p.rechecks ?? []).length === 0 ? "bg-sunk text-muted" : "bg-done-wash text-done-ink"
          }`}
        >
          <span aria-hidden="true">{failed ? "✕ " : (p.rechecks ?? []).length === 0 ? "" : "✓ "}</span>
          {(p.rechecks ?? []).length === 0 ? "no re-checks reported" : failed ? `${plural(failed, "check")} failed` : "all re-checks passed"}
        </span>
      </div>
      {p.proposal_text != null ? (
        <p className="manual-text whitespace-pre-wrap break-words rounded-xl bg-page p-3 text-read text-ink ring-1 ring-inset ring-line">{p.proposal_text}</p>
      ) : p.proposed_cells ? (
        <p className="text-sm text-muted">Table with {plural(p.proposed_cells.length, "row")}.</p>
      ) : p.proposed_bbox ? (
        <p className="text-sm text-muted">New crop: {p.proposed_bbox.map((v) => v.toFixed(0)).join(", ")}</p>
      ) : p.proposed_attach ? (
        <p className="text-sm text-muted">
          Attach {p.proposed_attach.figure_id} to {p.proposed_attach.article_id}
        </p>
      ) : p.proposed_regroup ? (
        <p className="text-sm text-muted">
          Move {p.proposed_regroup.block_id} to {p.proposed_regroup.to_topic_slug}
        </p>
      ) : null}
      <div className="grid gap-3 text-sm md:grid-cols-2">
        <div>
          <h4 className={H}>Checks run again</h4>
          {(p.rechecks ?? []).length ? (
            <ul className="mt-0.5 space-y-0.5" data-testid="rechecks">
              {(p.rechecks ?? []).map((r) => (
                <li key={r.check} data-outcome={r.passed ? "passed" : "failed"}>
                  <span className={`font-semibold ${r.passed ? "text-done-ink" : "text-fail"}`}>
                    <span aria-hidden="true">{r.passed ? "✓ " : "✕ "}</span>
                    {r.passed ? "Passed" : "Failed"}
                  </span>{" "}
                  {r.check.replace(/_/g, " ")}
                  {r.detail ? <span className="block text-xs text-muted">{r.detail}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-0.5 text-muted">None reported for this proposal.</p>
          )}
        </div>
        <div>
          <h4 className={H}>Model's rationale and evidence</h4>
          <p className="mt-0.5 text-ink">{p.rationale}</p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {(p.evidence ?? []).map((e, i) => (
              <li key={i}>
                <span className="text-muted">{e.source}:</span>{" "}
                {e.verified ? (
                  <q>{e.span}</q>
                ) : (
                  <>
                    <s>{e.span}</s> <span className="text-fail">(not found in this source)</span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
      {(p.history ?? []).length ? (
        <p className="text-xs text-muted">
          Tried before: {(p.history ?? []).map((h) => `${h.status}${h.reason ? ` (${h.reason})` : ""}`).join("; ")}
        </p>
      ) : null}
      {mode === "edit" ? (
        <div className="space-y-1">
          <label htmlFor={`edit-${p.id}`} className="text-xs font-medium text-ink">
            Your text
          </label>
          <textarea id={`edit-${p.id}`} value={text} onChange={(e) => setText(e.target.value)} rows={4} className={`manual-text w-full rounded-xl border border-line-strong bg-raised p-3 text-read text-ink ${FOCUS}`} />
        </div>
      ) : null}
      {mode === "reject" ? (
        <div className="space-y-1">
          <label htmlFor={`reject-${p.id}`} className="text-xs font-medium text-ink">
            Why is it wrong? <span className="font-normal text-muted">(optional, shown on the next attempt)</span>
          </label>
          <input id={`reject-${p.id}`} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} className={`w-full rounded-lg border border-line-strong bg-raised p-2 text-sm ${FOCUS}`} />
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-fail">
          {error}
        </p>
      ) : null}
      {mode === "idle" && acceptOff ? (
        <p id={`accept-off-${p.id}`} className="text-xs text-muted" data-testid="accept-off">
          {acceptOff}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {mode === "idle" ? (
          <>
            <button type="button" disabled={busy || acceptOff !== null} aria-describedby={acceptOff ? `accept-off-${p.id}` : undefined} onClick={() => void accept()} className={PRIMARY}>
              Accept
            </button>
            {p.kind === "text" ? (
              <button type="button" disabled={busy} onClick={() => setMode("edit")} className={BTN}>
                Edit
              </button>
            ) : null}
            <button type="button" disabled={busy} onClick={() => setMode("reject")} className={BTN}>
              Reject
            </button>
          </>
        ) : mode === "edit" ? (
          <>
            <button type="button" disabled={busy || !text.trim()} onClick={() => void edit(false)} className={BTN}>
              Save edit
            </button>
            {conflict ? (
              <button type="button" disabled={busy} onClick={() => void edit(true)} className={`min-h-[2.25rem] rounded-lg bg-fail px-3 text-sm font-semibold text-act-on ${FOCUS}`}>
                Confirm content change
              </button>
            ) : null}
            <button type="button" onClick={() => setMode("idle")} className={BTN}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button type="button" disabled={busy} onClick={() => void reject()} className={BTN}>
              Reject proposal
            </button>
            <button type="button" onClick={() => setMode("idle")} className={BTN}>
              Cancel
            </button>
          </>
        )}
      </div>
    </li>
  );
}

function Calibration({ c, error }: { c: CalibrationReport | undefined; error: unknown }) {
  if (error)
    return (
      <p className="text-sm text-muted" data-testid="calibration-unavailable">
        Calibration is not available: {errText(error)}
      </p>
    );
  if (!c) return <div aria-busy="true" className="h-16 animate-pulse rounded-xl bg-sunk" />;
  const used = (c.buckets ?? []).filter((b) => b.n > 0);
  const pct = (v: number | null | undefined): string => (v == null ? "n/a" : `${Math.round(v * 100)}%`);
  return (
    <div className="space-y-2 text-sm" data-testid="calibration">
      <p className="max-w-prose text-muted">
        How often you edited blocks in each score range, from {plural(c.n_outcomes ?? 0, "decision")}
        {(c.n_numeric_excluded ?? 0) > 0 ? ` (${plural(c.n_numeric_excluded ?? 0, "numeric block")} left out: they are always reviewed)` : ""}. Target edit rate{" "}
        {pct(c.target_edit_rate)}.
      </p>
      {used.length ? (
        <table className="w-full max-w-lg text-left text-sm" data-testid="calibration-table">
          <thead>
            <tr className="text-xs text-muted">
              <th scope="col" className="py-0.5 font-medium">Confidence</th>
              <th scope="col" className="py-0.5 text-right font-medium">Blocks</th>
              <th scope="col" className="py-0.5 text-right font-medium">Edited</th>
              <th scope="col" className="py-0.5 text-right font-medium">Edit rate</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {used.map((b) => (
              <tr key={b.lo} className="border-t border-line-soft">
                <td className="py-0.5">
                  {b.lo.toFixed(2)} to {b.hi.toFixed(2)}
                </td>
                <td className="py-0.5 text-right">{b.n}</td>
                <td className="py-0.5 text-right">{b.edited}</td>
                <td className="py-0.5 text-right">
                  {pct(b.edit_rate)}
                  {b.sparse ? <span className="text-xs text-muted"> (few)</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="rounded-xl border border-dashed border-line-strong px-3.5 py-3 text-muted">
          No decisions yet. This builds as you review: approve or edit blocks in Verify and the edit rate of each score range appears here.
        </p>
      )}
      <p data-testid="calibration-suggestion">
        Current threshold <span className="font-semibold tabular-nums">{c.current_threshold?.toFixed(2) ?? "n/a"}</span>. Suggested{" "}
        <span className="font-semibold tabular-nums">{c.suggested_threshold?.toFixed(2) ?? "none yet"}</span>
        {c.suggestion_detail ? <span className="text-muted">: {c.suggestion_detail}</span> : null}
      </p>
      <p className="text-xs text-muted">The suggestion is never applied automatically.</p>
      {(c.warnings ?? []).length ? (
        <ul role="note" className="list-disc pl-5 text-xs text-needs-ink">
          {(c.warnings ?? []).map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export default function AgentScreen() {
  const flags = useOpenFlags();
  const items = useAgentItems();
  const proposals = useProposals();
  const calibration = useCalibration();
  const itemMap = new Map((items.data ?? []).map((i) => [i.flag.id, i]));
  const list = proposals.data ?? [];
  const titles = useBlockTitles((flags.data ?? []).length > 0);
  return (
    <main className="flex w-full flex-col gap-7 px-4 pb-16 pt-5 wide:px-8 wide:pt-6" data-testid="agent-screen">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div>
          <h2 className="text-xl font-semibold tracking-[-0.01em] text-ink">Fix what you flag</h2>
          <p className="mt-1 max-w-[70ch] text-base text-muted" data-testid="agent-definition">
            An agent pass sends each open flag to a model, one fresh call per item: the flagged block is handed to a model with what you flagged, and it proposes a fix. Every proposal is re-checked by the same deterministic checks before you see it; failed checks are shown, not hidden.
          </p>
        </div>
        <Link className={`text-sm ${LINK}`} to="/scope">
          Back to Scope
        </Link>
      </div>
      <div className="grid grid-cols-1 gap-x-8 gap-y-8 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.3fr)] roomy:grid-cols-[minmax(0,0.9fr)_minmax(0,1.3fr)_minmax(0,0.9fr)]">
        <FlagsSection flags={flags.data} items={itemMap} error={flags.error} titles={titles} />
        <section aria-labelledby="proposals-title" className="space-y-3" data-testid="agent-proposals">
          <h3 id="proposals-title" className="text-lg font-semibold text-ink">
            Proposals waiting for you <span className="font-normal tabular-nums text-muted">{proposals.data ? list.length : ""}</span>
          </h3>
          {proposals.isError ? (
            <p className="text-sm text-muted">Proposals are not available: {errText(proposals.error)}</p>
          ) : proposals.data && list.length === 0 ? (
            <div className="rounded-xl border border-dashed border-line-strong px-4 py-4 text-sm text-muted">
              None. Run the agent pass on open flags and its proposals are listed here, each with its text before and after, the checks run again, and
              the model's reasons.
            </div>
          ) : proposals.data ? (
            <ul className="divide-y divide-line-soft overflow-hidden rounded-xl border border-line bg-raised">
              {list.map((p) => (
                <ProposalItem key={p.id} p={p} />
              ))}
            </ul>
          ) : (
            <div aria-busy="true" className="h-16 animate-pulse rounded-xl bg-sunk" />
          )}
          <p className="text-xs text-muted" data-testid="reject-note">
            Rejecting a proposal leaves its flag open: the item stays on this screen for the next agent pass, with what was tried and your reason, and the export stays locked until the flag is resolved.
          </p>
        </section>
        <section aria-labelledby="calibration-title" className="space-y-3 xl:col-span-2 roomy:col-span-1">
          <h3 id="calibration-title" className="text-lg font-semibold text-ink">
            How your decisions compare with the scores
          </h3>
          <Calibration c={calibration.data} error={calibration.error} />
        </section>
      </div>
    </main>
  );
}
