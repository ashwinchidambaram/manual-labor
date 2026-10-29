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

export const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
