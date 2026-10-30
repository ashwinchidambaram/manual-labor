// "Your next step" on Verify (design 13 section 2.10 question 2): built only from this block's own signals, so it
// never says more than the checks did. Pure, unit-tested in coach.test.ts.
import type { BlockDetail } from "../api/schema";
import type { NextStep } from "../shell/nextStep";
import { weakestFromDetail } from "./labels";
import { pickPair, readingLines } from "./parserDiff";

export const DECISION_KEYS: NonNullable<NextStep["keys"]> = [
  { id: "vApprove", label: "Approve: it matches the page" },
  { id: "vEdit", label: "Edit: fix it yourself" },
  { id: "vFlag", label: "Flag: hand it to the Agent" },
  { id: "vSkip", label: "Skip for now" },
  { id: "vBack", label: "Back to the previous one" },
];

const list = (xs: string[]): string => (xs.length <= 1 ? (xs[0] ?? "") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

export function coachFor(d: BlockDetail | undefined, weakestWord?: string | null): NextStep {
  if (!d) return { text: "Check each block against its page.", keys: DECISION_KEYS };
  const b = d.block;
  const why = d.why ?? [];
  const held = (n: string) => why.find((w) => w.kind === "signal" && w.name === n && (w.value ?? 1) < 1);
  if (b.type === "figure") return { text: "Check the figure and its crop against the page.", keys: DECISION_KEYS };
  if (b.faithfulness && !b.faithfulness.passed)
    return { text: "Cleanup changed words in this block. Read the diff ({vToggleDiff}) against the page before you decide.", keys: DECISION_KEYS };
  if (why.some((w) => w.kind === "stale")) return { text: "The text changed since you approved it. Compare it with the page again.", keys: DECISION_KEYS };
  if (b.status === "auto_approved") return { text: "The checks cleared this block; you are taking a second look. Compare it with the page.", keys: DECISION_KEYS };
  const parts: string[] = [];
  if (held("parser_agreement") || held("textlayer_vs_ocr")) {
    const pair = pickPair(d.parser_texts ?? {});
    const lines = pair ? readingLines(pair.ta, pair.tb).map((l) => l.line) : [];
    const uniq = [...new Set(lines)].slice(0, 3);
    parts.push(uniq.length ? `line${uniq.length > 1 ? "s" : ""} ${list(uniq.map(String))}` : "the lines where the readings differ");
  }
  const weak = held("ocr_min") ? (weakestFromDetail(held("ocr_min")?.detail) ?? weakestWord ?? null) : null;
  if (weak) parts.push(`the word "${weak}"`);
  if (b.has_numeric_spec) parts.push("every number");
  if (!parts.length) return { text: "Compare the text with the page, then decide.", keys: DECISION_KEYS };
  return { text: `Compare ${list(parts)} with the page, then decide.`, keys: DECISION_KEYS };
}
