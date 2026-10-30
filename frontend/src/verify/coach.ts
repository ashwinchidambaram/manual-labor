// "Your next step" on Verify (design 13 section 2.10 question 2): built only from this block's own signals, so it
// never says more than the checks did. Pure, unit-tested in coach.test.ts.
import type { BlockDetail } from "../api/schema";
import type { NextStep } from "../shell/nextStep";
import { weakestFromDetail } from "./labels";
import { pairForSignal, readingLines } from "./parserDiff";

export const DECISION_KEYS: NonNullable<NextStep["keys"]> = [
  { id: "vApprove", label: "Approve: it matches the page" },
  { id: "vEdit", label: "Edit: fix it yourself" },
  { id: "vFlag", label: "Flag: hand it to the Agent" },
  { id: "vSkip", label: "Skip for now" },
  { id: "vBack", label: "Back to the previous one" },
];

const list = (xs: string[]): string => (xs.length <= 1 ? (xs[0] ?? "") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** The first words of a line, as the user sees them in the readings list (a line number alone cannot be found). */
const opening = (s: string): string => {
  const w = s.replace(/\s+/g, " ").trim().split(" ");
  return `"${w.slice(0, 4).join(" ")}${w.length > 4 ? "…" : ""}"`;
};

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
  const reading = held("parser_agreement") ?? held("textlayer_vs_ocr");
  if (reading) {
    // the same pair the "Why this needs you" card shows for this signal
    const pair = pairForSignal(reading.name, d.parser_texts ?? {}, reading.detail, b.raw_source);
    const lines = pair ? readingLines(pair.ta, pair.tb).filter((l) => (l.a || l.b).trim()) : [];
    const shown = lines.slice(0, 3);
    parts.push(
      shown.length === 0
        ? "the two readings"
        : shown.length === 1
          ? `the line that starts ${opening(shown[0].a || shown[0].b)}`
          : shown.length === 2
            ? `the lines that start ${shown.map((l) => opening(l.a || l.b)).join(" and ")}`
            : `the ${shown.length} lines under "The two readings differ"`,
    );
  }
  const weak = held("ocr_min") ? (weakestFromDetail(held("ocr_min")?.detail) ?? weakestWord ?? null) : null;
  if (weak) parts.push(`the word "${weak}"`);
  if (b.has_numeric_spec) parts.push("every number");
  if (!parts.length) return { text: "Compare the text with the page, then decide.", keys: DECISION_KEYS };
  return { text: `Compare ${list(parts)} with the page, then decide.`, keys: DECISION_KEYS };
}
