import type { Block, FaithViolationKind, FigureRailItem, SignalName, WhyItem } from "../api/schema";
import { human, label, weakestFromDetail } from "../verify/labels";
import { CLEANUP_ALLOWED, NUMBER_CHOICE } from "./guide";

export type CheckOutcome = "passed" | "failed" | "measured" | "not_run";

export interface CheckRow {
  id: string;
  name: string;
  outcome: CheckOutcome;
  /** the visible result word(s); always text, never colour alone */
  result: string;
  /** what a person would say about it (design 13 section 2.8.1), shown before the value; null for a plain fact */
  sentence?: string | null;
  detail: string | null;
  /** the scorer's own words at the end of `detail`, verbatim (set in mono, as in "Why this needs you") */
  raw?: string | null;
}

const KIND_LABEL: Record<FaithViolationKind, string> = {
  insertion: "insertion",
  deletion: "deletion",
  numeric_mismatch: "numeric mismatch",
  reorder: "reorder",
};

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

/**
 * A 0..1 signal with two decimals, rounded down: only an exact 1 reads "1.00", so 0.996 can never look identical.
 */
export function fmtSignal(v: number): string {
  if (v >= 1) return "1.00";
  return (Math.floor(v * 100 + 1e-9) / 100).toFixed(2);
}

const SCALE: Partial<Record<SignalName, string>> = {
  parser_agreement: "1.00 = identical",
  textlayer_vs_ocr: "1.00 = identical",
  ocr_min: "1.00 = certain",
};

/**
 * The deterministic checks of one block, from the block's own data (design 12 section 2.5). Only what the API
 * reported is shown: a missing result is "Not run yet", never "Passed". Agreement signals carry a measured value
 * and no pass/fail cut from the server, so they are shown as the value with its scale and the server's `critical`
 * flag, never as a verdict.
 */
export function checkRows(block: Block, figure?: FigureRailItem | null): CheckRow[] {
  const rows: CheckRow[] = [];
  const scored = (block.signals ?? []).length > 0;
  const sig = (n: SignalName) => (block.signals ?? []).find((s) => s.name === n) ?? null;
  const notRun = (id: string, name: string, why = "Not run yet"): CheckRow => ({ id, name, outcome: "not_run", result: why, detail: null });
  const measured = (id: string, name: string, n: SignalName): CheckRow | null => {
    const s = sig(n);
    if (!s) return null;
    const weak = n === "ocr_min" ? weakestFromDetail(s.detail) : null;
    return {
      id,
      name,
      outcome: "measured",
      sentence: weak ? `Least certain word: “${weak}”` : human(n, s.value < 1),
      raw: s.detail ?? null,
      result: `${fmtSignal(s.value)} (${SCALE[n] ?? "1.00 = nothing wrong"})`,
      detail: [s.critical ? "critical for this block" : null, s.detail ?? null].filter(Boolean).join(". ") || null,
    };
  };

  if (block.type !== "figure") {
    const f = block.faithfulness ?? null;
    if (!f) {
      // a human edit is checked when it is saved (and confirmed past a violation if it changed content)
      const why = block.status === "edited" ? "Checked when you saved the edit" : "Not run yet";
      rows.push(notRun("faithfulness", "Faithfulness", why));
      rows.push(notRun("numbers", "Numbers preserved", why));
    } else {
      const counts = new Map<FaithViolationKind, number>();
      for (const v of f.violations ?? []) counts.set(v.kind, (counts.get(v.kind) ?? 0) + 1);
      const byKind = [...counts.entries()].map(([k, n]) => `${n} ${KIND_LABEL[k]}`).join(", ");
      rows.push({
        id: "faithfulness",
        name: "Faithfulness",
        outcome: f.passed ? "passed" : "failed",
        result: f.passed ? "Passed" : "Failed",
        sentence: human("faithfulness", !f.passed),
        detail: `${Math.round(f.alignment_ratio * 100)}% of the text aligns with the raw parse; ${(f.violations ?? []).length ? `${plural((f.violations ?? []).length, "violation")}: ${byKind}` : "no violations"}`,
      });
      const numeric = (f.violations ?? []).filter((v) => v.kind === "numeric_mismatch");
      const variants = f.numeric_variants ?? [];
      const chosen = variants.length
        ? `Recorded, not failed: ${variants.map((v) => `${v.raw} read as ${v.chosen} (from ${v.source === "ocr" ? "OCR" : "the text layer"})`).join("; ")}`
        : null;
      rows.push({
        id: "numbers",
        name: "Numbers preserved",
        outcome: numeric.length ? "failed" : "passed",
        result: numeric.length ? "Failed" : "Passed",
        sentence: numeric.length ? "A number changed in cleanup" : "Every number matches the raw text",
        detail: [numeric.length ? numeric.map((v) => `${v.raw || "(nothing)"} became ${v.clean || "(nothing)"}`).join("; ") : null, chosen].filter(Boolean).join(". ") || null,
      });
    }
    const pa = measured("parsers", "Parser agreement", "parser_agreement");
    if (pa) rows.push(pa);
    else rows.push(notRun("parsers", "Parser agreement", scored ? "Not measured for this block" : "Not run yet"));
    const tl = measured("textlayer", "Text layer vs OCR", "textlayer_vs_ocr");
    if (tl) rows.push(tl);
    const om = measured("ocr_min", "Weakest OCR word", "ocr_min");
    if (om) rows.push(om);
  } else {
    const method = figure?.record.extraction ?? null;
    rows.push(method ? { id: "method", name: "Extraction method", outcome: "measured", result: method, detail: sig("figure_method")?.detail ?? null } : notRun("method", "Extraction method"));
  }
  if (block.type === "figure" || block.figure_id) {
    const rule = figure?.attachment?.rule ?? null;
    const s = sig("figure_attach_rule");
    if (rule || s)
      rows.push({
        id: "attach",
        name: "Figure attach rule",
        outcome: "measured",
        result: rule ?? "unattached",
        detail: [figure?.attachment?.confidence != null ? `match ${figure.attachment.confidence.toFixed(2)}` : null, s?.detail ?? null].filter(Boolean).join(". ") || null,
      });
    else rows.push(notRun("attach", "Figure attach rule"));
  }
  return rows;
}

/** Plain reasons a block is queued, from the API's why-list (signals below 1, the numeric rule, a stale approval). */
const QUEUED_BECAUSE: Record<string, string> = {
  parser_agreement: "the parsers disagree on this block",
  textlayer_vs_ocr: "the text layer and OCR disagree",
  ocr_min: "OCR is unsure of at least one word",
  ocr_mean: "OCR is unsure of the text",
  reading_order_risk: "the reading order may be wrong",
  table_consistency: "the table's rows and columns do not line up",
  garbage_ratio: "the text has broken characters",
  llm_verifier: "the verifier model read it differently",
  has_numeric_spec: "it contains numbers, units or part numbers",
};

/** "Queued because ..." when faithfulness passed but the block still waits for a person; null otherwise. */
export function queuedBecause(block: Block, why: readonly WhyItem[]): string | null {
  if (block.status !== "queued" || !block.faithfulness?.passed) return null;
  const parts: string[] = [];
  for (const w of why) {
    if (w.kind === "stale") parts.push("the text changed since it was approved");
    else if (w.name === "has_numeric_spec") parts.push(QUEUED_BECAUSE.has_numeric_spec);
    else if (w.kind === "signal" && (w.value ?? 0) < 1 && w.name !== "faithfulness") parts.push(QUEUED_BECAUSE[w.name] ?? `${label(w.name)} is low`);
  }
  const uniq = [...new Set(parts)];
  if (!uniq.length) return null;
  const list = uniq.length === 1 ? uniq[0] : `${uniq.slice(0, -1).join(", ")} and ${uniq[uniq.length - 1]}`;
  return `Queued because ${list}.`;
}

const TONE: Record<CheckOutcome, string> = {
  passed: "font-semibold text-done-ink",
  failed: "font-semibold text-fail",
  measured: "text-ink",
  not_run: "text-muted",
};
const MARK: Record<CheckOutcome, string> = { passed: "✓", failed: "✗", measured: "·", not_run: "–" };

export default function ChecksList({ block, figure, why = [] }: { block: Block; figure?: FigureRailItem | null; why?: readonly WhyItem[] }) {
  const rows = checkRows(block, figure);
  const because = queuedBecause(block, why);
  return (
    <section aria-label="Checks on this block" className="text-sm" data-testid="checks-list">
      <h3 className="text-2xs font-semibold uppercase tracking-[0.07em] text-muted">Checks on this block</h3>
      <p className="mt-1 text-xs leading-relaxed text-muted" data-testid="checks-intro">
        {CLEANUP_ALLOWED} {NUMBER_CHOICE} Any other change fails the faithfulness check and is shown as a diff.
      </p>
      {because ? (
        <p className="mt-2 text-sm font-medium text-ink" data-testid="checks-queued-why">
          {because}
        </p>
      ) : null}
      <dl className="mt-2.5 grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-1.5">
        {rows.map((r) => (
          <div key={r.id} className="contents" data-testid={`check-${r.id}`} data-outcome={r.outcome}>
            <dt className="text-muted">{r.name}</dt>
            <dd className="min-w-0">
              {r.outcome === "measured" && r.sentence ? (
                // a measured agreement: the sentence first, then the value with its scale (never a verdict word)
                <>
                  <span className="block font-medium text-ink">{r.sentence}</span>
                  <span className="block text-xs tabular-nums text-ink">{r.result}</span>
                </>
              ) : (
                <span className={TONE[r.outcome]}>
                  <span aria-hidden="true" className="mr-1 inline-block w-3 text-center">
                    {MARK[r.outcome]}
                  </span>
                  {r.result}
                  {r.sentence ? <span className="font-normal text-ink"> · {r.sentence}</span> : null}
                </span>
              )}
              {r.detail ? (
                <span className="mt-0.5 block break-words text-2xs leading-relaxed text-muted">
                  {r.raw && r.detail.endsWith(r.raw) ? (
                    <>
                      {r.detail.slice(0, r.detail.length - r.raw.length)}
                      <span className="font-mono">{r.raw}</span>
                    </>
                  ) : (
                    r.detail
                  )}
                </span>
              ) : null}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
