# Module 0 design: contracts, IDs, providers, fixtures

Status: draft for approval · Inputs: SPEC §3, §5, §6, §8, §9 · CLAUDE.md · findings.md "Technical Decisions"
Implementers: M0.4 (contracts, ids, providers, schema export) and M0.5 (fixture generator), in parallel. Neither may change this design. Report anything you cannot satisfy instead.

## 1. Package layout

```
manuallabor/
  ids.py                    # slugs, ID formatters/parsers, regexes. Imports nothing from manuallabor.
  contracts/
    __init__.py             # re-exports every public model + EXPORTED_MODELS
    _base.py                # ContractModel, annotated scalar types (Unit, Coord, BBox, UTCDateTime, id strings)
    enums.py                # every StrEnum below
    document.py  block.py  figure.py  group.py  selection.py  flag.py
    decision.py  proposal.py  article.py  manifest.py  config.py  llm.py
    io.py                   # dump_json / write_json / read_json / canonical_json
    schema_export.py        # export_schemas(out_dir, check=False) -> list[Path]
  providers/
    __init__.py             # Provider, ProviderSet, build_provider_set, ProviderError, ProviderOutputError
    base.py  cache.py  mock.py  sinks.py
tests/
  __init__.py  conftest.py
  contracts/  ids/  providers/  fixtures_gen/        # test packages (names avoid clashing with tests/fixtures data dir)
  fixtures/__init__.py  fixtures/gen/{__init__,make_fixtures,ground_truth,content}.py
schemas/                    # exported JSON Schemas (committed)
```
`pyproject.toml`: `[tool.pytest.ini_options] pythonpath = ["."]`. New runtime deps: `jsonschema`, `pyyaml`. New dev deps: `hypothesis`, `imagehash` (already a runtime dep), `numpy` (already transitive, make it explicit).

## 2. Base conventions (`contracts/_base.py`)

```python
class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True,
                              use_enum_values=False, json_schema_serialization_defaults_required=True,
                              ser_json_inf_nan="null")
```
| Type alias | Definition |
|---|---|
| `Unit` | `Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False), AfterValidator(round6)]` |
| `Coord` | `Annotated[float, Field(allow_inf_nan=False), AfterValidator(round6)]` |
| `BBox` | `Annotated[list[Coord], Field(min_length=4, max_length=4), AfterValidator(check_bbox)]`: `[x0, y0, x1, y1]`, PDF points, **top-left origin** (PyMuPDF convention), requires `x0 <= x1 and y0 <= y1`. It is a list rather than a tuple because json-schema-to-typescript handles `minItems/maxItems` reliably. |
| `UTCDateTime` | `datetime`. Naive input is rejected; aware input is converted to UTC and truncated to milliseconds. It serializes as `YYYY-MM-DDTHH:MM:SSZ` when ms == 0 and as `YYYY-MM-DDTHH:MM:SS.mmmZ` otherwise. JSON schema `format: date-time`. |
| `DocSlug`, `TopicSlug` | `str` with pattern `ids.SLUG_PATTERN`, max_length 48 |
| `BlockId` / `FigureId` / `ArticleId` / `GroupId` | `str` with the `ids.*_PATTERN` (anchored) |
| `TargetId` | `BlockId \| FigureId`, discriminated by prefix in a validator |
| `Sha256Hex` | `^[0-9a-f]{64}$` |
| `PHash` | `^[0-9a-f]{16}$` (imagehash 8×8 phash, `str(hash)`) |

`round6(x) = round(x, 6) + 0.0` (the `+ 0.0` turns `-0.0` into `0.0`). All rounding happens at validation, so in-memory values equal on-disk values.

## 3. Enums (`contracts/enums.py`, all `StrEnum`, values exactly as listed)

| Enum | Values |
|---|---|
| `DocKind` | born_digital_pdf, scanned_pdf, docx |
| `BlockType` | heading, paragraph, list, table, figure, caption, header, footer, other |
| `BlockStatus` | auto_approved, queued, approved, edited, flagged, rejected |
| `SignalName` | ocr_mean, ocr_min, textlayer_vs_ocr, parser_agreement, reading_order_risk, table_consistency, garbage_ratio, faithfulness, figure_method, figure_resolution, figure_attach_rule, has_numeric_spec, llm_verifier |
| `Extraction` | native, vector, crop |
| `AttachRule` | caption_ref, caption_match, proximity, none |
| `GroupView` | structure, topic |
| `ArticleSplit` | per_topic, per_document |
| `FlagCategory` | wrong_text, missing_figure, wrong_grouping, bad_crop, table_structure |
| `FlagStatus` | open, resolved |
| `DecisionAction` | approve, edit, flag, skip |
| `ProposalStatus` | pending, accepted, edited, rejected |
| `Task` | cleanup, grouping, vision, verifier, embeddings, metadata, agent |
| `CallKind` | chat, vision, embed |
| `OcrEngine` | rapidocr, tesseract |
| `FaithViolationKind` | insertion, deletion, numeric_mismatch |
| `DiffOpKind` | equal, insert, delete, replace, reorder (module 3: a unit moved by an evidence-backed reading-order fix) |

## 4. Models (field order = declaration order = YAML/display order)

Defaults are `—` when the field is required. The "Validators" column lists model-level checks, and each one raises `ValueError` with a message that names the field.

### 4.1 `Document` (document.py)
| Field | Type | Default |
|---|---|---|
| slug | DocSlug | — |
| sha256 | Sha256Hex | — |
| filename | str (basename, min 1) | — |
| title | str \| None | None |
| product_model | str \| None | None |
| product_model_inferred | bool | False |
| kind | DocKind | — |
| page_count | int ≥ 1 | — |
| pages_without_text_layer | list[int] (sorted, unique, each 1..page_count) | [] |
| stripped_headers | list[str] (sorted, unique) | [] |
| stripped_footers | list[str] (sorted, unique) | [] |
| parser_versions | dict[str, str] (e.g. `{"pymupdf": "1.24.x"}`) | {} |

Validators: `product_model_inferred` implies `product_model is not None`. For `docx`, `pages_without_text_layer` must be empty.

### 4.2 Block sub-models and `Block` (block.py)
- `Signal`: `name: SignalName`, `value: Unit` (1.0 = fully trustworthy), `critical: bool`, `detail: str | None = None`.
- `OcrWord`: `text: str`, `confidence: Unit`, `bbox: BBox | None = None`.
- `TableCell`: `row: int ≥0`, `col: int ≥0`, `row_span: int ≥1 = 1`, `col_span: int ≥1 = 1`, `text: str`, `is_header: bool = False`.
- `TableShape`: `rows: int ≥0`, `cols: int ≥0`.
- `TableData`: `n_rows: int ≥1`, `n_cols: int ≥1`, `cells: list[TableCell]`, `markdown: str`, `shape_by_parser: dict[str, TableShape] = {}`. Validators: cells are sorted by (row, col) and unique on (row, col), every `row+row_span ≤ n_rows`, and every `col+col_span ≤ n_cols`.
- `DiffOp`: `op: DiffOpKind`, `raw: str`, `clean: str`.
- `FaithfulnessViolation`: `kind: FaithViolationKind`, `raw_start: int|None`, `raw_end: int|None`, `clean_start: int|None`, `clean_end: int|None`, `raw: str`, `clean: str`.
- `FaithfulnessResult`: `passed: bool`, `alignment_ratio: Unit`, `violations: list[FaithfulnessViolation]`, `diff: list[DiffOp]`, `numeric_variants: list[NumericVariant] = []` (`NumericVariant{raw, chosen, source: "textlayer"|"ocr", reason}`; a list since module 3, so a block with several text-layer/OCR conflicts can record each choice). `DiffOp` carries `raw_start/raw_end/clean_start/clean_end` (ints >= 0, end >= start) and `allowed: bool` (op is in the allowed-edit classes). `FaithViolationKind` = insertion, deletion, numeric_mismatch, reorder. Validator: `passed` is True exactly when `violations == []`.

| `Block` field | Type | Default | Notes |
|---|---|---|---|
| id | BlockId | — | |
| doc_id | DocSlug | — | |
| page | int ≥1 | — | 1-based. For DOCX this is a virtual page (§5.4). |
| bbox | BBox \| None | None | None only for DOCX |
| type | BlockType | — | |
| reading_order | int ≥0 | — | 0-based order across the whole document |
| raw_text | str | — | primary text before cleanup |
| raw_source | str | — | parser key that `raw_text` came from |
| raw_text_by_parser | dict[str, str] | {} | keys: pymupdf, docling, ocr, textlayer, docx… |
| order_by_parser | dict[str, int] | {} | each parser's reading-order index for this region |
| clean_text | str \| None | None | None until cleanup |
| confidence | Unit \| None | None | None until scored |
| signals | list[Signal] | [] | sorted by name, names unique |
| status | BlockStatus | queued | |
| heading_level | int 1..6 \| None | None | |
| section_number | str \| None | None | e.g. "5.1", pattern `^\d+(\.\d+)*$` |
| table | TableData \| None | None | |
| ocr_words | list[OcrWord] \| None | None | |
| numeric_tokens | list[str] | [] | in order of occurrence in raw_text |
| has_numeric_spec | bool | False | |
| numbers_verified | bool | False | set when a human approves a numeric block (§7.2) |
| figure_id | FigureId \| None | None | |
| faithfulness | FaithfulnessResult \| None | None | |

Block validators:
1. `ids.parse_block_id(id)` must return `(doc_id, page, _)`, so the slug and page match the fields.
2. `heading_level` is non-None only when `type == heading`.
3. `table` is non-None only when `type == table`.
4. `type == figure` if and only if `figure_id` is set, and the figure_id's slug and page equal the block's.
5. Signals are sorted by name and their names are unique. Sorting happens in a `mode="before"` validator, so it never errors on order.
6. `status == edited` requires `clean_text is not None`.

### 4.3 `FigureRecord` (figure.py): the SPEC §6.3 sidecar, exactly these fields and no others
`id: FigureId`, `file: str`, `svg: str | None`, `source_doc: DocSlug`, `product_model: str | None`, `page: int ≥1`, `bbox: BBox | None`, `extraction: Extraction`, `width: int ≥1`, `height: int ≥1`, `phash: PHash`, `caption_original: str | None`, `description_generated: str | None`, `tags: list[str]`, `articles: list[ArticleId]`, `attach_rule: AttachRule`, `confidence: Unit`, `review: BlockStatus`.
Validators:
- `file` is either the figure's own `<id>.png` or `../<other-slug>/<FIG-other-id>.(png|svg)` (the other id's slug must equal the directory). The `../<slug>/` form is used only for deduplicated figures stored once under another doc. The code (`figure.py`) allows only `png|svg`; JPEG sources are re-encoded to PNG.
- `svg` is non-None if and only if `extraction == vector`; it is either `<id>.svg` or `../<other-slug>/<FIG-other-id>.svg` and must point at the same figure as `file`.
- `id`'s slug equals `source_doc` and its page equals `page`.
- `tags` are lowercased, deduplicated and sorted. `articles` are sorted and unique.
- `bbox` is None only for DOCX images.

No field has a default, so every sidecar contains every key. The dedupe link lives only in the manifest (`ManifestFigure.duplicate_of`), never in the sidecar.

### 4.4 `Group` (group.py). `Topic` is a type alias for a `Group` whose `view == topic`.
| Field | Type | Default |
|---|---|---|
| id | GroupId: `g-<docslug>-s<nnn>` (structure, preorder, 1-based) or `g-<docslug>-t<nnn>` (topic, 1-based). `t000` is reserved for Unassigned. | — |
| view | GroupView | — |
| doc_id | DocSlug | — |
| title | str (min 1) | — |
| slug | TopicSlug | — (source of the article id) |
| block_ids | list[BlockId] (reading order, unique, all from doc_id) | — |
| page_ranges | list[PageRange{start:int≥1,end:int≥start}] (sorted, merged, non-overlapping) | — |
| section_ids | list[GroupId] (structure groups spanned; sorted) | [] |
| parent_id | GroupId \| None (structure only) | None |
| level | int ≥0 (structure depth; 0 for topics) | 0 |
| section_number | str \| None | None |
| cohesion | Unit \| None (topic only; None for structure and for unassigned) | None |
| is_unassigned | bool | False |
| block_count | int ≥0 | — |
| figure_count | int ≥0 | — |

Validators: `block_count == len(block_ids)`. The view must match the id letter (`s`/`t`). `is_unassigned` requires `view == topic`, id `t000` and slug `unassigned`. `parent_id` set requires `view == structure`.

Grouping models (module 4; field-level detail in `04-grouping.md` §1.1, all in `group.py` unless noted):
- `UnassignedEntry{block_id, view: GroupView, reason: UnassignedReason}`; `UnassignedReason` = header_footer, low_similarity, no_text, topic_failed, do_not_merge.
- `StragglerRecord{block_id, topic_id: GroupId | None, similarity: float in [-1,1] (round6), by: "centroid" | "llm"}`: one per straggler, plus one per cluster member dropped from a dissolved topic.
- `GroupOverlap{topic_id, section_id, blocks >= 1}`, `GroupOverride{seq, kind: move | rename, block_id, to_topic_slug, title, topic_slug}`, `GroupingParams` (every grouping constant, frozen into the file).
- `GroupsFile` (`docs/<slug>/groups.json`): `doc_id, algo_version, fingerprint, embedding_model, embedding_dim, grouping_model, learning_snapshot, params, structure, topics (t000 first), unassigned, stragglers, overlap, title_sources, topic_status: ok | failed, topic_error, overrides_applied, overrides_stale`. Its validator checks only internal consistency; the partition against `blocks.json` is `check_partition`.
- `selection.py`: `GroupCoverage` / `CoverageReport` (per-group and per-doc selected/total/fraction, with `subtree_*` for structure groups), `ReviewLoad{queued, numeric_queued, threshold}`, `ScopeSummary{docs, articles_per_topic, articles_per_document, articles, blocks, figures, pages, review_load}`.

### 4.5 `Selection` (selection.py)
`block_ids: list[BlockId]` (a before-validator deduplicates and sorts with `ids.block_sort_key` = (slug, page, n)), `article_split: ArticleSplit = per_topic`, `active_view: GroupView = topic`. Code uses `frozenset(sel.block_ids)`. Storing a sorted list keeps the JSON byte-stable.

### 4.6 `Flag` (flag.py)
`id: str` pattern `^flag-\d{6}$` (project sequence), `target_id: TargetId`, `category: FlagCategory`, `note: str | None = None`, `status: FlagStatus = open`, `created_at: UTCDateTime`, `resolved_at: UTCDateTime | None = None`, `resolution: str | None = None`. Computed property `target_kind -> Literal["block","figure"]`, which is not serialized. Validator: `status == resolved` if and only if `resolved_at is not None`. Figure flags target the `FIG-` id, not the figure block's id.

### 4.7 `Decision` (decision.py, SPEC §5.4 calibration record)
`seq: int ≥1`, `block_id: BlockId`, `action: DecisionAction`, `score: Unit | None` (confidence at decision time), `threshold: Unit`, `signals: list[Signal]` (snapshot), `edited_text: str | None = None`, `flag_id: str | None = None`, `timestamp: UTCDateTime`. Validators: `edited_text` non-None if and only if `action == edit`; `flag_id` non-None if and only if `action == flag`.

### 4.8 `Proposal` (proposal.py, SPEC §5.5)
- `RecheckResult`: `check: str` (e.g. `faithfulness`, `numeric_multiset`, `parser_agreement`), `passed: bool`, `detail: str | None = None`.
- `PriorAttempt`: `proposal_id: str`, `proposal_text: str`, `rationale: str`, `status: ProposalStatus`, `decided_at: UTCDateTime`.

| `Proposal` field | Type | Default |
|---|---|---|
| id | `^prop-\d{6}$` | — |
| flag_id | `^flag-\d{6}$` | — |
| target_id | TargetId | — |
| round | int ≥1 | 1 |
| proposal_text | str \| None (text proposals) | None |
| proposed_bbox | BBox \| None (bad_crop proposals) | None |
| evidence | list[str] (min 1): parser keys / signal names / "page_render" | — |
| rationale | str, one line: no `\n`, 1..300 chars | — |
| rechecks | list[RecheckResult] (sorted by check) | [] |
| status | ProposalStatus | pending |
| final_text | str \| None | None |
| history | list[PriorAttempt] (oldest first) | [] |
| model | str (`provider/model`) | — |
| input_hash | Sha256Hex | — |
| created_at | UTCDateTime | — |

Validators: exactly one of `proposal_text` / `proposed_bbox` is set. `status == edited` requires `final_text`. `len(history) == round - 1`. Computed `all_checks_passed: bool` is serialized via `@computed_field`.

### 4.9 `ArticleFrontmatter` (article.py, SPEC §6.2 exactly, in this order)
`id: ArticleId`, `title: str`, `source_doc: DocSlug`, `source_file: str`, `product_model: str | None`, `pages: list[int]` (sorted, unique, ≥1), `sections: list[str]`, `figures: list[FigureId]` (order of first appearance in the body), `blocks: int ≥0`, `review: ReviewCounts`, `generated_at: UTCDateTime`.
`ReviewCounts`: `approved: int ≥0`, `edited: int ≥0`, `overrides: int ≥0`. The validator requires `edited ≤ approved`. Here `approved` counts the article's blocks whose status is in {auto_approved, approved, edited}, and `edited` is a subset of it. ArticleFrontmatter also requires `review.approved ≤ blocks`.
`to_yaml_dict()` returns `model_dump(mode="json")` in declaration order. Module 11 renders it. The schema/dump test (C2) asserts that the field order equals the SPEC order.

### 4.10 `Manifest` (manifest.py)
| Field | Type |
|---|---|
| schema_version | Literal["1.0"] = "1.0" |
| project | ManifestProject{name: str, tool_version: str, generated_at: UTCDateTime} |
| docs | list[Document] (sorted by slug) |
| articles | list[ManifestArticle{id, path:`articles/<id>.md`, title, source_doc, block_ids: list[BlockId], figures: list[FigureId], pages: list[int], sections: list[str]}] (sorted by id) |
| figures | list[ManifestFigure{id, sidecar:`images/<slug>/<id>.json`, file: str, source_doc, duplicate_of: FigureId \| None}] (sorted by id) |
| review_stats | ReviewStats{total_blocks, auto_approved, approved, edited, flagged, rejected, queued, overrides: int ≥0; numbers_verified_blocks: list[BlockId] sorted} |
| models | dict[Task, ModelRef] (only tasks that were used) |
| threshold | Unit |
| article_split | ArticleSplit |
| overrides | list[Override{target_id: TargetId \| None, flag_id: str \| None, reason: str, at: UTCDateTime}] |
| accounting | BlockAccounting |

`BlockAccounting`: `total_blocks: int`, `assignments: dict[BlockId, str]` (the value is an ArticleId or the literal `"unassigned"`; keys are sorted on dump), `unassigned_reasons: dict[BlockId, Literal["not_selected","header_footer","rejected","empty"]]`.
Manifest validators:
- (a) `total_blocks == len(assignments)`, which must also equal `review_stats.total_blocks`.
- (b) Every value is a manifest article id or `"unassigned"`.
- (c) For each article, `set(article.block_ids) == {b for b, a in assignments.items() if a == article.id}`. Together with (b) this means each block is in exactly one article or unassigned.
- (d) `unassigned_reasons` keys are exactly the unassigned blocks.
- (e) Every `article.figures` id is in `figures`.
- (f) `duplicate_of` points to an existing figure whose own `duplicate_of` is None.
- (g) Each `Document` carries `block_ids` (all blocks produced by parsing, in parse order). The multiset union of every article's `block_ids` plus the `unassigned` block ids must equal exactly the union of all docs' `block_ids` (no missing, extra or duplicate block), `accounting.total_blocks` equals that union's size, review-status counts sum to `review_stats.total_blocks`, every article/figure `source_doc` is in `docs`, doc slugs are unique and no article id is the reserved `unassigned` marker.

### 4.11 `ProjectConfig` (config.py)
- `ModelRef`: `provider: str` (pattern `^[a-z][a-z0-9_]*$`; known: mock, ollama, anthropic, openai_compatible, vllm, llamacpp), `model: str` (min 1), `api_base: str | None = None`, `api_key_env: str | None = None`. Secrets are never stored in config.
- `TaskModels`: `cleanup`, `grouping`, `vision`, `embeddings: ModelRef`; `verifier: ModelRef | None`; `metadata: ModelRef | None = None` (falls back to grouping); `agent: ModelRef | None = None` (falls back to cleanup).
- `ProjectConfig`: `schema_version: Literal["1.0"]="1.0"`, `name: str`, `threshold: Unit = 0.85`, `models: TaskModels = <defaults>`, `article_split: ArticleSplit = per_topic`, `parsers: list[str] = ["pymupdf", "docling"]` (≥2, unique, order = primary first), `ocr_engine: OcrEngine = rapidocr`, `ocr_dpi: int ≥300 = 300`, `background_ocr_born_digital: bool = True`, `target_edit_rate: Unit = 0.02`.
- The default `TaskModels` are all `ollama`: cleanup/grouping `llama3.2:1b`, vision `moondream`, verifier `qwen2.5:1.5b`, embeddings `nomic-embed-text`. A `TaskModels` validator rejects `verifier` equal to `cleanup` (provider + model + api_base): a model grading its own output is not an independent check (the pipeline would skip it as `skip_same_model`); set `verifier` to `null` to disable it.
- `LearningConfig{enabled: bool = False}` as `ProjectConfig.learning` (default `LearningConfig()`); the grouping stage reads the learned snapshot only when `enabled`.
- `CleanupConfig{llm: "off"|"residual"|"always" = "residual", describe: bool = True}` as `ProjectConfig.cleanup` (module 5): `llm` says when the cleanup LLM pass runs (never / only for lines the deterministic passes could not settle / on every eligible block); `describe` toggles figure descriptions.
- `AttachRule` gains `human`: a figure attachment set by a reviewer (re-attach in Verify); cleanup never overwrites it. `TitleSource.human` likewise marks a reviewer-set title.
- `model_for(task: Task) -> ModelRef | None` resolves the fallbacks. `verifier=None` means the signal is skipped.

### 4.12 LLM records (llm.py)
- `Message`: `role: Literal["system","user","assistant"]`, `content: str`.
- `LLMCallLog`: `task: Task`, `kind: CallKind`, `provider: str`, `model: str`, `input_hash: Sha256Hex`, `prompt_tokens: int|None`, `completion_tokens: int|None`, `latency_ms: float ≥0` (rounded to 3 places), `cached: bool`, `ok: bool = True`, `error: str|None = None`, `truncated: bool = False` (the reply hit `max_tokens` or the prompt hit `num_ctx`), `timestamp: UTCDateTime`.
- `ChatResult`: `text: str`, `parsed: Any | None = None` (only when `json_schema` was given and validated), `log: LLMCallLog`.

## 5. IDs (`manuallabor/ids.py`)

```python
SLUG_PATTERN   = r"[a-z0-9]+(?:-[a-z0-9]+)*"
PAGE_PATTERN   = r"\d{3,4}"   # p001..p9999
INDEX_PATTERN  = r"\d{2,3}"   # 01..999
BLOCK_ID_RE    = re.compile(rf"^b-(?P<slug>{SLUG_PATTERN})-p(?P<page>{PAGE_PATTERN})-(?P<n>{INDEX_PATTERN})$")
FIGURE_ID_RE   = re.compile(rf"^FIG-(?P<slug>{SLUG_PATTERN})-p(?P<page>{PAGE_PATTERN})-(?P<n>{INDEX_PATTERN})$")
FIGURE_ID_SEARCH_RE = re.compile(r"FIG-[a-z0-9-]+-p\d{3,4}-\d{2,3}(?![0-9])")   # SPEC §6.1, unanchored
ARTICLE_ID_RE  = re.compile(rf"^(?P<slug>{SLUG_PATTERN})(?:--(?P<topic>{SLUG_PATTERN}))?$")
GROUP_ID_RE    = re.compile(rf"^g-(?P<slug>{SLUG_PATTERN})-(?P<view>[st])(?P<n>\d{{3}})$")
```
The pydantic `pattern` strings are the same expressions. Expose them as `*_PATTERN` constants so the two can never drift.

| Function | Rule |
|---|---|
| `slugify(text: str, max_len=48) -> str` | NFKD, then drop non-ASCII, then lowercase. Replace each run of `[^a-z0-9]` with `-` and strip leading/trailing `-`. If longer than `max_len`, cut at the last `-` at or before `max_len` (hard cut if there is none) and strip `-`. Empty input returns `"doc"`. |
| `doc_slug_from_filename(filename) -> str` | `slugify(Path(filename).stem)`. It uses the **filename, not the title**, because the title may be LLM-inferred and IDs must be deterministic before metadata exists. |
| `make_unique_slug(base, existing: Collection[str]) -> str` | Returns `base` if it is free, else the first free one of `base-2`, `base-3`, …. If base+suffix exceeds 48 characters, truncate base first. |
| `block_id(slug, page, n) -> str` | `f"b-{slug}-p{page:03d}-{n:02d}"`. Raises ValueError if the slug is invalid, page ∉ 1..9999, or n ∉ 1..999. |
| `figure_id(slug, page, n) -> str` | `f"FIG-{slug}-p{page:03d}-{n:02d}"`, with the same checks |
| `article_id(slug, topic_slug: str \| None) -> str` | `slug` or `f"{slug}--{topic_slug}"`. Slugs never contain `--`, so the split is unambiguous. |
| `group_id(slug, view, n) -> str` | `f"g-{slug}-{'s' if structure else 't'}{n:03d}"` |
| `parse_block_id / parse_figure_id(s) -> tuple[str,int,int]` | Inverse functions. Raise ValueError on no match. Anchored greedy matching makes slugs like `x-p001` parse correctly. |
| `parse_article_id(s) -> tuple[str, str \| None]` | Inverse function |
| `block_sort_key(id) -> tuple[str,int,int]` | Parsed tuple, used for every sort of IDs |

Index semantics:
- Block `n` is the block's 1-based position in that page's final reading order, counted over all blocks on the page, including header/footer/figure/caption blocks.
- Figure `n` is the figure's 1-based position among figure blocks on that page, in reading order.

**Determinism rule:** IDs are computed once, inside the parse stage, from (doc slug, page, per-page reading-order index), and then stored. No later stage computes an ID from list position, `enumerate()` or a dict order. Later stages only read `block.id` / `block.figure_id`. The same sha256 with the same `parser_versions` yields the same IDs.
**DOCX virtual pages:** page 1 starts at the document start. A new virtual page begins at each explicit page break, at each section break, and after every 999th block. `bbox` is None.

## 6. Providers (`manuallabor/providers/`)

### 6.1 `base.py`
```python
TEMPERATURE: Final = 0.0
RAW_OPEN, RAW_CLOSE = "<raw>", "</raw>"   # cleanup prompts MUST wrap the source text in these (module 5)
class ProviderError(Exception): provider: str; model: str; task: Task; retriable: bool
class ProviderOutputError(ProviderError): raw_text: str   # json_schema given, output invalid
LogSink = Callable[[LLMCallLog], None]
Clock = Callable[[], datetime]            # default: lambda: datetime.now(UTC)

class Provider(Protocol):
    ref: ModelRef
    def chat(self, task: Task, messages: Sequence[Message], *, json_schema: Mapping[str, Any] | None = None) -> ChatResult: ...
    def vision(self, task: Task, image_bytes: bytes, prompt: str, *, json_schema: Mapping[str, Any] | None = None) -> ChatResult: ...
    def embed(self, task: Task, texts: Sequence[str]) -> list[list[float]]: ...

class BaseProvider(ABC):   # implements Provider; subclasses implement only the raw methods
    def __init__(self, ref: ModelRef, *, sink: LogSink, cache: LLMCache | None = None, clock: Clock = utc_now): ...
    @abstractmethod def _chat_raw(self, task, messages, json_schema, temperature: float) -> RawChat   # RawChat(text, prompt_tokens, completion_tokens)
    @abstractmethod def _vision_raw(self, task, image_bytes, prompt, temperature: float, json_schema=None) -> RawChat   # `vision(json_schema=)` validates the reply exactly as `chat` does (failure never cached; the schema is part of the cache key)
    @abstractmethod def _embed_raw(self, task, texts) -> RawEmbed                                   # RawEmbed(vectors, prompt_tokens)
```
Public method flow: build the key with `cache.key(...)`. On a hit, return the cached response. On a miss, call raw with `temperature=TEMPERATURE` (there is no parameter or attribute that changes it), time it with `time.perf_counter`, and store the result unless raw raised. When `json_schema` is given, validate with `jsonschema.Draft202012Validator`: parse `text` as JSON, set `parsed`, and on failure raise `ProviderOutputError`. A failed result is never cached. **Each public call emits exactly one `LLMCallLog` to the sink**, including cache hits (`cached=True`) and failures (`ok=False`, `error=str(exc)`, then re-raise). Raw exceptions that are not ProviderError are wrapped in `ProviderError(retriable=False)`.
`ProviderSet`: a frozen dataclass `{by_task: Mapping[Task, Provider]}` whose `.get(task)` raises ProviderError when `config.model_for(task)` is None.
`build_provider_set(config, *, cache_dir: Path | None, sink: LogSink, factories: Mapping[str, Factory] = DEFAULT_FACTORIES, clock=utc_now)`. A `Factory` has the signature `(ModelRef, sink, cache, clock) -> Provider`. Module 0 registers only `"mock"`; module 6 adds the rest. An unknown provider raises ProviderError naming it.
**Injection:** every pipeline function takes `providers: ProviderSet` explicitly. There is no global or module-level singleton. `tests/conftest.py` provides these fixtures:
- `call_log` returns a list that ListSink appends to.
- `fixed_clock` returns 2026-01-01T00:00:00Z.
- `mock_providers(tmp_path)`: MockProvider for every task, cache under `tmp_path/.llm_cache`.
- `corrupting_providers(tmp_path)`: same, but `cleanup` uses CorruptingMockProvider.

### 6.2 `sinks.py`
`ListSink(list)`. `JsonlSink(path)` appends `json.dumps(log.model_dump(mode="json"), sort_keys=True, separators=(",",":"), ensure_ascii=False)+"\n"` to `<project>/logs/llm_calls.jsonl`, using one line per call and flushing per call.

### 6.3 `cache.py`
`LLMCache(root: Path)` with root `<project>/.llm_cache`, created lazily.
- `key(provider, model, task, kind, inputs: Mapping) -> str` is `sha256(canonical_json({"provider","model","task","kind","inputs"}))`.
- `inputs` per kind:
  - chat: `{"messages":[...dumped], "json_schema": schema|None}`
  - vision: `{"image_sha256": sha256(bytes), "prompt": str}`
  - embed: `{"texts":[...]}` (one entry per batch)
- `get(key) -> dict | None` reads `<root>/<key>.json`. Missing, unparsable, or `entry["key"] != key` counts as a miss and logs a warning via `logging`.
- `put(key, entry)` writes `{key, kind, provider, model, task, response, usage}` (no timestamp, so entries are byte-stable) with the serialization rules. It writes `<key>.json.tmp` and then calls `os.replace`.
- `response` is `{"text":…}` for chat and vision, or `{"vectors":[[…]]}` for embed. Vectors are rounded to 6 places before storing so hits and misses return identical values.
- `input_hash` in the log equals the cache key.

### 6.4 `mock.py`
- `MockProvider(BaseProvider)` with default `ref=ModelRef(provider="mock", model="mock-1")`. Constructor arguments: `responses: Mapping[Task, str | Callable[[Sequence[Message]], str]] = {}`, `vision_response: Callable[[bytes, str], str] | None`, `dim: int = 256`.
- `chat` resolution order:
  1. `responses[task]`
  2. `DEFAULT_MOCK_RESPONSES[task]`
  3. otherwise `ProviderError("mock: no response for task <task>")`.
- `DEFAULT_MOCK_RESPONSES` (module-level dict; later modules may **add** entries for their own tasks, and this is not a contract change):
  - `cleanup`: echo. Return the text between the last `RAW_OPEN`…`RAW_CLOSE` in the last user message, or the whole last user message if there are no tags.
  - `verifier`: `"NONE"`.
- `vision` default: `f"Generated description (mock) of image {sha256(image_bytes)[:8]}."`
- Tokens are counted as `len(text.split())` for prompt (all message contents joined) and for completion. `latency_ms` is the measured value.
- `embed`: tokens = `re.findall(r"[a-z0-9]+", nfkd_ascii(text).lower())`. For each token, `h = hashlib.sha256(tok.encode()).digest()`, `i = int.from_bytes(h[:4],"big") % dim`, and `v[i] += 1.0 if h[4] % 2 == 0 else -1.0`. Then L2-normalize and round to 6 places. A zero vector (no tokens) is replaced by `e_0 = [1.0, 0, …]`. Texts that share tokens therefore get high cosine.
- `CorruptingMockProvider(MockProvider)` takes `mode: Literal["digit","insert_word"] = "digit"`. Its `cleanup` output is `corrupt(echo, mode)`:
  - `digit`: the first ASCII digit `d` becomes `str((int(d)+1) % 10)`.
  - `insert_word`: insert `"not "` before the second whitespace-separated token, or append `" not"` if there is only one token. Empty text becomes `"not"`.
  - If `digit` mode finds no digit, it falls back to `insert_word`.
  - Invariant: the output never equals the input. `corrupt` is a public pure function.

## 7. Serialization (`contracts/io.py`)
- `dump_json(obj: BaseModel | Sequence[BaseModel] | Mapping) -> str` is `json.dumps(to_jsonable(obj), sort_keys=True, indent=2, ensure_ascii=False) + "\n"`, where models go through `model_dump(mode="json")`. `canonical_json(obj) -> bytes` is the compact form (`separators=(",",":")`) encoded as UTF-8, and it is the only input to any hash.
- `write_json(path, obj)` writes atomically (tmp file plus `os.replace`) with LF line endings. `read_json(path, Model)` uses `Model.model_validate_json`, and `read_json_list(path, Model)` works through a `TypeAdapter(list[Model])`.
- Floats: bbox/coords and Unit values are 6 places, `latency_ms` is 3 places, and embedding vectors are 6 places, all at validation time. Timestamps are ISO-8601 UTC with `Z` (§2). Sets never appear in contracts; lists are sorted where order has no meaning.
- **Schema export:** `labor schemas export [--out schemas] [--check]` calls `export_schemas`. `EXPORTED_MODELS` is an ordered tuple: Block, Document, FigureRecord, Group, Selection, Flag, Decision, Proposal, ArticleFrontmatter, Manifest, ProjectConfig, LLMCallLog.
  - Per model it writes `schemas/<Name>.json` containing `dump_json(Model.model_json_schema(mode="serialization"))`.
  - It also writes `schemas/_all.json`, containing `models_json_schema([(M,"serialization") …], title="ManualLaborContracts")` with the same dump rules. Type generation runs on `_all.json` so no `$defs` type is declared twice.
  - Stale `schemas/*.json` files that are not in the set are deleted.
  - `--check` writes nothing and exits 1 (listing the paths) if any file would change or be deleted.
  - No timestamps or absolute paths go in the output, so the files are byte-stable.

## 8. Fixture generator (`tests/fixtures/gen/`)
Entry point: `uv run python -m tests.fixtures.gen.make_fixtures --out tests/fixtures [--check]`. `--check` regenerates into a temp dir and compares the result with `CHECKSUMS.json`.
- `content.py` holds the fixed manual corpus: section titles, sentence templates, spec strings, table data and captions.
- `ground_truth.py` holds the GT pydantic models (test-only, not exported).
- Determinism:
  - `random.Random(20261028)` and `numpy.random.default_rng(20261028)` are created once per fixture, in fixture order.
  - reportlab `canvas.Canvas(path, pagesize=LETTER, invariant=1, pageCompression=1)` with fixed title/author/subject.
  - PNGs are saved by Pillow with no `pnginfo` and `optimize=False`.
  - For PyMuPDF output, call `doc.set_metadata({fixed fields, creationDate/modDate "D:20260101000000Z"})`, then `doc.save(path, garbage=4, deflate=True, no_new_id=True)`.
  - DOCX core_properties are fixed: created/modified 2026-01-01, revision 1, author "Manual Labor fixtures". After saving, `normalize_zip(path)` rewrites every entry, in original order, with `date_time=(1980,1,1,0,0,0)`, `ZIP_DEFLATED` and `external_attr=0o644<<16`.
  - Library versions are pinned by `uv.lock`. A changed checksum after a dependency bump means you regenerate, review the diff, and commit (README note).
- **Layout engine:** draw directly on the canvas, not with platypus flow, except for tables, which use `Table.wrapOn` + `drawOn` at known coordinates. Body is Helvetica 10/14pt and headings are Helvetica-Bold 16 (L1) and 12 (L2). Lines wrap with `simpleSplit`. Margins are 72pt and the page is US Letter 612×792. A block never crosses a page or column; it moves whole to the next frame. GT bbox in top-left-origin points: `x0 = frame_x`, `x1 = x0 + max(stringWidth(line))`, `y0 = H - (first_baseline + ascent)`, `y1 = H - (last_baseline + descent)`, with ascent/descent from `pdfmetrics.getAscentDescent`. All glyphs must be WinAnsi (`·`, `±`, `°`, `•` are fine).
- **Content features:** numeric specs drawn from `["35 N·m", "M8", "12 V", "P/N 4471-A", "0.25 mm ±0.05", "90°", "2.5 L", "10 A"]`. Hyphenated line breaks are forced in ≥3 places (`adjust-` / `ment`). Lists are `• item` lines, one list = one block. Captions are `Figure N. <text>` in Helvetica-Oblique 9 below the image. References are `see Figure N` inside body paragraphs.

| File | Pages | Construction |
|---|---|---|
| `clean.pdf` | 12 | Page 1 is the title page: "Acme X200 Service Manual", "Model X200 · Revision 4", no header/footer. Pages 2–12 have header "Acme X200 Service Manual" (top, 9pt) and footer "Page N" (N = physical page). Sections 1–5 have L1 headings "N. Title", with 2–3 L2 subsections "N.M Title" each. Paragraphs carry specs, plus ≥4 bullet lists. There are 3 raster PNG figures (seeded line art 900×600 at 300×200pt), each with a caption and a reference: Fig 1 and 2 on the same page, Fig 3 on the page before. |
| `twocol.pdf` | 6 | Full-width header/footer. Two frames, x = 72..297 and 315..540 (18pt gutter). Reading order is column-major. 2 raster figures inside columns, plus 1 **composite** figure (raster plus vector arrows/labels drawn over it, expected `crop`). |
| `tables.pdf` | 6 | Header/footer as in clean. 6 tables with captions "Table N. …", each with a header row: (1) torque specs, (2) electrical, (3) parts list, (4) intervals with a merged header (`SPAN` over 2 cols), (5) ragged (empty trailing cells plus one row-span cell), (6) borderless (no GRID). Numeric cells throughout. |
| `figures.pdf` | 8 | 14 figures, all expected native/vector: 8 raster (resolutions 600×400, 900×900, 1200×800, 1600×1000; displayed at various sizes) and 6 vector (canvas lines/rects/circles/bezier, no text inside). Raster figure R1 is drawn on p2 **and** p6 with identical bytes (`duplicate_of`), and a 50%-downscaled re-encode of R1 is on p7 (near-duplicate, `duplicate_of` set, `near_duplicate=true`). One figure has no caption and one has a caption but no reference. Two references are cross-page. |
| `scanned.pdf` | 12 | Each `clean.pdf` page is rendered with PyMuPDF at 300 DPI in grayscale, then converted to a Pillow `L` image. It is rotated 0.5° (`BICUBIC`, `fillcolor=255`, no expand), given gaussian noise σ=6 from the seeded numpy rng, clipped to uint8 and saved as JPEG q=80 (`optimize=False`, `subsampling=0`). Each page is inserted into a new 612×792 PDF page via `insert_image(page.rect, stream=…)`. There is no text layer. Target total size < 15 MB. |
| `manual.docx` | 2 virtual | Built with python-docx: Heading 1/2 styles, spec paragraphs, a `List Bullet` list, one 4×3 table with a header row, 2 inline PNG images each followed by a `Caption`-style paragraph "Figure N. …", and one explicit page break. |

**Ground truth** `ground_truth/<stem>.json` (dumped with §7 rules), models in `ground_truth.py`:
- `GroundTruth`: `fixture`, `file`, `sha256`, `kind: DocKind`, `page_count`, `page_size: [612.0, 792.0] | None`, `expected_slug` (= `doc_slug_from_filename`), `title`, `product_model: "Acme X200"`, `header_text: str | None`, `footer_template: str | None` (`"Page {n}"`), `derived_from: str | None` (`"clean"` for scanned), `text_is_reference: bool` (True for scanned, where exact OCR match is not expected; it is used for SPEC §11.2 recall), `blocks: list[GTBlock]`, `figures: list[GTFigure]`.
- `GTBlock`: `index` (0-based, document reading order), `page`, `type: BlockType`, `text` (logical text: hyphenation joined, wrapped lines joined with one space, list items joined by `\n`), `raw_lines: list[str]` (exactly as drawn), `bbox: BBox | None`, `heading_level`, `section_number`, `column: 0|1|None`, `is_header_footer: bool`, `numeric_tokens` (`re.findall(r"\d+(?:[.,]\d+)*", text)`), `numeric_specs` (spec strings inserted from the corpus), `has_numeric_spec` (= bool(numeric_specs)), `hyphenated: bool`, `figure_refs: list[int]` (N in "see Figure N"), `table: GTTable | None`.
- `GTTable`: `n_rows`, `n_cols`, `cells: list[TableCell]`, `bordered: bool`, `has_merged: bool`, `ragged: bool`, `caption`.
- `GTFigure`: `number: int | None`, `expected_id` (via `ids.figure_id`; n = per-page figure order top-to-bottom, left-to-right, columns column-major), `page`, `bbox`, `expected_extraction: Extraction`, `caption: str | None`, `caption_block_index: int | None`, `referenced_by: list[int]` (GTBlock indices), `duplicate_of: str | None`, `near_duplicate: bool`, `source_image: {sha256, width, height} | None` (raster only), `section_number`.
- Header/footer blocks are included as GTBlocks with `is_header_footer=true`. For scanned, blocks/figures are copied from clean, with `bbox` unchanged and documented as ±6pt approximate because of the rotation.

`tests/fixtures/project-a/`:
- `project.json` is `ProjectConfig(name="project-a")` with every TaskModels entry `ModelRef(provider="mock", model="mock-1")` (verifier included), dumped with §7.
- `sources/clean.pdf` and `sources/figures.pdf` are byte copies.

`tests/fixtures/CHECKSUMS.json` maps each relative path to its sha256 for the 6 fixtures, 6 GT files, `project-a/project.json` and the 2 source copies. It is sorted and dumped with §7. Each GT `sha256` must equal the CHECKSUMS entry for its file.

## 9. Test list
Contracts (`tests/contracts/`):
- **C1** The SPEC §6.3 example (phash set to `c3a1b2c3d4e5f607`) validates as FigureRecord, and `model_dump(mode="json") == input`.
- **C2** The SPEC §6.2 frontmatter (YAML via `yaml.safe_load`) validates, dumps back equal, and `list(ArticleFrontmatter.model_fields) == SPEC key order`.
- **C3** Each EXPORTED_MODEL rejects an unknown extra key.
- **C4** BBox rejects len 3/5, x0>x1, NaN, inf, and rounds `1.23456789` to `1.234568`. `-0.0` dumps as `0.0`.
- **C5** Unit rejects -0.01, 1.0000001 and NaN, and accepts 0 and 1.
- **C6** Block validators 1–6: each violation is rejected; signals given out of order dump sorted; duplicate signal names are rejected.
- **C7** Document: a bad sha256 is rejected; `product_model_inferred=True` with None is rejected; a bad slug is rejected; docx with `pages_without_text_layer` is rejected.
- **C8** FigureRecord: vector without svg, crop with svg, id/source_doc mismatch, bad phash and a bad `file` are all rejected; `../other-doc/FIG-…png` is accepted.
- **C9** Decision: edit without edited_text, approve with edited_text, and flag without flag_id are rejected.
- **C10** Proposal: a multi-line rationale, both text and bbox set, edited without final_text, and `history` length ≠ round-1 are rejected; `all_checks_passed` is serialized.
- **C11** Selection given duplicate, unordered ids dumps identical JSON to one given sorted input; sort uses (slug, page, n), so p010 > p009.
- **C12** Manifest accounting: a valid partition passes; block in two articles, missing block, article block absent from assignments, unknown target, and an unassigned block without a reason each fail.
- **C13** ProjectConfig defaults (0.85, per_topic, `["pymupdf","docling"]`, rapidocr, 300); one parser or duplicate parsers are rejected; `model_for(metadata)` equals grouping; `model_for(agent)` equals cleanup; verifier None returns None.
- **C14** UTCDateTime: naive input is rejected; `+02:00` input is converted; output ends in `Z`; ms precision; no `.000` when ms is 0.
- **C15** `dump_json` is byte-identical for models built from dicts in different key orders, ends in `\n`, and keeps `N·m` literal (not `·`).
- **C16** Two `export_schemas` runs into two temp dirs are byte-identical. The file set equals EXPORTED_MODELS plus `_all.json`. `--check` gives 0 on a fresh dir and 1 after appending a space to one file, and 1 when a stale extra file exists.
- **C17** Every exported schema passes `Draft202012Validator.check_schema`. The C1 and C2 instances validate against `schemas/FigureRecord.json` and `ArticleFrontmatter.json` with jsonschema.
- **C18** Enum value sets equal the SPEC lists exactly (BlockType 9, BlockStatus 6, FlagCategory 5, Extraction 3, AttachRule 4).

IDs (`tests/ids/`):
- **I1** `slugify` table: `X200_Service_Manual_rev4` → `x200-service-manual-rev4`; `Ünïcödé Manual` → `unicode-manual`; `---` → `doc`; a 60-char name gives ≤48 chars with no trailing `-`; `clean` → `clean`.
- **I2** `make_unique_slug`: free returns base; taken returns `-2`; base and `-2` taken returns `-3`; long base is truncated before the suffix.
- **I3** `block_id("acme-x200-service",42,3) == "b-acme-x200-service-p042-03"`; page 1000 gives `p1000`; n=100 gives `-100`; page 0, n 0 and slug `"Bad"` raise.
- **I4** `figure_id("acme-x200-service",42,1) == "FIG-acme-x200-service-p042-01"`.
- **I5** Hypothesis: for valid (slug, page, n), `parse_*(format(...)) == (slug, page, n)`, including slugs like `x-p001` and `a-p042-03`.
- **I6** These are rejected by the anchored regexes: `B-x-p001-01`, `FIG-Acme-p001-01`, `b-x-p42-03`, `b-x-p042-3`, `b-x-p042-03 `, `b--p001-01`, `b-x--y-p001-01`.
- **I7** `FIGURE_ID_SEARCH_RE.findall` over the SPEC §6.2 article body returns the frontmatter figures plus the inline reference, in order.
- **I8** `article_id(s, None) == s`, `article_id("acme-x200-service","belt-tension") == "acme-x200-service--belt-tension"`, `parse_article_id` inverts both, and a topic slug with `--` raises.
- **I9** `group_id` formats and `GROUP_ID_RE` parses `g-clean-s001` and `g-clean-t000`.

Providers and cache (`tests/providers/`):
- **P1** `embed` gives identical vectors from two MockProvider instances, and the sha256 of `canonical_json` of the vectors for 3 fixed texts equals a literal recorded in the test.
- **P2** cos("Tighten the M8 bolts to 35 N·m", "tighten M8 bolts to 35 N·m") > 0.7, and cos(first, "wiring diagram for the 12 V fuse box") < 0.4.
- **P3** Vectors have dim 256 and norm 1±1e-6; `""` gives `e_0`.
- **P4** Cleanup echo returns the text between the last `<raw>` tags, or the last user message when there are no tags.
- **P5** Canned responses work as both a str and a callable (the callable receives the messages).
- **P6** A task with no canned or default response raises ProviderError mentioning the task.
- **P7** With `json_schema`, a valid canned JSON fills `parsed`; invalid JSON or a schema mismatch raises ProviderOutputError, and nothing is cached.
- **P8** Exactly one LLMCallLog per call for chat, vision and embed, on hit, miss and error, with correct task/kind/provider/model/`input_hash == cache key`/cached/ok.
- **P9** A spy subclass records `temperature == 0.0` on every raw call.
- **P10** Hypothesis on `corrupt`: output ≠ input always; digit mode on text with a digit changes exactly one char, digit to digit; insert_word adds exactly one token `not`.
- **P11** The vision mock is deterministic and changes when the image bytes change.
- **P12** `build_provider_set(project-a config)` returns a MockProvider for all 7 tasks; provider `"nope"` raises ProviderError naming it; `ProviderSet.get(verifier)` with verifier None raises.
- **K1** The cache key is equal for equal inputs regardless of dict order and differs when provider, model, task, kind, any message, the schema, or the image bytes change.
- **K2** The second identical call hits: raw call count is 1, the log has `cached=True`, and results are equal.
- **K3** The file is at `<root>/<key>.json`, no `.tmp` remains, and the content is byte-stable across two puts.
- **K4** A truncated cache file counts as a miss, raw is called, and the file is rewritten valid.
- **K5** `cache=None` never touches disk.
- **K6** A raw call that raises leaves no cache file and logs `ok=False`.
- **K7** `JsonlSink` writes one compact, sorted-keys line per call.

Fixtures (`tests/fixtures_gen/`):
- **F1** All 6 fixtures, 6 GT files, project.json and 2 sources exist; their sha256 values equal `CHECKSUMS.json`; each GT `sha256` matches.
- **F2** Regenerating into `tmp_path` gives byte-identical files for every CHECKSUMS entry (the determinism gate).
- **F3** Every GT validates. GT `expected_id`s match `FIGURE_ID_RE`, use `expected_slug`, and are unique per fixture. Indices run 0..n-1. `referenced_by` blocks contain `Figure N`. `caption_block_index` points to a `caption` block.
- **F4** For clean/twocol/tables/figures, every non-figure GT block: PyMuPDF `get_text("text", clip=bbox±3pt)` token recall vs `raw_lines` ≥ 0.98.
- **F5** In `figures.pdf`, ≥12 figures and ≥95% have expected extraction native or vector. Each raster GT figure has an xref whose `get_image_rects` matches the bbox within 1pt and whose pixel size equals `source_image`. The duplicate pair has the same image sha256. The near-duplicate has `imagehash.phash` distance ≤ 4 from R1.
- **F6** `scanned.pdf`: page count equals clean's; every page's `get_text().strip() == ""`; exactly 1 image per page; effective DPI (px width / 8.5in) is 300±2; file is < 15 MB.
- **F7** `clean.pdf`: page 2–12 text contains the header and `Page N` with N = page number; GT has ≥3 `hyphenated` blocks; the union of `numeric_specs` contains `35 N·m`, `M8`, `12 V` and `P/N 4471-A`.
- **F8** `tables.pdf`: ≥5 GT tables; every table has a header row; ≥1 has a span > 1; ≥1 is `ragged`; ≥1 is borderless.
- **F9** `twocol.pdf`: GT column-0 and column-1 bboxes have disjoint x-ranges, and GT order is column-major within each page.
- **F10** `manual.docx` opens with python-docx: ≥2 inline shapes, 1 table, Heading styles, 1 page break. All GT bbox are None and pages are in {1, 2}.
- **F11** `project-a/project.json` validates as ProjectConfig with all providers `mock`, and the sources are byte-identical to the fixtures.

## 10. Open issues / contract risks (each resolved with a choice; reviewers please confirm)
1. **DOCX has no pages or bboxes**, yet SPEC §3 requires `page` and `bbox` on blocks. Choice: virtual pages (§5) and `bbox: BBox | None`.
2. **ID width overflow.** SPEC uses `p\d{3}` / `\d{2}`. Choice: format with `:03d`/`:02d` (natural widening) and accept `\d{3,4}`/`\d{2,3}`. This is a strict superset of the SPEC regex.
3. **Topics across documents** conflict with `<docslug>--<topic-slug>`. Choice: in v1, topics and groups are per document (`Group.doc_id`). Cross-doc topics are deferred.
4. **Header/footer blocks vs "every block assigned".** Choice: they are Blocks (types header/footer) and are accounted as `unassigned` with reason `header_footer`.
5. **Figure dedupe** has no field in the §6.3 sidecar. Choice: the sidecar `file` may point to `../<slug>/…`, and `duplicate_of` lives in `ManifestFigure`. The sidecar `file` is exactly `<own id>.png|svg`, or for a deduplicated figure exactly `../<other-slug>/<FIG-other-id>.png|svg` (the other id's slug equals the directory; `svg` follows the same rule and must point at the same figure as `file`). The Manifest validator cross-checks `duplicate_of` against this path: a figure with `duplicate_of` must use the dedup path to exactly that figure, and one without must use its own file.
6. **Figure `review` values** are unspecified. Choice: reuse `BlockStatus`.
7. **`review: {approved, edited}` semantics.** Choice: `edited ⊆ approved` (consistent with the SPEC example 7/1).
8. **`has_numeric_spec` is a rule, not a score.** It appears in `SignalName` for display, but module 3 must exclude it from the combiner. Block also has the boolean.
9. **Doc slug source** "filename/title". Choice: the filename stem only, so it is deterministic before metadata exists.
10. **"IDs never change"** only holds for the same bytes and the same parser versions. Choice: record `Document.parser_versions`. Re-parsing under new versions is a new parse, not a guarantee.
11. **`generated_at` breaks byte-stable exports.** Choice: inject a `Clock`. Export tests compare with a fixed clock.
12. **`labor check` on `tests/fixtures/project-a`** would write state into the repo. Choice (for module 7/11): `check` copies the project to a temp dir first.
13. **Fixture checksums depend on library versions** (reportlab, Pillow, PyMuPDF, libjpeg). They are pinned via `uv.lock`; a bump means regenerate and review.
14. **The faithfulness "reorder" allowance** (§5.2) conflicts with pure character alignment. Module 3 must define it; the contract only stores the diff and violations.
15. **Task enum** extends SPEC §8's five with `metadata` (ingest inference) and `agent` (§5.5), each with a config fallback.
16. **Mock default responses** exist only for cleanup, verifier and vision. Modules 4, 5 and 10 must register theirs (grouping, metadata, agent) so `labor check` runs fully mocked.
17. **Tag order.** `FigureRecord.tags` keep SPEC example order (lowercased, de-duplicated, not sorted) because C1 requires the SPEC §6.3 example to round-trip.
18. **ID widening.** IDs with page >= 1000 or index >= 100 widen past the SPEC's published regex by design (`\d{3}|[1-9]\d{3,}` and `\d{2}|[1-9]\d{2,}`); leading zeros beyond the fixed width are rejected.
19. **Module-level registries.** The `mock.py` canned-reply registry (`DEFAULT_MOCK_RESPONSES`) and the `base.py` provider registry (`DEFAULT_FACTORIES`) are module-level; modules 4, 5, 6 and 10 will register into them at import time.
20. **CI has not run yet** because the repository has no remote; the workflow is untested beyond its commands being run locally.
21. **Cache namespace.** The LLM cache key hashes `(provider.cache_namespace, task, kind, inputs)`. The default namespace is `provider:model`; mocks add their class name and a digest of their canned replies so two mocks with the same ModelRef never share entries.
22. **Mock reply digest and closures (re-review).** `MockProvider._replies_digest` hashes callable bytecode and constants, not closure cell values, so two lambdas built by the same factory with different captured values share a digest. Test-only; when canned replies must differ per test, use distinct cache dirs or plain (non-callable) replies.
23. **Manifest cross-checks (re-review).** `ManifestArticle` requires `parse_article_id(id)[0] == source_doc` and every `block_id` slug == `source_doc`; `ManifestFigure` requires the figure-id slug == `source_doc`.
