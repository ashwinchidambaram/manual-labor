// Reason chips for queue cards and the extracted pane header (design 09 section 1, "Reason chips").
import { label, STALE_NAME } from "./labels";

export interface ReasonIn {
  kind: string;
  name: string;
  value: number | null;
  critical: boolean;
}
export interface Chip {
  name: string;
  text: string;
  tone: "critical" | "soft" | "rule" | "status";
}
export interface ReasonChips {
  status: Chip[];
  reasons: Chip[];
  overflow: string[];
}

const NUMERIC = "has_numeric_spec";
const byValue = (a: ReasonIn, b: ReasonIn): number => {
  if (a.value === null || b.value === null) return 0; // null keeps server order
  return a.value - b.value || a.name.localeCompare(b.name);
};
const chip = (r: ReasonIn, tone: Chip["tone"]): Chip => ({ name: r.name, text: label(r.name), tone });

export function reasonChips({ why, hasNumeric, max = 3 }: { why: ReasonIn[]; hasNumeric: boolean; max?: number }): ReasonChips {
  const status = why.filter((w) => w.kind === "stale").map((w): Chip => ({ name: w.name, text: w.name, tone: "status" }));
  const signals = why.filter((w) => w.kind === "signal" && (w.value ?? 0) < 1);
  const crit = signals.filter((w) => w.critical && w.name !== NUMERIC).sort(byValue);
  const soft = signals.filter((w) => !w.critical && w.name !== NUMERIC).sort(byValue);
  const rule = hasNumeric ? 1 : 0;
  const critTaken = crit.slice(0, max - rule);
  const softTaken = soft.slice(0, Math.max(0, max - rule - critTaken.length));
  const reasons: Chip[] = critTaken.map((w) => chip(w, "critical"));
  if (hasNumeric) reasons.push({ name: NUMERIC, text: label(NUMERIC), tone: "rule" });
  reasons.push(...softTaken.map((w) => chip(w, "soft")));
  const taken = new Set([...critTaken, ...softTaken]);
  const overflow = [...crit, ...soft].filter((w) => !taken.has(w)).map((w) => label(w.name));
  return { status, reasons, overflow };
}

/**
 * The server lists queue reasons as names only; the leading `critical_reasons` ones were critical (gap G3).
 * Until that field exists the criticality is derived the way the scorer assigns it: faithfulness and figure_method
 * always; the two agreement signals and the weakest-OCR-word signal only on numeric blocks. Values are unknown on a
 * card (null), so criticals are put in a fixed priority order instead of by value.
 */
const CRITICAL_ALWAYS = ["faithfulness", "figure_method"];
const CRITICAL_IF_NUMERIC = ["parser_agreement", "textlayer_vs_ocr", "ocr_min"];
const PRIORITY = [...CRITICAL_ALWAYS, ...CRITICAL_IF_NUMERIC];
export function reasonsFromQueueItem(reasons: string[], hasNumeric: boolean, criticalReasons?: number): ReasonIn[] {
  const isCritical = (name: string, i: number): boolean =>
    criticalReasons !== undefined ? i < criticalReasons : CRITICAL_ALWAYS.includes(name) || (hasNumeric && CRITICAL_IF_NUMERIC.includes(name));
  const out = reasons.map((name, i): ReasonIn => ({
    kind: name === STALE_NAME ? "stale" : "signal",
    name,
    value: null,
    critical: isCritical(name, i),
  }));
  if (criticalReasons !== undefined) return out;
  const rank = (n: string): number => PRIORITY.indexOf(n);
  return [...out.filter((r) => r.critical).sort((a, b) => rank(a.name) - rank(b.name)), ...out.filter((r) => !r.critical)];
}
