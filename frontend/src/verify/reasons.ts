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

/** The server lists queue reasons as names only; the leading `critical_reasons` ones were critical (gap G3). */
const CRITICAL_FALLBACK = new Set(["faithfulness", "figure_method"]);
export function reasonsFromQueueItem(reasons: string[], hasNumeric: boolean, criticalReasons?: number): ReasonIn[] {
  void hasNumeric;
  return reasons.map((name, i) => ({
    kind: name === STALE_NAME ? "stale" : "signal",
    name,
    value: 0,
    critical: criticalReasons !== undefined ? i < criticalReasons : CRITICAL_FALLBACK.has(name),
  }));
}
