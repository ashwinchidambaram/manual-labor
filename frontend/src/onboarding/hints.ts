// Control id -> short definition (design 12 section 2.4). Tooltips, the Help glossary and docs/USER_GUIDE.md all
// read this registry. A hint only adds a definition and the hotkey; anything needed to decide is inline text.
import type { SignalName } from "../api/schema";
import type { HotkeyId } from "../hotkeys";

export interface HintEntry {
  /** the glossary term */
  term: string;
  text: string;
  hotkey?: HotkeyId;
}

export const HINTS = {
  // shell
  navScope: { term: "Scope (step 1)", text: "Choose which topics or sections become articles.", hotkey: "goScope" },
  navVerify: { term: "Verify (step 2)", text: "Review the blocks the checks could not clear.", hotkey: "goVerify" },
  navAgent: { term: "Agent (step 3)", text: "Hand flagged blocks to a model and review its proposals.", hotkey: "goAgent" },
  navExport: { term: "Export (step 4)", text: "Build the knowledge base zip once nothing is left to review.", hotkey: "goExport" },
  help: { term: "Help", text: "Getting-started guide, keyboard shortcuts and this glossary.", hotkey: "help" },
  // scope
  viewToggle: { term: "Grouping view", text: "Two views of the same blocks. Switching never changes what is selected.", hotkey: "toggleView" },
  splitMode: { term: "Article split", text: "Whether articles follow topics or whole documents. It changes the article count, not the selected blocks.", hotkey: "splitMode" },
  selectAll: { term: "Select all", text: "Select every block of every document.", hotkey: "selectAll" },
  selectNone: { term: "Clear selection", text: "Clear the whole selection. Asks twice so it cannot happen by accident.", hotkey: "selectNone" },
  confirm: { term: "Confirm scope", text: "Saves the selection, starts scoring and opens Verify. Review can start as soon as the first document is scored.", hotkey: "confirm" },
  addDocuments: { term: "Add documents", text: "Add PDF or DOCX files. Parsing runs in the background while you keep working." },
  applyTier: { term: "Model tier", text: "Use this tier's models for every task. Stages that depend on the models are marked to re-run." },
  // verify
  viewSlider: { term: "Review filter", text: "Also lists auto-approved blocks below this confidence for a second look. Their status does not change.", hotkey: "vViewUp" },
  sort: { term: "Queue order", text: "Worst first, by page, or figures only.", hotkey: "vSort" },
  textDiff: { term: "Original vs cleaned", text: "The diff shows every change cleanup made to the raw parse. Grey changes are allowed normalisation.", hotkey: "vToggleDiff" },
  approve: { term: "Approve", text: "Accept the text as shown. On a block with numbers this records that you checked them.", hotkey: "vApprove" },
  edit: { term: "Edit", text: "Correct the text. Your edit is checked too: a change to content or numbers asks you to confirm.", hotkey: "vEdit" },
  flag: { term: "Flag", text: "Mark the block as wrong: text, figure, grouping, crop or table. Open flags lock the export.", hotkey: "vFlag" },
  skip: { term: "Skip", text: "Leave the block queued and move on.", hotkey: "vSkip" },
  back: { term: "Back", text: "Return to the previous block.", hotkey: "vBack" },
  attachFigure: { term: "Attach a figure", text: "Pick a figure from this document and attach it to the current article." },
  // export
  exportButton: { term: "Export", text: "Builds the zip from accepted text and records the build in the action log." },
  overrideReason: { term: "Override reason", text: "Why you are exporting with blocks not yet reviewed. It is written into manifest.json." },
  // non-focusable (hover only; keyboard users read them in the Help glossary)
  reasonChip: { term: "Reason chip", text: "A signal that kept this block from auto-approval. Red chips are critical: the block cannot pass while they are low." },
  statusChip: { term: "Block status", text: "Queued waits for you; auto-approved was cleared by the checks; approved, edited and flagged are your decisions." },
  cohesion: { term: "Cohesion", text: "How closely a topic's blocks belong together, from 0 to 1. Low cohesion means the topic may mix subjects." },
  coverage: { term: "Coverage", text: "How much of this group is in your selection." },
  numbersVerified: { term: "Numbers verified by you", text: "You approved this block after checking its numbers against the source page." },
  attachRule: { term: "Attach rule", text: "How a figure was matched to its article: a caption reference, proximity on the page, or by hand." },
  learningChip: { term: "Learned rules", text: "Rules learned from your earlier edits that were used on this block. Each one can be disabled." },
  methodBadge: { term: "Extraction method", text: "How a figure was extracted: a native image, a vector render, or a crop of the page image." },
} as const satisfies Record<string, HintEntry>;

export type HintId = keyof typeof HINTS;

/**
 * Plain sentence per scoring signal: what it measures, never a claim that it failed (the value says that). The
 * WhyList and reason chips show it next to the short label.
 */
export const SIGNAL_HINTS: Record<SignalName, string> = {
  ocr_mean: "Average OCR confidence over the block's words.",
  ocr_min: "OCR confidence of the least certain word in the block.",
  textlayer_vs_ocr: "How closely the PDF text layer and OCR agree on this region.",
  parser_agreement: "How closely the two parsers' readings of this block agree.",
  reading_order_risk: "How safe the reading order is; columns and wrapped text lower it.",
  table_consistency: "Whether the table's rows and columns line up consistently.",
  garbage_ratio: "How free the text is of broken characters or a wrong encoding.",
  faithfulness: "Whether cleanup kept the text, changing only spacing, hyphenation, headers or reading order.",
  figure_method: "How the figure was extracted; a crop of the page image scores lower than a native image.",
  figure_resolution: "Whether the figure image has enough resolution.",
  figure_attach_rule: "How strong the rule is that matched the figure to this article.",
  has_numeric_spec: "Blocks with numbers, units or part numbers are always reviewed by a person.",
  llm_verifier: "How closely a separate verifier model's reading agrees.",
};

export const signalHint = (name: string): string | null => (name in SIGNAL_HINTS ? SIGNAL_HINTS[name as SignalName] : null);
