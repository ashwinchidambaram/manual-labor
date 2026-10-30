import { useCallback, useEffect, useRef } from "react";
import { useSources } from "../api/queries";
import type { BlockDetail, DiffOp, EditConflict } from "../api/schema";
import ChecksList from "../onboarding/ChecksList";
import Hint from "../onboarding/Hint";
import { Keycap } from "../onboarding/Copy";
import { keyLabel } from "../onboarding/guide";
import DiffView, { Marked } from "./DiffView";
import EditConflictPanel from "./EditConflictPanel";
import { numericRanges } from "./diffSegments";
import { FOCUS, SCORE_TITLE, STATUS_LABEL, scoreText } from "./labels";
import LearningChip from "./LearningChip";
import { READER } from "./parserDiff";
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
  threshold: number | null;
  /** the block's human title (section heading, document or page), from its queue card */
  title: string | null;
  /** rendered at the end of the evidence column (the figure rail) */
  aside?: React.ReactNode;
}

const STATUS_TONE: Record<string, string> = {
  queued: "bg-needs-wash text-needs-ink",
  auto_approved: "bg-done-wash text-done-ink",
  approved: "bg-done-wash text-done-ink",
  edited: "bg-done-wash text-done-ink",
  flagged: "bg-sunk text-ink ring-1 ring-inset ring-line-strong",
  rejected: "bg-sunk text-ink ring-1 ring-inset ring-line-strong",
};

/**
 * The block's text and the evidence about it (region "Extracted text"). From the `split` breakpoint the text and the
 * evidence sit side by side (the evidence `--evidence-w` wide) and scroll on their own; below it they stack in one
 * scrolling column. On a low window the header moves under the text, so the text sits right under the page strip:
 * title and ids above it, the Text/Diff toggle and the provenance line below it (design 13 section 9.3).
 */
export default function ExtractedPane({ detail, loading, error, view, onView, edit, onEditText, onConfirmConflict, onKeepEditing, threshold, title, aside }: Props) {
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
      <section role="region" aria-label="Extracted text" className="min-h-0 flex-1 px-4 py-5 text-sm wide:overflow-auto wide:px-7" data-zone="extracted">
        {error ? (
          <p role="alert" className="text-fail">
            {error}
          </p>
        ) : loading ? (
          <div aria-busy="true" role="status" aria-label="Loading block" className="max-w-[62ch] space-y-3">
            <div className="h-6 w-1/2 animate-pulse rounded bg-sunk" />
            <div className="h-24 animate-pulse rounded bg-sunk" />
          </div>
        ) : (
          <p className="text-muted">No block selected</p>
        )}
        {aside}
      </section>
    );

  const b = detail.block;
  const ops = diffOps(detail);
  const display = b.clean_text ?? b.raw_text;
  const isFigure = b.type === "figure";
  const stale = (detail.why ?? []).filter((w) => w.kind === "stale");
  const fig = isFigure ? (detail.figures ?? []).find((f) => f.block_id === b.id) : undefined;
  const figUrl = b.figure_id ? `/api/figures/${b.figure_id}/image${fig ? `?v=${fig.record.phash}` : ""}` : null;
  // provenance: where this text came from (design 12 section 2.5)
  const src = (sources.data ?? []).find((s) => s.slug === b.doc_id);
  const readers = Object.keys(detail.parser_texts ?? {});
  const provenance = [
    src?.filename ?? b.doc_id,
    src?.kind === "docx" ? "Word document, no page image" : `page ${b.page}`,
    readers.length ? `read by ${readers.map((r) => READER[r] ?? r).join(" and ")}` : null,
  ].filter(Boolean);

  return (
    <section
      role="region"
      aria-label="Extracted text"
      className="min-h-0 flex-1 wide:overflow-auto split:grid split:grid-cols-[minmax(0,1fr)_var(--evidence-w)] split:overflow-hidden"
      data-zone="extracted"
      data-testid="extracted-pane"
    >
      {/* height variants are stacked under `wide:` where they override a `wide:` value (screens are emitted last) */}
      <div className="flex min-w-0 flex-col gap-3 px-4 pb-6 pt-3 low:gap-2.5 short:gap-2 short:pt-2 wide:gap-4 wide:px-7 wide:pt-5 wide:low:gap-2.5 wide:low:pt-3 wide:short:gap-2 wide:short:pt-2 split:overflow-auto">
        <header className="flex flex-col gap-1 low:contents">
          <p className="text-xs text-muted low:order-2" data-testid="provenance">
            {provenance.join(" · ")}
          </p>
          {/* below `wide` the current queue card right above already carries the title */}
          <h3 className="text-xl font-semibold tracking-[-0.01em] text-ink max-wide:sr-only low:text-lg">{title ?? `Page ${b.page}, ${b.type}`}</h3>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-mono text-xs text-muted" data-testid="block-id">
              {b.id}
            </span>
            <span className="font-mono text-xs text-muted">{b.type}</span>
            <span className="text-xs tabular-nums text-muted" data-testid="block-confidence" title={SCORE_TITLE}>
              {scoreText(b.confidence, threshold)}
            </span>
            <Hint id="statusChip">
              <span className={`rounded-full px-2 py-px text-2xs font-semibold ${STATUS_TONE[b.status] ?? "bg-sunk text-ink"}`} data-testid="block-status">
                {STATUS_LABEL[b.status] ?? b.status}
              </span>
            </Hint>
            {isContentChangeEdit(detail) ? (
              <span data-testid="content-change-marker" className="rounded-full bg-fail-wash px-2 py-px text-2xs font-semibold text-fail ring-1 ring-inset ring-fail-line">
                <span aria-hidden="true">✕ </span>human edit: content changed
              </span>
            ) : null}
            {b.numbers_verified ? (
              <Hint id="numbersVerified">
                <span className="rounded-full bg-done-wash px-2 py-px text-2xs font-semibold text-done-ink" data-testid="numbers-verified">
                  <span aria-hidden="true">✓ </span>numbers verified by you
                </span>
              </Hint>
            ) : null}
            {stale.map((w) => (
              <span key={w.name} data-testid="stale-chip" className="rounded-full bg-needs-wash px-2 py-px text-2xs font-semibold text-needs-ink">
                {w.name}
              </span>
            ))}
          </p>
        </header>
        {/* below `wide`, and on a low window, the passage comes straight after the id line, right under the page strip */}
        <div className="flex flex-wrap items-center justify-between gap-2 max-wide:order-1 low:order-1">
          <Hint id="textDiff" within>
            <span className="inline-flex rounded-xl bg-sunk p-[3px] ring-1 ring-inset ring-line-soft" role="group" aria-label="Original vs cleaned">
              <button
                type="button"
                data-testid="view-text"
                aria-pressed={view === "text"}
                onClick={() => onView("text")}
                className={`min-h-[2rem] rounded-[9px] px-3 text-sm ${view === "text" ? "bg-raised font-semibold text-ink shadow-[0_1px_2px_rgb(39_32_26/0.12)]" : "font-medium text-muted hover:text-ink"} ${FOCUS}`}
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
                className={`min-h-[2rem] rounded-[9px] px-3 text-sm disabled:opacity-50 ${view === "diff" ? "bg-raised font-semibold text-ink shadow-[0_1px_2px_rgb(39_32_26/0.12)]" : "font-medium text-muted hover:text-ink"} ${FOCUS}`}
              >
                Diff vs raw
              </button>
            </span>
          </Hint>
          <span className="hidden items-center gap-1.5 text-xs text-muted sm:flex">
            <Keycap>{keyLabel("vToggleDiff")}</Keycap> shows every change cleanup made
          </span>
        </div>

        {isFigure ? (
          <div data-testid="figure-block" className="space-y-2 text-sm">
            {figUrl ? <img src={figUrl} alt={`Figure ${b.figure_id}`} className="max-h-72 max-w-full rounded-lg border border-line bg-page" /> : null}
            <p className="manual-text text-read text-ink">{fig?.record.caption_original ?? b.raw_text}</p>
            {fig ? (
              <dl className="grid grid-cols-[7rem_1fr] gap-y-0.5 text-xs text-muted">
                <dt>Extraction</dt>
                <dd className="text-ink">{fig.record.extraction}</dd>
                <dt>Page</dt>
                <dd className="text-ink">{fig.record.page}</dd>
                <dt>Size</dt>
                <dd className="text-ink">
                  {fig.record.width} x {fig.record.height}
                </dd>
              </dl>
            ) : null}
            <p className="text-xs text-muted">Figure blocks are fixed via the rail</p>
          </div>
        ) : edit ? (
          <div data-zone="edit" className="space-y-2">
            {edit.conflict ? <EditConflictPanel conflict={edit.conflict} onConfirm={onConfirmConflict} onKeep={onKeepEditing} busy={edit.busy} /> : null}
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
              className={`manual-text w-full max-w-[62ch] rounded-xl border border-line-strong bg-raised p-3 text-read text-ink ${FOCUS} ${edit.conflict ? "bg-sunk text-muted opacity-60" : ""}`}
            />
            {edit.error ? (
              <p role="alert" data-testid="edit-error" className="text-sm text-fail">
                {edit.error}
              </p>
            ) : null}
            <p className="text-xs text-muted">
              {edit.conflict ? "Text is locked while the content change is open. Esc to dismiss and edit again" : "Ctrl or Cmd + Enter saves, Esc cancels"}
            </p>
          </div>
        ) : view === "diff" && ops ? (
          <div className="manual-text max-w-[62ch] text-[length:var(--read-size)] leading-[1.7] text-ink">
            <DiffView ops={ops} />
          </div>
        ) : (
          <p className="manual-text max-w-[62ch] whitespace-pre-wrap break-words text-[length:var(--read-size)] leading-[1.7] text-ink" data-testid="block-text">
            <Marked text={display} ranges={numericRanges(display)} />
          </p>
        )}
        {!isFigure && b.clean_text === null && view === "diff" ? <p className="text-sm text-muted">No cleanup yet; text is raw</p> : null}
      </div>

      <div className="flex min-w-0 flex-col gap-6 border-line px-4 pb-8 pt-5 wide:px-7 split:overflow-auto split:border-l split:bg-paper split:px-5" data-testid="evidence">
        <WhyList
          why={detail.why ?? []}
          autoApproved={b.status === "auto_approved" ? { confidence: b.confidence ?? null, threshold } : null}
          parserTexts={detail.parser_texts ?? {}}
          faithfulnessPassed={b.faithfulness ? b.faithfulness.passed : null}
          rawSource={b.raw_source ?? null}
        />
        <ChecksList block={b} figure={fig ?? null} why={detail.why ?? []} />
        <LearningChip learning={detail.learning ?? { provenance: "baseline", learned_rules: [], few_shot: [] }} slug={b.doc_id} />
        {aside}
      </div>
    </section>
  );
}
