import type { FlagCategory } from "../api/schema";

// Plain-language names for scoring signals (design 09 section 1).
export const SIGNAL_LABEL: Record<string, string> = {
  parser_agreement: "parsers disagree",
  textlayer_vs_ocr: "text layer ≠ OCR",
  ocr_min: "weak OCR word",
  ocr_mean: "low OCR",
  reading_order_risk: "reading order",
  table_consistency: "table shape",
  garbage_ratio: "garbled text",
  faithfulness: "cleanup changed content",
  figure_method: "figure crop",
  figure_resolution: "low-res figure",
  figure_attach_rule: "weak figure match",
  llm_verifier: "verifier disagrees",
  has_numeric_spec: "numeric spec",
};
export const label = (name: string): string => SIGNAL_LABEL[name] ?? name.replace(/_/g, " ");

/**
 * What a person would say about each signal (design 13 section 2.8.2): `held` when it kept the block for you (value
 * under 1), `passed` when it found nothing wrong (1.00). The short signal name and the number follow as secondary text;
 * this is the only place these sentences are written.
 */
export const SIGNAL_HUMAN: Record<string, { held: string; passed: string }> = {
  parser_agreement: { held: "The two readings differ", passed: "The two readings agree" },
  textlayer_vs_ocr: { held: "The PDF text and the scan differ", passed: "The PDF text and the scan agree" },
  ocr_min: { held: "The scanner was unsure of a word", passed: "The scanner was sure of every word" },
  ocr_mean: { held: "The scan is faint", passed: "The scan reads clearly" },
  reading_order_risk: { held: "The reading order may be wrong", passed: "The reading order agrees" },
  table_consistency: { held: "Table rows or columns do not line up", passed: "The table lines up" },
  garbage_ratio: { held: "Garbled characters", passed: "No garbled characters" },
  faithfulness: { held: "Cleanup changed words", passed: "Cleanup kept every word" },
  figure_method: { held: "Figure cut from the page image", passed: "Figure taken from the file itself" },
  figure_resolution: { held: "Low-resolution figure", passed: "Figure resolution is enough" },
  figure_attach_rule: { held: "Unsure this figure belongs here", passed: "The figure's place is certain" },
  llm_verifier: { held: "A second model pointed at a change cleanup made", passed: "A second model found no change to question" },
  has_numeric_spec: { held: "Has numbers, so a person always checks it", passed: "Has numbers, so a person always checks it" },
};
export const human = (name: string, held: boolean): string => SIGNAL_HUMAN[name]?.[held ? "held" : "passed"] ?? label(name);

/** The faithfulness signal's detail on a block whose cleanup has not run (manuallabor/scoring/pipeline.py). */
export const FAITH_NOT_RUN = "raw (no cleanup yet)";

/**
 * A passed faithfulness check scored under 1 (manuallabor/scoring/pipeline.py): 0.5 when a model's cleanup was
 * rejected and the deterministic result kept, 0.9 when it passed through an evidence-backed reorder. The sentence is
 * taken from the detail the scorer wrote, never from the number.
 */
export function faithHeldSentence(detail: string | null | undefined): string {
  const d = detail ?? "";
  if (d.startsWith("cleanup candidate rejected")) return "A model's cleanup was rejected; the deterministic cleanup was kept";
  if (d.includes("reorder")) return "Passed after a reading-order fix backed by the page";
  return "Cleanup passed with a note";
}

/** The least certain word, from the OCR signal's detail ("min 0.899 at '4471-A'; 68 words"). */
export function weakestFromDetail(detail: string | null | undefined): string | null {
  const m = /at '(.+?)'(?:;|$)/.exec(detail ?? "");
  return m ? m[1] : null;
}

export const STALE_NAME = "changed since approval";

export const STATUS_LABEL: Record<string, string> = {
  queued: "queued",
  auto_approved: "auto-approved",
  approved: "approved",
  edited: "edited",
  flagged: "flagged",
  rejected: "rejected",
};

// Labels are keyed by the generated FlagCategory, so a category added to the contract fails the typecheck here.
const FLAG_LABEL: Record<FlagCategory, string> = {
  wrong_text: "Wrong text",
  missing_figure: "Missing figure",
  wrong_grouping: "Wrong grouping",
  bad_crop: "Bad crop",
  table_structure: "Table structure",
};
/** Display order (digits 1-5 in the flag dialog). */
const FLAG_ORDER = ["wrong_text", "missing_figure", "wrong_grouping", "bad_crop", "table_structure"] as const satisfies readonly FlagCategory[];
type Missing = Exclude<FlagCategory, (typeof FLAG_ORDER)[number]>;
const _allCategoriesOrdered: Missing extends never ? true : never = true;
void _allCategoriesOrdered;
export const FLAG_CATEGORIES: { id: FlagCategory; label: string }[] = FLAG_ORDER.map((id) => ({ id, label: FLAG_LABEL[id] }));

/**
 * How a flag is resolved, in one sentence used by the flag dialog, the Verify flag notice and the Export screen (design 09
 * section 10). True to the server: an approve or edit resolves a block's open flags (state/review.py), so does an
 * accepted or edited agent proposal (agent/service.py); the export gate covers a flag only with an override that names
 * it or a blanket override (export/gate.py `_covers_flag`), and the blanket one is recorded only by the CLI.
 */
export const FLAG_RESOLUTION =
  "A flag locks the export until you approve or edit the block in Verify, accept the agent's fix on the Agent screen, or record an override that names the flag on the Export screen (a blanket labor export --override also covers it). An override of the block alone never covers a flag.";

export const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";

/** A queue card's human title (design 13 section 2.8.3): the enclosing section heading, else the document, else the page. */
export function cardTitle(sectionTitle: string | null | undefined, docTitle: string | null | undefined, page: number, type: string): string {
  if (sectionTitle && sectionTitle.trim()) return sectionTitle.trim();
  if (docTitle && docTitle.trim()) return docTitle.trim();
  return `Page ${page}, ${type.replace(/_/g, " ")}`;
}

const EXCERPT_MAX = 80;
const ELLIPSIS = "…";
const ws = (s: string): string => s.replace(/\s+/g, " ").trim();

/** manuallabor/state/card.py `cut`: whitespace-normalised, cut at a word boundary with an ellipsis. */
export function cutExcerpt(s: string, limit = EXCERPT_MAX): string {
  const t = ws(s);
  if (t.length <= limit) return t;
  let room = t.slice(0, limit - ELLIPSIS.length);
  if (t[room.length] !== " ") {
    const sp = room.lastIndexOf(" ");
    if (sp > 0) room = room.slice(0, sp);
  }
  return room.replace(/[ ,;:]+$/, "") + ELLIPSIS;
}

/**
 * A queue card's excerpt by the server's own rule (manuallabor/state/card.py `card_excerpt`), so a card built from a
 * block's detail (the pinned card) reads the same as when the block comes back in the list: a figure shows its
 * caption, else "Figure on page N"; a table its first row's cells joined by " · "; anything else its shown text.
 */
export function cardExcerpt(
  block: { type: string; page: number; clean_text?: string | null; raw_text: string; table?: { cells: { row: number; col: number; text: string }[] } | null },
  caption?: string | null,
): string {
  if (block.type === "figure") {
    const cap = ws(caption ?? "");
    return cap ? cutExcerpt(cap) : `Figure on page ${block.page}`;
  }
  if (block.type === "table" && block.table) {
    const row = block.table.cells
      .filter((c) => c.row === 0)
      .sort((x, y) => x.col - y.col)
      .map((c) => ws(c.text))
      .filter(Boolean)
      .join(" · ");
    if (row) return cutExcerpt(row);
  }
  return cutExcerpt(block.clean_text ?? block.raw_text);
}

/**
 * A block's score with what it is judged against (PRODUCT.md: never a bare confidence number). The number is the
 * scorer's combined confidence; the threshold is the auto-approve line from the project config.
 */
/** `threshold` is null until the project has loaded: then the bare score, never a guessed comparison. */
export function scoreText(conf: number | null | undefined, threshold: number | null): string {
  if (conf === null || conf === undefined) return "score n/a · not scored yet";
  const v = conf.toFixed(2);
  if (threshold === null) return `score ${v}`;
  const t = threshold.toFixed(2);
  const cmp = conf < threshold ? (v === t ? "just below" : "below") : "at or above";
  return `score ${v} · ${cmp} ${t}`;
}
export const SCORE_TITLE = "Combined confidence from the checks, 0 to 1. Blocks below the threshold are reviewed by a person; blocks with numbers are always reviewed.";
