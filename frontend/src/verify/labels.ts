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

export const FLAG_CATEGORIES: { id: "wrong_text" | "missing_figure" | "wrong_grouping" | "bad_crop" | "table_structure"; label: string }[] = [
  { id: "wrong_text", label: "Wrong text" },
  { id: "missing_figure", label: "Missing figure" },
  { id: "wrong_grouping", label: "Wrong grouping" },
  { id: "bad_crop", label: "Bad crop" },
  { id: "table_structure", label: "Table structure" },
];

export const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
