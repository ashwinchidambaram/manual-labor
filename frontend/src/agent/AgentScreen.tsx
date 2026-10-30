import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, client, unwrap } from "../api/client";
import { invalidateReviewCounts, trackJob, useAgentItems, useCalibration, useOpenFlags, useProposals } from "../api/queries";
import type { AgentItemView, CalibrationReport, Flag, Proposal } from "../api/schema";
import Copy from "../onboarding/Copy";
import { openInVerify } from "../shell/openInVerify";
import { FLAG_CATEGORIES } from "../verify/labels";

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
const LINK = `text-blue-700 underline underline-offset-2 hover:text-blue-900 ${FOCUS}`;
const BTN = `rounded border border-slate-500 bg-white px-2.5 py-1 text-sm hover:bg-slate-100 disabled:opacity-50 ${FOCUS}`;
const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;
const errText = (e: unknown): string => (e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e));
const CATEGORY = new Map(FLAG_CATEGORIES.map((c) => [c.id, c.label]));
const isBlock = (id: string): boolean => id.startsWith("b-");

function Target({ id }: { id: string }) {
  const nav = useNavigate();
  if (!isBlock(id)) return <span className="font-mono text-xs">{id}</span>;
  return (
    <a
      href="/verify"
      aria-label={`Open ${id} in Verify`}
      onClick={(e) => {
        e.preventDefault();
        void openInVerify(id).then(() => nav("/verify"));
      }}
      className={`font-mono text-xs ${LINK}`}
    >
      {id}
    </a>
  );
}

function FlagsSection({ flags, items, error }: { flags: Flag[] | undefined; items: Map<string, AgentItemView>; error: unknown }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const run = async (): Promise<void> => {
    setBusy(true);
    setMsg(null);
    try {
      const job = unwrap(await client.POST("/api/agent/run", { body: { request_id: crypto.randomUUID() } }));
      trackJob(qc, job);
      setMsg("Agent pass started. Proposals appear below as each item finishes; you can keep reviewing meanwhile.");
    } catch (e) {
      setMsg(`Agent pass not started: ${errText(e)}`);
    } finally {
      setBusy(false);
    }
  };
  const n = flags?.length ?? 0;
  return (
    <section aria-labelledby="flags-title" className="space-y-2" data-testid="agent-flags">
      <div className="flex flex-wrap items-center gap-3">
        <h3 id="flags-title" className="text-base font-semibold text-slate-950">
          Open flags <span className="font-normal tabular-nums text-slate-600">{flags ? n : ""}</span>
        </h3>
        <button type="button" onClick={() => void run()} disabled={busy || n === 0} data-testid="agent-run" className={`ml-auto rounded bg-slate-900 px-3 py-1 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400 ${FOCUS} focus-visible:ring-offset-2`}>
          {busy ? "Starting..." : n ? `Run agent pass on ${plural(n, "flag")}` : "Run agent pass"}
        </button>
      </div>
      {msg ? (
        <p role="status" className="text-sm text-slate-700">
          {msg}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-800">
          Could not list the open flags: {errText(error)}
        </p>
      ) : flags && n === 0 ? (
        <p className="text-sm text-slate-700" data-testid="agent-empty">
          <Copy text="No open flags. Flag a block in Verify ({vFlag}) when its text, figure, grouping or table is wrong." />
        </p>
      ) : flags ? (
        <ul className="divide-y divide-slate-200 rounded border border-slate-300 bg-white text-sm">
          {flags.map((f) => {
            const it = items.get(f.id);
            return (
              <li key={f.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2" data-testid="agent-flag">
                <span className="font-medium">{CATEGORY.get(f.category) ?? f.category}</span>
                <Target id={f.target_id} />
                {f.note ? <q className="text-slate-700">{f.note}</q> : null}
                <span className="ml-auto text-xs text-slate-600">
                  {it ? (it.round > 0 ? `round ${it.round}${it.last_outcome ? `, last: ${it.last_outcome}` : ""}` : "not tried yet") : null}
                  {it?.pending_proposal_id ? " · proposal waiting" : ""}
                </span>
                {it?.last_detail ? <span className="basis-full text-xs text-slate-600">{it.last_detail}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <div aria-busy="true" className="h-16 animate-pulse rounded bg-slate-200" />
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
  return (
    <li className="space-y-2 px-3 py-3" data-testid="proposal" data-proposal-id={p.id}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
        <Target id={p.target_id} />
        <span className="text-slate-700">{p.kind} proposal</span>
        <span className="text-xs text-slate-600">
          round {p.round} · {p.model}
        </span>
        <span className={`ml-auto rounded px-1.5 text-xs ${failed ? "bg-red-100 text-red-900" : "bg-slate-100 text-slate-800"}`}>
          {(p.rechecks ?? []).length === 0 ? "no re-checks reported" : failed ? `${plural(failed, "check")} failed` : "all re-checks passed"}
        </span>
      </div>
      {p.proposal_text != null ? (
        <p className="whitespace-pre-wrap break-words rounded border border-slate-200 bg-slate-50 p-2 font-mono text-sm">{p.proposal_text}</p>
      ) : p.proposed_cells ? (
        <p className="text-sm text-slate-700">Table with {plural(p.proposed_cells.length, "row")}.</p>
      ) : p.proposed_bbox ? (
        <p className="text-sm text-slate-700">New crop: {p.proposed_bbox.map((v) => v.toFixed(0)).join(", ")}</p>
      ) : p.proposed_attach ? (
        <p className="text-sm text-slate-700">
          Attach {p.proposed_attach.figure_id} to {p.proposed_attach.article_id}
        </p>
      ) : p.proposed_regroup ? (
        <p className="text-sm text-slate-700">
          Move {p.proposed_regroup.block_id} to {p.proposed_regroup.to_topic_slug}
        </p>
      ) : null}
      <div className="grid gap-3 text-sm md:grid-cols-2">
        <div>
          <h4 className="text-xs font-semibold text-slate-800">Re-checks</h4>
          {(p.rechecks ?? []).length ? (
            <ul className="mt-0.5 space-y-0.5" data-testid="rechecks">
              {(p.rechecks ?? []).map((r) => (
                <li key={r.check} data-outcome={r.passed ? "passed" : "failed"}>
                  <span className={r.passed ? "text-emerald-800" : "font-semibold text-red-800"}>{r.passed ? "Passed" : "Failed"}</span> {r.check.replace(/_/g, " ")}
                  {r.detail ? <span className="block text-xs text-slate-600">{r.detail}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-0.5 text-slate-600">None reported for this proposal.</p>
          )}
        </div>
        <div>
          <h4 className="text-xs font-semibold text-slate-800">Model's rationale and evidence</h4>
          <p className="mt-0.5 text-slate-700">{p.rationale}</p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {(p.evidence ?? []).map((e, i) => (
              <li key={i}>
                <span className="text-slate-600">{e.source}:</span>{" "}
                {e.verified ? (
                  <q>{e.span}</q>
                ) : (
                  <>
                    <s>{e.span}</s> <span className="text-red-800">(not found in this source)</span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
      {(p.history ?? []).length ? (
        <p className="text-xs text-slate-600">
          Tried before: {(p.history ?? []).map((h) => `${h.status}${h.reason ? ` (${h.reason})` : ""}`).join("; ")}
        </p>
      ) : null}
      {mode === "edit" ? (
        <div className="space-y-1">
          <label htmlFor={`edit-${p.id}`} className="text-xs font-medium text-slate-800">
            Your text
          </label>
          <textarea id={`edit-${p.id}`} value={text} onChange={(e) => setText(e.target.value)} rows={4} className={`w-full rounded border border-slate-400 p-2 font-mono text-sm ${FOCUS}`} />
        </div>
      ) : null}
      {mode === "reject" ? (
        <div className="space-y-1">
          <label htmlFor={`reject-${p.id}`} className="text-xs font-medium text-slate-800">
            Why is it wrong? <span className="font-normal text-slate-600">(optional, shown on the next attempt)</span>
          </label>
          <input id={`reject-${p.id}`} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} className={`w-full rounded border border-slate-400 p-1.5 text-sm ${FOCUS}`} />
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-800">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {mode === "idle" ? (
          <>
            <button type="button" disabled={busy} onClick={() => void accept()} className={BTN}>
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
              <button type="button" disabled={busy} onClick={() => void edit(true)} className={`rounded bg-red-700 px-2.5 py-1 text-sm text-white ${FOCUS}`}>
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
      <p className="text-sm text-slate-700" data-testid="calibration-unavailable">
        Calibration is not available: {errText(error)}
      </p>
    );
  if (!c) return <div aria-busy="true" className="h-16 animate-pulse rounded bg-slate-200" />;
  const used = (c.buckets ?? []).filter((b) => b.n > 0);
  const pct = (v: number | null | undefined): string => (v == null ? "n/a" : `${Math.round(v * 100)}%`);
  return (
    <div className="space-y-2 text-sm" data-testid="calibration">
      <p className="max-w-prose text-slate-700">
        How often you edited blocks at each confidence level, from {plural(c.n_outcomes ?? 0, "decision")}
        {(c.n_numeric_excluded ?? 0) > 0 ? ` (${plural(c.n_numeric_excluded ?? 0, "numeric block")} left out: they are always reviewed)` : ""}. Target edit rate{" "}
        {pct(c.target_edit_rate)}.
      </p>
      {used.length ? (
        <table className="w-full max-w-lg text-left text-sm" data-testid="calibration-table">
          <thead>
            <tr className="text-xs text-slate-600">
              <th scope="col" className="py-0.5 font-medium">Confidence</th>
              <th scope="col" className="py-0.5 text-right font-medium">Blocks</th>
              <th scope="col" className="py-0.5 text-right font-medium">Edited</th>
              <th scope="col" className="py-0.5 text-right font-medium">Edit rate</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {used.map((b) => (
              <tr key={b.lo} className="border-t border-slate-200">
                <td className="py-0.5">
                  {b.lo.toFixed(2)} to {b.hi.toFixed(2)}
                </td>
                <td className="py-0.5 text-right">{b.n}</td>
                <td className="py-0.5 text-right">{b.edited}</td>
                <td className="py-0.5 text-right">
                  {pct(b.edit_rate)}
                  {b.sparse ? <span className="text-xs text-slate-600"> (few)</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-slate-600">No decisions yet. Approve or edit blocks in Verify and the edit rates appear here.</p>
      )}
      <p data-testid="calibration-suggestion">
        Current threshold <span className="font-semibold tabular-nums">{c.current_threshold?.toFixed(2) ?? "n/a"}</span>. Suggested{" "}
        <span className="font-semibold tabular-nums">{c.suggested_threshold?.toFixed(2) ?? "none yet"}</span>
        {c.suggestion_detail ? <span className="text-slate-700">: {c.suggestion_detail}</span> : null}
      </p>
      <p className="text-xs text-slate-600">The suggestion is never applied automatically.</p>
      {(c.warnings ?? []).length ? (
        <ul role="note" className="list-disc pl-5 text-xs text-amber-900">
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
  return (
    <main className="mx-auto w-full max-w-5xl space-y-8 p-4 sm:p-6" data-testid="agent-screen">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">Agent</h2>
          <p className="mt-1 max-w-prose text-sm text-slate-700">
            Flags can be handed to a model, one fresh call per item. Every proposal is re-checked by the same deterministic checks before you see it; failed checks are shown, not hidden.
          </p>
        </div>
        <Link className={`text-sm ${LINK}`} to="/scope">
          Back to Scope
        </Link>
      </div>
      <FlagsSection flags={flags.data} items={itemMap} error={flags.error} />
      <section aria-labelledby="proposals-title" className="space-y-2" data-testid="agent-proposals">
        <h3 id="proposals-title" className="text-base font-semibold text-slate-950">
          Proposals waiting for you <span className="font-normal tabular-nums text-slate-600">{proposals.data ? list.length : ""}</span>
        </h3>
        {proposals.isError ? (
          <p className="text-sm text-slate-700">Proposals are not available: {errText(proposals.error)}</p>
        ) : proposals.data && list.length === 0 ? (
          <p className="text-sm text-slate-700">None. Run the agent pass on open flags and its proposals are listed here.</p>
        ) : proposals.data ? (
          <ul className="divide-y divide-slate-200 rounded border border-slate-300 bg-white">
            {list.map((p) => (
              <ProposalItem key={p.id} p={p} />
            ))}
          </ul>
        ) : (
          <div aria-busy="true" className="h-16 animate-pulse rounded bg-slate-200" />
        )}
        <p className="text-xs text-slate-600">A rejected proposal sends its block back to the Verify queue with what was tried.</p>
      </section>
      <section aria-labelledby="calibration-title" className="space-y-2">
        <h3 id="calibration-title" className="text-base font-semibold text-slate-950">
          Calibration
        </h3>
        <Calibration c={calibration.data} error={calibration.error} />
      </section>
    </main>
  );
}
