import type { Block, FaithViolationKind, FigureRailItem, SignalName } from "../api/schema";

export type CheckOutcome = "passed" | "failed" | "measured" | "not_run";

export interface CheckRow {
  id: string;
  name: string;
  outcome: CheckOutcome;
  /** the visible result word(s); always text, never colour alone */
  result: string;
  detail: string | null;
}

const KIND_LABEL: Record<FaithViolationKind, string> = {
  insertion: "insertion",
  deletion: "deletion",
  numeric_mismatch: "numeric mismatch",
  reorder: "reorder",
};

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

/**
 * The deterministic checks of one block, from the block's own data (design 12 section 2.5). Only what the API
 * reported is shown: a missing result is "Not run yet", never "Passed". Agreement signals carry a measured value
 * and no pass/fail cut from the server, so they are shown as measured (1.00 means the readings are identical).
 */
export function checkRows(block: Block, figure?: FigureRailItem | null): CheckRow[] {
  const rows: CheckRow[] = [];
  const scored = (block.signals ?? []).length > 0;
  const sig = (n: SignalName) => (block.signals ?? []).find((s) => s.name === n) ?? null;
  const notRun = (id: string, name: string, why = "Not run yet"): CheckRow => ({ id, name, outcome: "not_run", result: why, detail: null });
  const measured = (id: string, name: string, n: SignalName, same: string, differ: string): CheckRow | null => {
    const s = sig(n);
    if (!s) return null;
    const v = s.value.toFixed(2);
    return {
      id,
      name,
      outcome: "measured",
      result: s.value >= 1 ? `${same} (${v})` : `${differ} (${v})`,
      detail: [s.critical ? "Critical for this block" : null, s.detail ?? null].filter(Boolean).join(". ") || null,
    };
  };

  if (block.type !== "figure") {
    const f = block.faithfulness ?? null;
    if (!f) {
      rows.push(notRun("faithfulness", "Faithfulness"));
      rows.push(notRun("numbers", "Numbers preserved"));
    } else {
      const counts = new Map<FaithViolationKind, number>();
      for (const v of f.violations ?? []) counts.set(v.kind, (counts.get(v.kind) ?? 0) + 1);
      const byKind = [...counts.entries()].map(([k, n]) => `${n} ${KIND_LABEL[k]}`).join(", ");
      rows.push({
        id: "faithfulness",
        name: "Faithfulness",
        outcome: f.passed ? "passed" : "failed",
        result: f.passed ? "Passed" : "Failed",
        detail: `${Math.round(f.alignment_ratio * 100)}% of the text aligns with the raw parse; ${(f.violations ?? []).length ? `${plural((f.violations ?? []).length, "violation")}: ${byKind}` : "no violations"}`,
      });
      const numeric = (f.violations ?? []).filter((v) => v.kind === "numeric_mismatch");
      rows.push({
        id: "numbers",
        name: "Numbers preserved",
        outcome: numeric.length ? "failed" : "passed",
        result: numeric.length ? "Failed" : "Passed",
        detail: numeric.length ? numeric.map((v) => `${v.raw || "(nothing)"} became ${v.clean || "(nothing)"}`).join("; ") : null,
      });
    }
    const pa = measured("parsers", "Parsers agree", "parser_agreement", "Agree", "Differ");
    if (pa) rows.push(pa);
    else rows.push(notRun("parsers", "Parsers agree", scored ? "Not measured for this block" : "Not run yet"));
    const tl = measured("textlayer", "Text layer matches OCR", "textlayer_vs_ocr", "Match", "Differ");
    if (tl) rows.push(tl);
    const om = sig("ocr_min");
    if (om) rows.push({ id: "ocr_min", name: "Weakest OCR word", outcome: "measured", result: om.value.toFixed(2), detail: om.detail ?? null });
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

const TONE: Record<CheckOutcome, string> = {
  passed: "text-emerald-800",
  failed: "font-semibold text-red-800",
  measured: "text-slate-800",
  not_run: "text-slate-600",
};
const MARK: Record<CheckOutcome, string> = { passed: "✓", failed: "✗", measured: "·", not_run: "–" };

export default function ChecksList({ block, figure }: { block: Block; figure?: FigureRailItem | null }) {
  const rows = checkRows(block, figure);
  return (
    <section aria-label="Checks on this block" className="text-sm" data-testid="checks-list">
      <h3 className="font-semibold">Checks on this block</h3>
      <p className="mt-0.5 text-xs text-slate-600">
        Cleanup can only fix spacing, hyphenation, headers and reading order. Any other change is caught here and shown as a diff.
      </p>
      <dl className="mt-1.5 grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-1">
        {rows.map((r) => (
          <div key={r.id} className="contents" data-testid={`check-${r.id}`} data-outcome={r.outcome}>
            <dt className="text-slate-700">{r.name}</dt>
            <dd className="min-w-0">
              <span className={TONE[r.outcome]}>
                <span aria-hidden="true" className="mr-1 inline-block w-3 text-center">
                  {MARK[r.outcome]}
                </span>
                {r.result}
              </span>
              {r.detail ? <span className="block break-words text-xs text-slate-600">{r.detail}</span> : null}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
