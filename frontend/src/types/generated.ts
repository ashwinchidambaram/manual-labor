/* eslint-disable */
/** AUTO-GENERATED from schemas/_all.json by scripts/gen-types.mjs — do not edit. Regenerate: npm run gen-types */

/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ArticleSplit".
 */
export type ArticleSplit = 'per_topic' | 'per_document';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "AttachRule".
 */
export type AttachRule = 'caption_ref' | 'caption_match' | 'proximity' | 'none';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "DiffOpKind".
 */
export type DiffOpKind = 'equal' | 'insert' | 'delete' | 'replace' | 'reorder';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "FaithViolationKind".
 */
export type FaithViolationKind = 'insertion' | 'deletion' | 'numeric_mismatch' | 'reorder';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "SignalName".
 */
export type SignalName =
  | 'ocr_mean'
  | 'ocr_min'
  | 'textlayer_vs_ocr'
  | 'parser_agreement'
  | 'reading_order_risk'
  | 'table_consistency'
  | 'garbage_ratio'
  | 'faithfulness'
  | 'figure_method'
  | 'figure_resolution'
  | 'figure_attach_rule'
  | 'has_numeric_spec'
  | 'llm_verifier';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "BlockType".
 */
export type BlockType =
  'heading' | 'paragraph' | 'list' | 'table' | 'figure' | 'caption' | 'header' | 'footer' | 'other';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "BlockStatus".
 */
export type BlockStatus = 'auto_approved' | 'queued' | 'approved' | 'edited' | 'flagged' | 'rejected';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "CallKind".
 */
export type CallKind = 'chat' | 'vision' | 'embed';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "GroupView".
 */
export type GroupView = 'structure' | 'topic';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "DecisionAction".
 */
export type DecisionAction = 'approve' | 'edit' | 'flag' | 'skip';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "DocKind".
 */
export type DocKind = 'born_digital_pdf' | 'scanned_pdf' | 'docx';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Extraction".
 */
export type Extraction = 'native' | 'vector' | 'crop';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "FlagCategory".
 */
export type FlagCategory = 'wrong_text' | 'missing_figure' | 'wrong_grouping' | 'bad_crop' | 'table_structure';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "FlagStatus".
 */
export type FlagStatus = 'open' | 'resolved';
/**
 * This interface was referenced by `undefined`'s JSON-Schema definition
 * via the `patternProperty` "^g-(?:[a-z0-9]+(?:-[a-z0-9]+)*)-(?:[st])(?:\d{3})$".
 *
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "TitleSource".
 */
export type TitleSource = 'heading' | 'llm' | 'fallback' | 'human';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "UnassignedReason".
 */
export type UnassignedReason = 'header_footer' | 'low_similarity' | 'no_text' | 'topic_failed' | 'do_not_merge';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Task".
 */
export type Task = 'cleanup' | 'grouping' | 'vision' | 'verifier' | 'embeddings' | 'metadata' | 'agent';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "OcrEngine".
 */
export type OcrEngine = 'auto' | 'rapidocr' | 'tesseract';
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ProposalStatus".
 */
export type ProposalStatus = 'pending' | 'accepted' | 'edited' | 'rejected';

export interface _All {
  [k: string]: unknown | undefined;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ArticleFrontmatter".
 */
export interface ArticleFrontmatter {
  blocks: number;
  figures: string[];
  generated_at: string;
  id: string;
  pages: number[];
  product_model: string | null;
  review: ReviewCounts;
  sections: string[];
  source_doc: string;
  source_file: string;
  title: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ReviewCounts".
 */
export interface ReviewCounts {
  approved: number;
  edited: number;
  overrides: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Block".
 */
export interface Block {
  bbox: [number, number, number, number] | null;
  clean_text: string | null;
  confidence: number | null;
  doc_id: string;
  faithfulness: FaithfulnessResult | null;
  figure_id: string | null;
  has_numeric_spec: boolean;
  heading_level: number | null;
  id: string;
  numbers_verified: boolean;
  numeric_tokens: string[];
  ocr_words: OcrWord[] | null;
  order_by_parser: {
    [k: string]: number | undefined;
  };
  page: number;
  raw_source: string;
  raw_text: string;
  raw_text_by_parser: {
    [k: string]: string | undefined;
  };
  reading_order: number;
  section_number: string | null;
  signals: Signal[];
  status: 'auto_approved' | 'queued' | 'approved' | 'edited' | 'flagged' | 'rejected';
  table: TableData | null;
  type: BlockType;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "FaithfulnessResult".
 */
export interface FaithfulnessResult {
  alignment_ratio: number;
  diff: DiffOp[];
  numeric_variants: NumericVariant[];
  passed: boolean;
  violations: FaithfulnessViolation[];
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "DiffOp".
 */
export interface DiffOp {
  allowed: boolean;
  clean: string;
  clean_end: number;
  clean_start: number;
  op: DiffOpKind;
  raw: string;
  raw_end: number;
  raw_start: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "NumericVariant".
 */
export interface NumericVariant {
  chosen: string;
  raw: string;
  reason: string;
  source: 'textlayer' | 'ocr';
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "FaithfulnessViolation".
 */
export interface FaithfulnessViolation {
  clean: string;
  clean_end: number | null;
  clean_start: number | null;
  kind: FaithViolationKind;
  raw: string;
  raw_end: number | null;
  raw_start: number | null;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "OcrWord".
 */
export interface OcrWord {
  bbox: [number, number, number, number] | null;
  confidence: number;
  text: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Signal".
 */
export interface Signal {
  critical: boolean;
  detail: string | null;
  name: SignalName;
  value: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "TableData".
 */
export interface TableData {
  cells: TableCell[];
  markdown: string;
  n_cols: number;
  n_rows: number;
  shape_by_parser: {
    [k: string]: TableShape | undefined;
  };
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "TableCell".
 */
export interface TableCell {
  col: number;
  col_span: number;
  is_header: boolean;
  row: number;
  row_span: number;
  text: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "TableShape".
 */
export interface TableShape {
  cols: number;
  rows: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "BlockAccounting".
 */
export interface BlockAccounting {
  assignments: {
    /**
     * This interface was referenced by `undefined`'s JSON-Schema definition
     * via the `patternProperty` "^b-(?:[a-z0-9]+(?:-[a-z0-9]+)*)-p(?:(?:\d{3}|[1-9]\d{3,}))-(?:(?:\d{2}|[1-9]\d{2,}))$".
     */
    [k: string]: string;
  };
  total_blocks: number;
  unassigned_reasons: {
    /**
     * This interface was referenced by `undefined`'s JSON-Schema definition
     * via the `patternProperty` "^b-(?:[a-z0-9]+(?:-[a-z0-9]+)*)-p(?:(?:\d{3}|[1-9]\d{3,}))-(?:(?:\d{2}|[1-9]\d{2,}))$".
     */
    [k: string]: 'not_selected' | 'header_footer' | 'rejected' | 'empty';
  };
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "CoverageReport".
 */
export interface CoverageReport {
  doc_id: string;
  selectable: number;
  selected: number;
  structure: GroupCoverage[];
  topics: GroupCoverage[];
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "GroupCoverage".
 */
export interface GroupCoverage {
  fraction: number | null;
  group_id: string;
  selected: number;
  subtree_fraction: number | null;
  subtree_selected: number | null;
  subtree_total: number | null;
  total: number;
  view: GroupView;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Decision".
 */
export interface Decision {
  action: DecisionAction;
  block_id: string;
  edited_text: string | null;
  flag_id: string | null;
  score: number | null;
  seq: number;
  signals: Signal[];
  threshold: number;
  timestamp: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Document".
 */
export interface Document {
  block_ids: string[];
  filename: string;
  kind: DocKind;
  page_count: number;
  pages_without_text_layer: number[];
  parser_versions: {
    [k: string]: string | undefined;
  };
  product_model: string | null;
  product_model_inferred: boolean;
  sha256: string;
  slug: string;
  stripped_footers: string[];
  stripped_headers: string[];
  title: string | null;
  title_inferred: boolean;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "FigureRecord".
 */
export interface FigureRecord {
  articles: string[];
  attach_rule: AttachRule;
  bbox: [number, number, number, number] | null;
  caption_original: string | null;
  confidence: number;
  description_generated: string | null;
  extraction: Extraction;
  file: string;
  height: number;
  id: string;
  page: number;
  phash: string;
  product_model: string | null;
  review: BlockStatus;
  source_doc: string;
  svg: string | null;
  tags: string[];
  width: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Flag".
 */
export interface Flag {
  category: FlagCategory;
  created_at: string;
  id: string;
  note: string | null;
  resolution: string | null;
  resolved_at: string | null;
  status: 'open' | 'resolved';
  target_id: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Group".
 */
export interface Group {
  block_count: number;
  block_ids: string[];
  cohesion: number | null;
  doc_id: string;
  figure_count: number;
  id: string;
  is_unassigned: boolean;
  level: number;
  page_ranges: PageRange[];
  parent_id: string | null;
  section_ids: string[];
  section_number: string | null;
  slug: string;
  title: string;
  view: GroupView;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "PageRange".
 */
export interface PageRange {
  end: number;
  start: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "GroupOverlap".
 */
export interface GroupOverlap {
  blocks: number;
  section_id: string;
  topic_id: string;
}
/**
 * Every grouping constant, frozen into groups.json so a result can be explained.
 *
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "GroupingParams".
 */
export interface GroupingParams {
  d_cut: number;
  embed_batch: number;
  embed_prefix: string;
  k_max_divisor: number;
  llm_stragglers: boolean;
  low_cohesion: number;
  max_topic_blocks: number;
  min_topic_blocks: number;
  n_candidates: number;
  name_sample: number;
  name_tokens: number;
  page_window: number;
  small_doc: number;
  straggler_batch: number;
  summary_tokens: number;
  t_assign: number;
  t_candidate: number;
  title_max: number;
  topic_slug_max: number;
}
/**
 * docs/<slug>/groups.json: both views of one document, the accounting of blocks that sit in
 * no group, and the provenance needed to explain or reproduce the result.
 *
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "GroupsFile".
 */
export interface GroupsFile {
  algo_version: string;
  doc_id: string;
  embedding_dim: number;
  embedding_model: string;
  fingerprint: string;
  grouping_model: string;
  learning_snapshot: string;
  overlap: GroupOverlap[];
  overrides_applied: number;
  overrides_stale: number[];
  params: GroupingParams;
  stragglers: StragglerRecord[];
  structure: Group[];
  title_sources: {
    [k: string]: TitleSource;
  };
  topic_error: string | null;
  topic_status: 'ok' | 'failed';
  topics: Group[];
  unassigned: UnassignedEntry[];
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "StragglerRecord".
 */
export interface StragglerRecord {
  block_id: string;
  by: 'centroid' | 'llm';
  similarity: number;
  topic_id: string | null;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "UnassignedEntry".
 */
export interface UnassignedEntry {
  block_id: string;
  reason: UnassignedReason;
  view: GroupView;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "LLMCallLog".
 */
export interface LLMCallLog {
  cached: boolean;
  completion_tokens: number | null;
  error: string | null;
  input_hash: string;
  kind: CallKind;
  latency_ms: number;
  model: string;
  ok: boolean;
  prompt_tokens: number | null;
  provider: string;
  task: Task;
  timestamp: string;
}
/**
 * Self-improvement toggle (module 7 extends it with snapshot settings).
 *
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "LearningConfig".
 */
export interface LearningConfig {
  enabled: boolean;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Manifest".
 */
export interface Manifest {
  accounting: BlockAccounting;
  article_split: ArticleSplit;
  articles: ManifestArticle[];
  docs: Document[];
  figures: ManifestFigure[];
  models: {
    [k: string]: ModelRef | undefined;
  };
  overrides: Override[];
  project: ManifestProject;
  review_stats: ReviewStats;
  schema_version: '1.0';
  threshold: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ManifestArticle".
 */
export interface ManifestArticle {
  block_ids: string[];
  figures: string[];
  id: string;
  pages: number[];
  path: string;
  sections: string[];
  source_doc: string;
  title: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ManifestFigure".
 */
export interface ManifestFigure {
  duplicate_of: string | null;
  file: string;
  id: string;
  sidecar: string;
  source_doc: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ModelRef".
 */
export interface ModelRef {
  api_base: string | null;
  api_key_env: string | null;
  model: string;
  provider: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Override".
 */
export interface Override {
  at: string;
  flag_id: string | null;
  reason: string;
  target_id: string | null;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ManifestProject".
 */
export interface ManifestProject {
  generated_at: string;
  name: string;
  tool_version: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ReviewStats".
 */
export interface ReviewStats {
  approved: number;
  auto_approved: number;
  edited: number;
  flagged: number;
  numbers_verified_blocks: string[];
  overrides: number;
  queued: number;
  rejected: number;
  total_blocks: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "PriorAttempt".
 */
export interface PriorAttempt {
  decided_at: string;
  proposal_id: string;
  proposal_text: string;
  rationale: string;
  status: ProposalStatus;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ProjectConfig".
 */
export interface ProjectConfig {
  article_split: 'per_topic' | 'per_document';
  background_ocr_born_digital: boolean;
  learning: LearningConfig;
  models: TaskModels;
  name: string;
  ocr_dpi: number;
  ocr_engine: 'auto' | 'rapidocr' | 'tesseract';
  parsers: string[];
  schema_version: '1.0';
  target_edit_rate: number;
  threshold: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "TaskModels".
 */
export interface TaskModels {
  agent: ModelRef | undefined | null;
  cleanup: ModelRef | undefined;
  embeddings: ModelRef | undefined;
  grouping: ModelRef | undefined;
  metadata: ModelRef | undefined | null;
  verifier: ModelRef | undefined | null;
  vision: ModelRef | undefined;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Proposal".
 */
export interface Proposal {
  all_checks_passed: boolean;
  created_at: string;
  /**
   * @minItems 1
   */
  evidence: [string, ...string[]];
  final_text: string | null;
  flag_id: string;
  history: PriorAttempt[];
  id: string;
  input_hash: string;
  model: string;
  proposal_text: string | null;
  proposed_bbox: [number, number, number, number] | null;
  rationale: string;
  rechecks: RecheckResult[];
  round: number;
  status: 'pending' | 'accepted' | 'edited' | 'rejected';
  target_id: string;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "RecheckResult".
 */
export interface RecheckResult {
  check: string;
  detail: string | null;
  passed: boolean;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ReviewLoad".
 */
export interface ReviewLoad {
  numeric_queued: number;
  queued: number;
  threshold: number;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "ScopeSummary".
 */
export interface ScopeSummary {
  articles: number;
  articles_per_document: number;
  articles_per_topic: number;
  blocks: number;
  docs: number;
  figures: number;
  pages: number;
  review_load: ReviewLoad;
}
/**
 * This interface was referenced by `_All`'s JSON-Schema
 * via the `definition` "Selection".
 */
export interface Selection {
  active_view: 'structure' | 'topic';
  article_split: 'per_topic' | 'per_document';
  block_ids: string[];
}
