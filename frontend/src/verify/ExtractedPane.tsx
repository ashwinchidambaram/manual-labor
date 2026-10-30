import { useCallback, useEffect, useRef } from "react";
import { useSources } from "../api/queries";
import type { BlockDetail, DiffOp, EditConflict } from "../api/schema";
import ChecksList from "../onboarding/ChecksList";
import Hint from "../onboarding/Hint";
import { signalHint } from "../onboarding/hints";
import DiffView, { Marked } from "./DiffView";
import EditConflictPanel from "./EditConflictPanel";
import { numericRanges } from "./diffSegments";
import { FOCUS, STATUS_LABEL } from "./labels";
import LearningChip from "./LearningChip";
import ParserCompare from "./ParserCompare";
import { reasonChips } from "./reasons";
import WhyList from "./WhyList";

export interface EditState {
  text: string;
  error: string | null;
  conflict: EditConflict | null;
  /** the exact text that produced `conflict`; Confirm sends this, never the live textarea value */
  conflictText: string | null;
  busy: boolean;
}

/** Source of the diff ops (design 09 section 4): the human edit, else the machine cleanup, else nothing. */
export function diffOps(d: BlockDetail): DiffOp[] | null {
  if (d.block.status === "edited") {
    const h = [...(d.history ?? [])].reverse().find((x) => x.human_edit_diff);
    if (h?.human_edit_diff) return h.human_edit_diff;
  }
  return d.block.faithfulness?.diff ?? null;
}

/** The latest human edit was confirmed past a faithfulness violation (faith_passed=false on its decision record). */
export function isContentChangeEdit(d: BlockDetail): boolean {
  if (d.block.status !== "edited") return false;
  const h = [...(d.history ?? [])].reverse().find((x) => x.human_edit_diff || x.faith_passed !== undefined);
  return h?.faith_passed === false;
}

interface Props {
  detail: BlockDetail | undefined;
  loading: boolean;
  error: string | null;
  view: "text" | "diff";
  onView: (v: "text" | "diff") => void;
  edit: EditState | null;
  onEditText: (t: string) => void;
  onConfirmConflict: () => void;
  onKeepEditing: () => void;
  threshold: number;
}

export default function ExtractedPane({ detail, loading, error, view, onView, edit, onEditText, onConfirmConflict, onKeepEditing, threshold }: Props) {
  const area = useRef<HTMLTextAreaElement | null>(null);
  // focus on mount: the textarea may appear after the edit started (the block's detail arrives late)
  const setArea = useCallback((el: HTMLTextAreaElement | null) => {
    area.current = el;
    if (el) {
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
  }, []);
  const editing = edit !== null;
  const sources = useSources();
  useEffect(() => {
    if (!editing || edit?.conflict) return;
    const take = (): void => {
      const el = area.current;
      if (el && document.activeElement !== el) {
        el.focus();
        el.setSelectionRange(el.value.length, el.value.length);
      }
    };
    take();
    // something else (a pending queue-card focus request) may grab focus in the same tick: take it back next frame
    const raf = requestAnimationFrame(take);
    return () => cancelAnimationFrame(raf);
  }, [editing, edit?.conflict]);

  if (!detail)
    return (
      <section role="region" aria-label="Extracted text" className="min-h-0 overflow-auto p-3 text-sm" data-zone="extracted">
        {error ? <p role="alert" className="text-red-800">{error}</p> : <p className="text-slate-600">{loading ? "Loading block..." : "No block selected"}</p>}
      </section>
    );

  const b = detail.block;
  const ops = diffOps(detail);
  const display = b.clean_text ?? b.raw_text;
  const isFigure = b.type === "figure";
  const chips = reasonChips({ why: (detail.why ?? []).map((w) => ({ kind: w.kind, name: w.name, value: w.value ?? null, critical: w.critical })), hasNumeric: b.has_numeric_spec, max: 6 });
  const fig = isFigure ? (detail.figures ?? []).find((f) => f.block_id === b.id) : undefined;
  const figUrl = b.figure_id ? `/api/figures/${b.figure_id}/image${fig ? `?v=${fig.record.phash}` : ""}` : null;
  // provenance: where this text came from (design 12 section 2.5)
  const src = (sources.data ?? []).find((s) => s.slug === b.doc_id);
  const readers = Object.keys(detail.parser_texts ?? {});
  const provenance = [
    src?.filename ?? b.doc_id,
    src?.kind === "docx" ? "Word document, no page image" : `page ${b.page}`,
    readers.length ? `read by ${readers.join(", ")}` : null,
  ].filter(Boolean);

  return (
    <section role="region" aria-label="Extracted text" className="flex min-h-0 flex-col gap-3 overflow-auto p-3" data-zone="extracted" data-testid="extracted-pane">
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm" data-testid="block-id">
          {b.id}
        </span>
        <span className="text-xs text-slate-600">{b.type}</span>
        <span className="text-xs tabular-nums text-slate-700" data-testid="block-confidence">
          {b.confidence === null || b.confidence === undefined ? "n/a" : b.confidence.toFixed(2)}
        </span>
        <Hint id="statusChip">
          <span className="rounded bg-slate-200 px-1.5 text-xs" data-testid="block-status">
            {STATUS_LABEL[b.status] ?? b.status}
          </span>
        </Hint>
        {isContentChangeEdit(detail) ? (
          <span data-testid="content-change-marker" className="rounded border border-red-500 bg-red-100 px-1.5 text-xs font-semibold text-red-900">
            human edit {"\u2014"} content changed
          </span>
        ) : null}
        {b.numbers_verified ? (
          <Hint id="numbersVerified">
            <span className="rounded bg-emerald-100 px-1.5 text-xs text-emerald-900" data-testid="numbers-verified">
              numbers verified by you
            </span>
          </Hint>
        ) : null}
        {chips.status.map((c) => (
          <span key={c.name} data-testid="stale-chip" className="rounded bg-amber-100 px-1.5 text-xs text-amber-950">
            {c.text}
          </span>
        ))}
        {chips.reasons.map((c) => (
          <Hint key={c.name} id="reasonChip" text={signalHint(c.name) ?? undefined}>
            <span className={`rounded px-1.5 text-xs ${c.tone === "critical" ? "bg-red-100 text-red-900" : c.tone === "rule" ? "bg-violet-100 text-violet-900" : "bg-slate-200"}`}>
              {c.text}
            </span>
          </Hint>
        ))}
        <Hint id="textDiff" within>
        <span className="ml-auto flex items-center gap-1" role="group" aria-label="Original vs cleaned">
          <span aria-hidden="true" className="mr-0.5 hidden text-xs text-slate-600 2xl:inline">
            Original vs cleaned
          </span>
          <button
            type="button"
            data-testid="view-text"
            aria-pressed={view === "text"}
            onClick={() => onView("text")}
            className={`rounded border px-2 text-xs ${view === "text" ? "border-slate-900 bg-slate-900 text-white" : "border-slate-400"} ${FOCUS}`}
          >
            Text
          </button>
          <button
            type="button"
            data-testid="view-diff"
            aria-pressed={view === "diff"}
            disabled={ops === null}
            title={ops === null ? "No cleanup yet; text is raw" : undefined}
            onClick={() => onView("diff")}
            className={`rounded border px-2 text-xs disabled:opacity-50 ${view === "diff" ? "border-slate-900 bg-slate-900 text-white" : "border-slate-400"} ${FOCUS}`}
          >
            Diff vs raw
          </button>
        </span>
        </Hint>
        <p className="basis-full text-xs text-slate-600" data-testid="provenance">
          {provenance.join(" · ")}
        </p>
      </header>

      {isFigure ? (
        <div data-testid="figure-block" className="space-y-1 text-sm">
          {figUrl ? <img src={figUrl} alt={`Figure ${b.figure_id}`} className="max-h-72 max-w-full border border-slate-300 bg-white" /> : null}
          <p>{fig?.record.caption_original ?? b.raw_text}</p>
          {fig ? (
            <dl className="grid grid-cols-[7rem_1fr] text-xs text-slate-700">
              <dt>Extraction</dt>
              <dd>{fig.record.extraction}</dd>
              <dt>Page</dt>
              <dd>{fig.record.page}</dd>
              <dt>Size</dt>
              <dd>
                {fig.record.width} x {fig.record.height}
              </dd>
            </dl>
          ) : null}
          <p className="text-xs text-slate-600">Figure blocks are fixed via the rail</p>
        </div>
      ) : edit ? (
        <div data-zone="edit" className="space-y-2">
          {edit.conflict ? (
            <EditConflictPanel conflict={edit.conflict} onConfirm={onConfirmConflict} onKeep={onKeepEditing} busy={edit.busy} />
          ) : null}
          <textarea
            ref={setArea}
            autoFocus
            aria-label="Edit block text"
            value={edit.text}
            onChange={(e) => onEditText(e.target.value)}
            readOnly={!!edit.conflict}
            aria-readonly={!!edit.conflict}
            onKeyDown={(e) => {
              if (e.key === "Escape" && edit.conflict) {
                e.preventDefault();
                e.stopPropagation();
                onKeepEditing();
              }
            }}
            rows={10}
            className={`w-full rounded border border-slate-400 p-2 font-mono text-sm ${FOCUS} ${edit.conflict ? "bg-slate-100 text-slate-500 opacity-60" : ""}`}
          />
          {edit.error ? (
            <p role="alert" data-testid="edit-error" className="text-sm text-red-800">
              {edit.error}
            </p>
          ) : null}
          <p className="text-xs text-slate-600">
            {edit.conflict ? "Text is locked while the content change is open. Esc to dismiss and edit again" : "Ctrl or Cmd + Enter saves, Esc cancels"}
          </p>
        </div>
      ) : view === "diff" && ops ? (
        <DiffView ops={ops} />
      ) : (
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed" data-testid="block-text">
          <Marked text={display} ranges={numericRanges(display)} />
        </p>
      )}
      {!isFigure && b.clean_text === null && view === "diff" ? <p className="text-sm text-slate-600">No cleanup yet; text is raw</p> : null}

      <WhyList
        why={detail.why ?? []}
        autoApproved={b.status === "auto_approved" ? { confidence: b.confidence ?? null, threshold } : null}
      />
      <ChecksList block={b} figure={fig ?? null} />
      <ParserCompare texts={detail.parser_texts ?? {}} block={b} />
      <LearningChip learning={detail.learning ?? { provenance: "baseline", learned_rules: [], few_shot: [] }} slug={b.doc_id} />
    </section>
  );
}
