# Module 3 design: scoring + faithfulness check

Inputs: SPEC §1, §4.6, §5 (all), §7.2, §9, §11.2 · CLAUDE.md (faithfulness invariant, deterministic core, "never trust model self-confidence") · `00-contracts.md` §4.2, §4.7, §6, §10.8/§10.14 · `01-parse.md` §2, §5, §6, §7, §9, §14 · `02-figures.md` §6, §9, §14 · code as it is now.
Gate (CLAUDE.md): unit tests for every signal and the combiner; seeded corruptions (swap a digit, merge two columns, drop a table row) all land below threshold.
Implementer: one Opus agent. Report anything you cannot satisfy instead of changing this design.

## 0. Measured on this machine (2026-10-28, real `blocks.json` of clean, scanned, tables, twocol)

| Probe | Result | Consequence |
|---|---|---|
| Block keys | born-digital: `raw_text_by_parser` = {pymupdf, docling, ocr} (ocr = background Tesseract), `order_by_parser` = {pymupdf, docling}; scanned: {ocr, ocr_alt}, raw_source `ocr`; figure blocks: raw_text `""` | §2 pair selection |
| Docling vs PyMuPDF text | identical except docling drops bullet glyphs (32 diffs on clean) and joins wrapped lines with a space | normalization N3, N4 |
| Tesseract on born-digital renders | systematic: `N·m`→`N-m` (35×), `±`→`+` (19×), `•`→`«`, word merges `with a`→`witha`, `10 A`→`10A` | directional OCR fold + space-insensitive replace in `textlayer_vs_ocr` |
| Scanned OCR vs GT (page-substring test) | 24 of 176 blocks differ; every difference is Tesseract `·`→`-` or `±`→`+`; RapidOCR reads both correctly | numeric-context penalty in `parser_agreement`; recall test |
| Prototype of §2 formulas | clean 62 auto / 85 numeric-queued / 0 low-confidence; twocol 42/52/0; tables 33/54 (2 tables with low `textlayer_vs_ocr`); scanned 87 auto / 89 queued (4 by score only), **recall 24/24** at 0.85 | constants in §2 |
| Prototype `has_numeric_spec` vs GT on clean | 85 flagged = 85 GT-positive, 0 false positives, 0 misses | §3 rule set |
| Block-level character-class entropy | prose 1.42 bits, symbol soup 1.45, spec table 2.18 | entropy does **not** separate garbage; §2.7 uses token-shape rules |
| Parser order inversions | clean 0, scanned 0; twocol p2: pymupdf places the column-2 top block early (1 displaced block); tables: docling puts every table caption after its table | LIS displacement in §2.5 |
| OCR on tables | Tesseract misses vertically centred row-span cells (`J1`) | `textlayer_vs_ocr` false alarm on tables; harmless (tables are numeric, always queued) |
| Timing | token alignment 0.18 ms per block pair; char-level `SequenceMatcher(autojunk=False)` on real blocks 0.6 ms mean (max 497 chars), 8.6k chars 0.6 s; whole prototype 35–56 ms per doc | 1,000 blocks well under 10 s; size guard §4.6 |

## 1. Package layout (`manuallabor/scoring/`)

| File | Contents |
|---|---|
| `types.py` | `ScoreModel(BaseModel, extra="forbid")` internal models: `BlockScore`, `ScoreFile`, `HistoryEntry`, `FigureInputs`, `BlockContext`, `ReorderEvidence`; every constant in §2–§6; `SCORING_ALGO_VERSION = "1"` |
| `text.py` | shared comparison normalization (N1–N6), `TOKW`, `cmp_tokens`, `numeric_context`, `weighted_agreement`, `OCR_DEGRADE`, `LOOKALIKES` |
| `ocr.py` | `ocr_signals(block, ctx) -> list[Signal]` (§2.1) |
| `agreement.py` | `parser_agreement`, `textlayer_vs_ocr` (§2.2, §2.3) |
| `layout.py` | `lis_keep`, `displaced_blocks(page_blocks) -> dict[BlockId, list[str]]`, `reading_order_risk` (§2.5) |
| `tables.py` | `table_consistency` (§2.6) |
| `garbage.py` | `garbage_ratio` (§2.7) |
| `figures.py` | `figure_method`, `figure_resolution`, `figure_attach_rule` (§2.9) |
| `numeric.py` | `NUMERIC_SPEC_RULES`, `find_numeric_specs`, `has_numeric_spec`, `FAITH_NUM_RE` (§3) |
| `faithfulness.py` | `MappedText`, `canonicalize`, `check_faithfulness`, reorder logic (§4) |
| `combine.py` | `combine`, `EXCLUDED_FROM_COMBINER` (§5) |
| `queue.py` | `assign_status`, `build_queue` (§6) |
| `verifier.py` | `llm_verifier` (§2.10) |
| `pipeline.py` | `score_block`, `score_document` (pure), `run_score(paths, only, force, providers, emit)` (I/O), fingerprint, `load_scored_blocks` (§7) |

- CLI (`cli.py`): `labor score <project> [--force] [--doc SLUG]`, exit 1 if any doc failed.
- Paths (`project.py`): `DocPaths.scores = root/"scores.json"`, `DocPaths.score_history = root/"score_history.jsonl"`.
- Reuse, do not copy: `parse.text.MODEL_RE`, `parse.text.hf_key`, `parse.text.collapse_ws`, `parse.types.PageLayout`, `figures.types.{FigureReport, FigureIndex}`, `contracts.io.write_json`, `parse.pipeline.stdout_emit`.
- No new runtime dependency.
- **Contract change (the only one):** append `reorder = "reorder"` to `DiffOpKind` (§4.5). Regenerate schemas and TS types, update `00-contracts.md` §3 and §4.2.

## 2. Signals

Every value is in [0,1] with 1 = trustworthy, rounded with `round6`. `detail` is ≤ 200 chars (truncate with `…`) and names the evidence, never just a number. "Omitted" means no `Signal` object is emitted.

**Which signals apply**

| Block | Signals |
|---|---|
| heading, paragraph, list, caption, other, header, footer | parser_agreement, textlayer_vs_ocr (text-layer pages), ocr_mean/ocr_min (OCR-sourced), reading_order_risk, garbage_ratio, faithfulness, has_numeric_spec, llm_verifier (after cleanup) |
| table | the above + table_consistency |
| figure | figure_method, figure_resolution, figure_attach_rule (when attached) |

`ctx.ocr_sourced = block.raw_source in {"ocr","ocr_alt"}`. `ctx.text_layer = block.raw_source in {"pymupdf","docling"}`.

### 2.0 Comparison normalization (`text.py`, used by §2.2, §2.3 only, never by faithfulness)

| Step | Rule |
|---|---|
| N1 | `unicodedata.normalize("NFKC", s)`; delete U+00AD |
| N2 | dehyphenate: `re.sub(r"([^\W\d_])-[ \t]*\n[ \t]*([^\W\d_])", r"\1\2", s)` |
| N3 | drop line-leading symbol bullets: `re.sub(r"^[ \t]*[^\w\s][ \t]+", "", s, flags=re.M)` (covers `•`, `*`, `¢`, `«`, `-`, `+`) |
| N4 | `TOKW = re.compile(r"\w+(?:[.,]\d+)*|[^\w\s|]")`: word runs (with decimal tails), single symbols; `|` (table separators) is dropped |
| N5 | casefold tokens with no digit; tokens containing a digit keep case |
| N6 | `w(t) = DIGIT_WEIGHT (3) if any digit in t else 1`; `numeric_context(ts)[i]` = some token within `NUMERIC_WINDOW` (2) positions of i contains a digit |

`weighted_agreement(a, b, *, directional: bool) -> Agreement(value, k_numeric, notes)`:
1. `ops = SequenceMatcher(None, a, b, autojunk=False).get_opcodes()`.
2. `equal` → matched weight `w(A)`.
3. `replace` where `"".join(A).casefold() == "".join(B).casefold()` → matched (spacing only: `10A`/`10 A`, `witha`/`with a`).
4. `replace` with `directional=True`, `len(A)==len(B)`, and every pair `(x, y)` has equal length with each char `y == x` or `y in OCR_DEGRADE[x]` → matched. `OCR_DEGRADE = {"·": "-.+•", "±": "+", "•": "*«¢eo+-.", "×": "xX", "°": "o\"'", "–": "-", "—": "-", "’": "'", "“": "\"", "”": "\""}`. **Text layer → OCR direction only.** A text layer `+0.05` with OCR `±0.05` is a mismatch.
5. Any other non-equal op is a mismatch. If it touches a numeric-context token on either side, `k_numeric += 1`. If its tokens pair up 1:1 with equal length and differ only at positions where `{x_c, y_c} ∈ LOOKALIKES`, and either token has a digit, the note is `confusable 'x' vs 'y'`. `LOOKALIKES` = {O,o,D,Q}↔0, {l,I,i,|}↔1, {S,s}↔5, B↔8, {Z,z}↔2, {G,b}↔6, {g,q}↔9, T↔7, A↔4.
6. `ratio = 2·matched / (W(a)+W(b))` (1.0 if both empty). `value = min(ratio, NUMERIC_PENALTY ** k_numeric)` with `NUMERIC_PENALTY = 0.5`.
7. `notes`: up to 3 mismatches as `'A' vs 'B'`, in op order.

### 2.1 `ocr_mean`, `ocr_min` (`ocr.py`)
- Applies only when `ctx.ocr_sourced` and `block.ocr_words`. Born-digital `ocr_words` are background words and feed only §2.3.
- Words: drop words whose text is one non-alphanumeric char (bullets: the measured `¢` at 0.045 and `*` at 0.73) and empty words. No words left → both omitted.
- `ocr_mean = mean(conf)` via `math.fsum`, `ocr_min = min(conf)`. These are OCR-engine per-word statistics (SPEC §5.1), not an LLM rating itself.
- Critical: `ocr_mean` never; `ocr_min` iff `has_numeric_spec`.
- Detail: `min 0.787 at 'M8'; 41 words` / `mean over 41 words`.

### 2.2 `parser_agreement` (`agreement.py`)
- Pair = first of `[("pymupdf","docling"), ("ocr","ocr_alt"), ("docx","docling")]` with both keys in `raw_text_by_parser`. Text = §2.0 tokens of each side. `value = weighted_agreement(a, b, directional=False).value`.
- Both texts empty → omitted.
- **Single source** (no pair; the block was read by one text parser only, ignoring background `ocr` on text-layer pages): if the missing parser ran for this doc (`Document.parser_versions[k]` exists and ≠ `"unavailable"`), value `SINGLE_SOURCE_VALUE = 0.6`, detail `only pymupdf read this region`. If the other reader is unavailable for the doc, the signal is omitted and the progress line carries `parser_agreement unavailable: ocr_alt`.
- **Critical iff `has_numeric_spec` or value < `AGREEMENT_CRITICAL_BELOW` (0.8).** This extends SPEC's "< 0.8 on a numeric block" to all blocks: below 0.8 a fifth of the text is contested, and the geometric mean would otherwise dilute it (the merge-two-columns case).
- Detail: `pymupdf vs docling 0.97; numeric: '+0.05' vs '±0.05'`.

### 2.3 `textlayer_vs_ocr`
- Applies when `ctx.text_layer` and `"ocr" in raw_text_by_parser`. `a` = `raw_text_by_parser[raw_source]`, `b` = `raw_text_by_parser["ocr"]`, `directional=True`.
- `a` empty → omitted. `a` non-empty and `b` empty → `OCR_EMPTY_VALUE = 0.5`, detail `OCR found no words in region` (invisible or white text is a real risk).
- Critical iff `has_numeric_spec` or value < 0.8. This catches corrupt text layers (`3S` vs `35`, shifted-font mojibake that both PDF parsers share).
- Detail: `text layer vs OCR 0.5; confusable '3S' vs '35'`.

### 2.4 `faithfulness`
Always emitted, always critical. With `clean_text is None`: `check_faithfulness(raw, raw)` runs as a self-test (it must pass; failure raises `ScoringError`, a canonicalizer bug), value 1.0, detail `raw (no cleanup yet)`, and `BlockScore.faithfulness = None`. With `clean_text`: §4; value 1.0 if passed without reorder, `FAITH_REORDER_VALUE = 0.9` if passed via reorder, **0.0 if failed** (the floor). Detail: `2 violations: deletion '35'→'36'; numeric_mismatch '35'`.

### 2.5 `reading_order_risk` (`layout.py`)
Per page, take the body blocks (all types except header/footer) sorted by `reading_order`.
- For each parser key k present in ≥ 2 of them: `seq` = `order_by_parser[k]` of those blocks, in final order. `lis_keep(seq)` = longest **non-decreasing** subsequence by patience sorting (`bisect_right` on pile tails, predecessor links, reconstructed back from the last pile's top). Blocks not kept are **displaced in k**. Measured effect: the docling caption-after-table swap marks the caption displaced, and the twocol p2 column-2 top block is displaced in pymupdf.
- Value = `(1 − 0.4·[displaced in any parser]) · (1 − 0.3·[in any PageLayout.overlaps pair]) · (1 − 0.1·[page n_columns ≥ 2])`.
- Emitted on text and table blocks; figure blocks take part in `seq` but get no signal. No layout for the page (DOCX without bbox) → only the displacement term applies. Soft.
- Detail: `displaced in docling order; page has 2 columns`.

### 2.6 `table_consistency` (`tables.py`, table blocks)
| Component | Rule |
|---|---|
| shape | `shape_by_parser` with < 2 parsers → 0.7. Any `TableShape(0,0)` → 0.5. Else `min over parsers k of (min(r_k,R)/max(r_k,R))·(min(c_k,C)/max(c_k,C))` vs `(R,C) = (n_rows, n_cols)` |
| ragged | build the grid (span origins cover their spans). A non-header row is ragged if fewer than `n_cols` grid slots are covered by non-empty cells. `1 − 0.5·ragged/max(1, body_rows)` |
| header | any `is_header` cell → 1.0, else 0.8 |

Value = shape · ragged · header. Soft. Detail: `shapes pymupdf 7×4, docling 6×4; 2 ragged rows; header ok`.

### 2.7 `garbage_ratio` (`garbage.py`)
Tokens = whitespace split of `raw_text` after N3 and `|` removal. `core` = token stripped of leading `([{"'“‘«` and trailing `.,;:!?)]}"'”’»`. A token is **bad** if:

| # | Rule |
|---|---|
| G1 | contains U+FFFD, `(cid:`, or a char of category Co, Cn, Cs, Cc, or Cf (except U+00AD, U+200B–U+200D) |
| G2 | the core is not one repeated char (TOC leaders `.....` are fine) **and** (≥ 2 chars of category P*/S* outside `ALLOWED_INNER = "-/.,·'’°%±+×:_#&()\""`, **or** len ≥ 3 with no digit and ≥ 60% P*/S* chars) |
| G3 | letters from ≥ 2 scripts (first word of `unicodedata.name`; {CJK, HIRAGANA, KATAKANA} count as one; Greek `µμΩωπ` are ignored) |

Fragmentation (non-table blocks): `F` = share of tokens whose core is one alphabetic char. `value = clamp(1 − bad/n − 2·max(0, F − 0.2))`. No tokens → omitted. Soft everywhere (§12.6). Detail: `3/40 tokens symbol soup ('#$%@'); fragmentation 0.45`.
Measured: fixture blocks F ≤ 0.2 (scanned primary); RapidOCR garbage readings have F of 0.39–0.67.

### 2.8 `has_numeric_spec`: see §3. Emitted only when True: `value = 1.0 if block.numbers_verified else 0.0`, `critical=False`, detail `numeric spec: 35 N·m; M8 (always reviewed)`. **Excluded from the combiner** (00 §10.8).

### 2.9 Figure signals (`figures.py`, figure blocks)
Inputs (`FigureInputs`): the `FigureExtraction` or `FigureFailure` from `figures_report.json`, the `DedupeEntry` from `figures/index.json`, and the sidecar's `attach_rule` and `articles`.

| Signal | Value | Critical |
|---|---|---|
| figure_method | base native 1.0 / vector 0.95 / crop 0.70. Cap at 0.5 if `kind == "near"` duplicate (02 §6: a wrong file is a silent error), and at 0.5 if `min(bbox w,h) < 36 pt` or `bbox_area_frac < 0.002`. `FigureFailure` → 0.0. Detail: `crop (scanned_page); near-duplicate of FIG-… (d=4)` | **always** (confidence = method × the soft mean, as the brief asks) |
| figure_resolution | `clamp(effective_dpi / 150)`; dpi None → omitted | no |
| figure_attach_rule | caption_ref 1.0, caption_match 0.9, proximity 0.6, none 0.4. **Omitted until attachment has run** (`attach_rule == none and articles == []`, i.e. all of module 3). Module 5 fills it in. | no |

Missing report entry for a figure block → `ScoringError` (doc fails; run `labor figures`).

### 2.10 `llm_verifier` (`verifier.py`, optional)
- **Skip (omit)** unless all hold: `clean_text` set and `≠ raw_text` (since §2.10a: a canonical token changed); faithfulness passed; `config.model_for(Task.verifier)` is not None; the verifier ModelRef ≠ the cleanup ModelRef (same provider+model+api_base would mean a model reading its own output). Skips are counted in the progress `detail`.
- Call: `providers.get(Task.verifier).chat(Task.verifier, [system VERIFIER_SYSTEM, user f"{RAW_OPEN}{raw}{RAW_CLOSE}\n<clean>{clean}</clean>\nDoes the cleaned text change any fact, number, or step? Answer with the differing span or NONE"])`. No `json_schema`, because 1B local models break JSON. Temperature 0 and the cache by input hash come from `BaseProvider`.
- **Strict validation:** `out` = stripped text with one pair of surrounding quotes or backticks removed.
  - `re.fullmatch(r"(?i)none\.?", out)` → **omitted** (outcome `ok`, no signal). Revised after the module 3 review: a 1.0 soft signal on NONE raised the soft geometric mean and lifted a 0.8486 block to 0.8842 (auto-approved). A "no difference" answer is not evidence; the verifier can only lower a score.
  - Else if `len(out) ≤ 300`, there is no blank line, the span is not weak (≥ `VERIFIER_MIN_SPAN` = 3 chars, contains a letter or digit, not only function words such as `the`, `of the`), and `collapse_ws(out)` is a substring of `collapse_ws(clean)` or `collapse_ws(raw)` → `VERIFIER_FLAG_VALUE = 0.2`, detail `verifier: '<span>'` (since §2.10a the span must also mark a raw/clean change, and the detail carries that change). Exception (second module 3 review): a 1–2 char all-digit span that is a whole number token of raw or clean (`35`, `5`) also flags; `3` inside `35`, `no`, `the` and punctuation stay ignored.
  - Anything else → omitted, counted `verifier_invalid`. `ProviderError` → omitted, counted `verifier_errors`.
- Soft. Never asked to rate anything; it is a second reader.

#### 2.10a Revision 2026-10-30: ask only about a change, count only a quote on a change

**Failure mode (build/human-test, qwen2.5:1.5b as verifier).** 124 blocks reached the verifier. 118 differed from raw only in whitespace and the other 6 only in GFM table pipes and a separator row: the gate `clean != raw` was exact string equality, so the model was asked to find a difference that did not exist, and a 1.5B model answers that by copying the passage back. The old validation flagged any non-weak span found in `collapse_ws(raw)` or `collapse_ws(clean)` without checking that it marks a place where they differ, so 36 of 37 flags quoted text identical in both versions (33 whitespace-only cleanups, 3 table rows). The unit test `test_span_must_be_in_raw_or_clean` asserted exactly that (RAW and CLEAN differed by a newline and `cover bolts` flagged). Separately, 71 of the 124 calls were dropped by a false Ollama truncation guard (design 06, revision 2026-10-30).

**Rule.**
1. *Gate.* `token_pair(raw, clean, block_type, hf_strings, page, hf_pages)` (`verifier.py`) canonicalises both sides with the faithfulness check's own `canonicalize` and the same arguments the pipeline gives the check (`faith_kwargs`: AE5 glyphs, AE3 headers/footers, AE4 bullets, AE2 hyphenation, AE1 whitespace), then `loose` (a hyphen between two letters, kept or dropped, is the same word). Tokens are `\w+` runs and single punctuation glyphs; table pipes, the canonical bullet and GFM separator rows (`GFM_SEP_RE`, AE6) are structure and are not tokens. Splitting punctuation off words matches AE1, which lets a space appear or vanish next to a non-word character. The differences are the non-`equal` opcodes of `difflib.SequenceMatcher(autojunk=False)` over the token texts. When there are none the call is skipped as `skip_unchanged` (counted with the other skips). The pair is computed only after the faithfulness, no-verifier and same-model skips, so scoring without a verifier costs nothing extra.
2. *Evidence.* The existing checks stay unchanged (verbatim in collapsed raw or clean, ≤ 300 chars, no blank line, not weak, or a whole short numeric token). In addition the span's canonical tokens must occur, as a whole-token run, on the raw side overlapping a raw-side change or on the clean side overlapping a clean-side change. A change that is empty on one side (tokens only the other side has) sits between two tokens and is marked by a quote that includes either neighbour. A span found only in text both versions share is `verifier_invalid`: no evidence, no flag.
3. *Evidence on screen.* The flag's detail is `verifier quoted "<span>"; raw "<raw fragment>" -> clean "<clean fragment>"`, each part a JSON string literal (the first change, in raw order, that the span marks; fragments are the original text of the changed tokens, whitespace collapsed). Parts longer than 48 chars are shortened with `…` inside the literal, and shortened further until the detail fits `DETAIL_MAX`, so a literal is never cut. The Verify panel (`WhyList.tsx`, `verifierEvidence`) reads the three literals back and shows Raw, Clean and the quoted span next to the verdict; an older detail shows no evidence block and stays on the technical line.

**Effect on build/human-test** (recorded replies replayed): all 124 pairs are `skip_unchanged`; none of the 37 false flags survives.

**What it must not do.** It does not loosen any faithfulness test or change what the check allows; it reuses its canonicalisation. It does not turn the verifier into an agreement or similarity score: NONE still adds no signal, and a flag is still the fixed soft `VERIFIER_FLAG_VALUE = 0.2`, not lowered or graded. The model still never rates anything; the decision that a quote is evidence is deterministic code over raw and clean. `SCORING_ALGO_VERSION` is bumped to `"6"` by this change (decided 2026-10-30 by the owner's delegate: the verifier's semantics changed, so a score written by version 5 is not the same measurement). Consequences, each deliberate:
- Every existing project must rescore. Until it does, a `scores.json` with another `algo_version` reads exactly like a missing one everywhere: `scoring.pipeline.scores_current(paths, slug)` (memoised on the file's mtime and size) is the one test, used by `ProjectData.readiness` and `ReviewService._ready_docs` (the document is `pending`, waiting for the first stale node), `export.load.doc_ready` (the gate and the status skip it), `ScopeService` (no rows for the figure count and the review estimate; the document still counts in `docs`, `pages` and the article counts, which follow the selection like `blocks`, design 08 section 10 revision; the Scope estimate needs only a current first-pass score, `ProjectData.has_scores`, not clean.json), `ReviewService.block_statuses` / `page_blocks` (empty) and `_find` (404). No read path raises `ScoringError` into a 500; the Scope chip and `labor status` show "Needs a run" because `score2`'s fingerprint carries the algo version.
- `group`'s fingerprint includes `SCORING_ALGO_VERSION` (design 04 step 2), so the next `labor run` also re-groups, and the topic-name rule of design 04 §3.4.1 then renames topics once (`connector-data-2` becomes `connector-data-section-5`). Article ids and file names follow the slugs. Group overrides that name an old slug are reported in `overrides_stale`; attach overrides and agent proposals naming an old article id no longer match a topic. README "Upgrading" tells the owner.
Test: `tests/api/test_old_scores.py` (a project whose score files say `"5"`: every GET route answers without a 500, Verify lists the documents as pending, export status is locked with no blockers from them).

Tests (`tests/scoring/test_verifier.py`): `test_skip_reasons` (whitespace-only pair is `skip_unchanged`), `test_score_block_never_calls_the_verifier_on_a_whitespace_only_cleanup` (spy: no call), `test_span_must_be_in_raw_or_clean_and_mark_a_change` (the inverted test), `test_replay_p002_07_whole_passage_copied_back_does_not_flag` (recorded reply), `test_valid_span_flags` and `test_span_on_either_side_of_the_change_flags` (positive control `35 N·m` → `53 N·m` flags at 0.2 with the fragments), `test_span_outside_the_change_is_no_evidence`, `test_table_with_only_pipes_added_does_not_flag`, `test_table_cell_change_still_flags`, `test_header_removed_by_cleanup_is_not_a_change`, `test_evidence_fragments_are_bounded_and_parseable`, `test_found_span_lowers_score` and `test_span_in_the_unmoved_part_of_a_reorder_does_not_lower_score` (an evidence-backed reorder: the only faithfulness-passing cleanup with changed tokens besides numeric variants). `tests/scoring/test_review_round2.py` short numeric spans now mark a change; `tests/scoring/test_pipeline_cli.py::test_run_score_with_mock_verifier` sends only the reordered blocks.

## 3. `has_numeric_spec` rule (`numeric.py`)

`NUM = r"[±∓+\-−]?\d+(?:[.,]\d+)*"`
`UNIT = r"(?:N\s?[·.\-]?\s?m|Nm|kN|N|lbf?[·.\-\s]?ft|ft[·.\-\s]?lbf?s?|in[·.\-\s]?lbf?s?|kgf?[·.\-]?[cm]?m|mm|cm|km|[µμu]m|m|in|ft|kg|g|mg|lbs?|oz|kPa|MPa|Pa|mbar|bar|psi|V(?:DC|AC|dc|ac)?|mV|kV|mA|A|kVA|VA|kW|W|[ΩΩ]|k[ΩΩ]|M[ΩΩ]|ohms?|kHz|MHz|Hz|rpm|RPM|°\s?[CF]|°|K|mL|ml|L|cc|gal|qt|ms|sec|s|min|hrs?|hours?|h|minutes?|seconds?|%|dBA?)"`

| Name | Pattern (Python `re`, applied to NFKC text) |
|---|---|
| quantity | `rf"(?<![\w.]){NUM}(?:\s?(?:-|–|to|\.\.)\s?{NUM})?\s?{UNIT}(?![A-Za-z])"` (35 N·m, 12 V, 0.25 mm, 90°, 2.5 L, 10 A, 10 to 60 N·m, 12VDC) |
| tolerance | `r"±\s?\d|\+\s?/\s?-\s?\d|\d\s?(?:±|\+/-)"` |
| part_number | `r"(?i:\b(?:P/?N|part\s*(?:no\.?|number|#)|ref\.?|cat\.?\s*no\.?|sku|order\s*no\.?))\s*[:#]?\s*[A-Z0-9][A-Z0-9./-]{2,}"` |
| code | `parse.text.MODEL_RE` (M8, J1, X200, 4471-A, M10x1); a match equal to a whitespace token of `Document.product_model` is ignored |
| dimension | `r"\d+(?:[.,]\d+)?\s?[x×]\s?\d+(?:[.,]\d+)?"` |
| spec_word | `r"(?i)\b(?:torque|voltage|current|pressure|tolerance|clearance|capacity|rating|gap|preload)\b[^.\n]{0,40}?\d"` |

- **Revised after the module 3 review** (`numeric.py` is the source of truth): the unit lexicon covers abbreviations and plurals (volts/V/VDC/VAC, amps, watts, ohms, Hz, inches/inch/in./`"`, feet/ft/`'`, pounds/lb/lbs, ft.lb./ft-lb/lb-ft/N·m, P.S.I./psi/kPa/bar, tons, gallons/gals., quarts/qts, liters, °F/°C/degrees, rpm, blows per min./bpm, hours/hrs, cu. in./cc, %), part-number keywords add FSN, NSN, Model, Serial (value must contain a digit; keyword must not run into a letter, so `REFERENCES` is not `REF`). False positives removed: `in` is a unit only before `.`/punctuation/end and after a decimal or a dimension word; glued `s`/`h` never (`1970s`, `5s`); glued single-letter units need ≥ 2 digits (`1V`); codes like `50S`/`0G`, appendix refs `A-1`, and codes after Section/Chapter/Appendix are ignored.
- **Revised after the second module 3 review:** glued `V`/`W` fire on any number (`5V`, `3W`) except right after Section/Chapter (`Section 1V.`); `A L m g K` still need ≥ 2 digits glued (`Step 3A`). `in.` with its dot is always a unit (`2 in. from the edge`). A `thread` rule fires on diameter-pitch specs (`1/4-20 UNC`, `3/8-16`, `#10-32`, `0.250-28 UNF`). Nothing inside a document-number footer `[A-Z]{2,} -\d…` (`ME -3895-332-12/2-4`) fires. `spec_word` reports the whole spec: keyword through the number and, when an accepted quantity starts at that number, its unit (`Torque to 100 ft.lb.`, never `Torque to 1`).
- `find_numeric_specs(text, product_model) -> list[str]`: matches in text order, de-duplicated, stripped.
- `has_numeric_spec(block, doc)`:
  - header/footer/figure → False.
  - table → True iff any non-header cell text has a digit (one numeric cell makes it a spec table; open issue 4).
  - else True iff `find_numeric_specs` is non-empty on `raw_text` **or any** `raw_text_by_parser` value. The union means a corrupted reader (`3S N·m`) cannot hide a spec another reader saw.
  - Detail lists specs from `raw_text` first, then the others, at most 5.
- **It is a rule, not a score:** it forces `status = queued` and never enters `combine`.
- `FAITH_NUM_RE = r"(?<!\w)[±∓+\u2212-]?\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*"` (sign-aware, so `±0.05`→`+0.05` changes the multiset). §4 uses it on canonical text, not `Block.numeric_tokens` (that list includes header/footer lines and has no signs).

## 4. Faithfulness check (`faithfulness.py`, pure, deterministic)

```python
def check_faithfulness(raw: str, clean: str, *, block_type: BlockType, table: TableData | None,
                       hf_strings: Sequence[str], variant: NumericVariant | None,
                       variant_sources: Mapping[str, str], evidence: ReorderEvidence) -> FaithfulnessResult
```
- `hf_strings` = `Document.stripped_headers + stripped_footers`.
- `variant_sources` = `raw_text_by_parser`.
- `ReorderEvidence(layout_risk: bool, alt_texts: tuple[str, ...])`: `layout_risk` = displaced in any parser, in an overlap, or the page has n_columns ≥ 2 (§2.5 terms). `alt_texts` = `raw_text_by_parser` values for keys ≠ `raw_source`, sorted by key.

### 4.1 Allowed edits: exactly SPEC §5.2 plus lossless glyph identity

| # | Edit | Where |
|---|---|---|
| AE1 | Whitespace: change any whitespace run to any other non-empty run (newline↔space, collapse, strip at the text ends). Delete or insert whitespace **only** where at least one neighbour is not `\w`. | both |
| AE2 | Dehyphenation: in raw, a `-` that is the last non-space char of a line, preceded by a letter, with the next line starting with a letter, may be dropped or kept (`adjust-\nment` → `adjustment` or `adjust-ment`) | raw line breaks |
| AE3 | Header/footer removal (revised after the second module 3 review). Recorded strings are grouped by `hf_key` digit template; each group has a **page slot** `{n}` (pages known, `hf_pages` = recorded string → pages, built from the header/footer blocks: the digit run that equals the recording page on every recorded occurrence; pages unknown: the single digit run that varies across the recorded strings, none if 0 or ≥ 2 vary) and **fixed runs** (same value in every member). Delete a whole raw line only if (a) it is a string recorded on THIS page, or (b) it has the group's template, every run outside the page slot equals the fixed value, and the page slot equals `block.page` (`Page 35 of 60` on page 35 with template `Page {n} of 60`; never `Page 35 of 35`, never `… · 13 V` from a recorded `… · 12 V`), or (c) the group has no page slot and the line is its recorded string (case aside), a doc-wide constant (recorded on ≥ 2 pages when pages are known). Another page's footer (`Page 34` on page 35) and any other numeric line are body text (a header `TM 5-3895-332-12` never deletes the body line `TM 9-2320-280-20`). **Position (algo 4):** only the run of such lines at the block's start or end (`hf_edge_lines`) is deletable; a line with body text on both sides is body text, and a block is never emptied. On the clean side a deleted string is removed only as a surplus occurrence over what raw kept. Clean may keep it. | raw lines |
| AE4 | Bullet normalization: at line start, `[•·◦▪‣●*–-]` + whitespace ↔ `[-*•]` + whitespace. The OCR misreads `¢ + o «` count as bullets only when `block_type == list`. A sign glyph `+ - –` before a number (`+ 5 V`) is never a bullet (algo 4). | line starts |
| AE5 | Glyph identity: NFC on both sides; ligatures `ﬀ ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ` → letters; delete U+00AD; U+00A0, U+2000–U+200A, U+202F count as whitespace | both |
| AE6 | Table reconstruction (table blocks): §4.3 | tables |
| AE7 | Reordering for reading-order fixes, **only with evidence**: §4.5 | units |

Whitespace is stricter than SPEC's literal "remove whitespace". Merging `a cross`→`across` or splitting `notable`→`not able` changes tokens, and cleanup is lossless normalization, not OCR correction (CLAUDE.md). Open issue 9.

### 4.2 Canonicalization: `MappedText(text: str, src: tuple[int, ...], optional: frozenset[int])`
- `src[i]` is the index in the original string of canonical char i.
- `optional` holds the canonical indices of AE2 hyphens.
- Every transform maps `MappedText → MappedText`, so spans always map back to the original offsets.

`canonicalize(s, side)`, in order:
1. AE5.
2. AE3. Raw: collect the hf lines and delete them. Clean: delete lines whose text equals a deleted raw hf line, at most as many times as raw had it (multiset).
3. AE4: rewrite each matched line-start bullet to `• `.
4. AE2: delete the newline and surrounding whitespace after an AE2 hyphen, keep the hyphen, and mark it `optional`. Apply to both sides.
5. AE1: collapse every whitespace run to one `" "` and strip both ends.

The same function runs on both sides, so whatever allowed subset cleanup applied, both sides converge.

### 4.3 Tables (AE6)
`raw_c` comes from `block.table`: the grid in row order, cells joined `" | "` (covered span cells as `""`), rows joined `"\n"`, AE5 and AE1 inside each cell. `src` points at the matching cell text in `raw_text` when found by left-to-right search, else the row start. `clean_text` is parsed in one of two formats:
- (i) GFM: every non-blank line starts with `|`, and line 2 is a separator matching `^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$`. Drop the separator and split rows on unescaped `|` (unescape `\|`). Each row must have `n_cols` cells. It is compared grid-to-grid against `raw_c`, so **cell positions matter** (a value moved into a neighbouring empty cell is a violation). **Coverage (algo 4):** the cells must also cover `raw_text`, which may come from the other parser: the non-empty cell tokens (`TOKEN_RE`, AE5) must equal `raw_text`'s token multiset (a missing raw token is a `deletion`, an extra cell token an `insertion`), and the non-empty row count must equal the raw row count when raw is in the `` | `` row convention (else one `deletion`/`insertion` over the whole text). `table_consistency(table, raw_text)` turns the same mismatch into a critical 0.3.
- (ii) Otherwise, compared as text against `raw_text` (the `" | "` / `"\n"` convention) with §4.2.

### 4.4 Level (a): alignment, violations, numeric multiset
1. **Variant** (revised after the second module 3 review): a variant applies only if (i) `chosen` is an **OCR-confusable** reading of `raw`: the same length and differing only inside the pairs `0O`, `1lI|`, `5S`, `8B`, `2Z`, `6G`, `9g`, `.,`, or one digit dropped/added on top of those (`3S→35`, `4B→48`, `l0→10`, `35→355`; never `35→40`, `36→35`, `3.5→35`); and (ii) it is **confirmed at the same position**: counting only digit-bearing tokens (`parse.text.TOKEN_RE` tokens with a digit; a raw token without a digit such as `SO` counts as one), the other reading (`variant_sources["ocr"]` for source `ocr`, `variant_sources[raw_source]` for `textlayer`) has exactly as many numeric tokens as raw and its token at the raw occurrence's numeric index equals `chosen` (surrounding punctuation stripped). No ±1 slack: in `Sizes 30 35 40 mm` with OCR `Sizes 30 85 40 mm`, `35→40` is not confirmed by the neighbouring 40. Every confirmed whole-token occurrence of `raw` in `raw_c` is replaced by `chosen` (src kept). An unconfirmed variant is ignored and is not listed in `numeric_variants`.
2. If `raw_c.text == clean_c.text`, there are no violations.
3. **Size guard:** if `len(raw_c)+len(clean_c) > FAITH_MAX_CHARS` (50,000) or `SequenceMatcher(...).quick_ratio() < 0.5`, emit one `deletion` violation over the whole text (a rewrite). Otherwise `ops = SequenceMatcher(None, raw_c.text, clean_c.text, autojunk=False).get_opcodes()`.
4. Classify each non-equal op:
   - `delete` whose raw chars are all in `optional` → allowed (AE2 drop).
   - `replace` of a single optional `-` by `-` cannot occur (they are equal).
   - `delete`/`insert` of `" "` with a non-`\w` neighbour on the side that has it → allowed (AE1).
   - Otherwise `delete` → `deletion`; `insert` → `insertion`; `replace` → `deletion` with both spans set (a substitution removes raw content).
5. **Numeric multiset:** `Counter(FAITH_NUM_RE on raw_c) − Counter(on clean_c)` gives one `numeric_mismatch` per surplus raw occurrence (raw span of the occurrence that is still unmatched after left-to-right pairing). The reverse direction gives clean-side ones. This is order-independent, so it holds under reorder.
6. Spans: `raw_start = src[i]`, `raw_end = src[j-1]+1` (insertion points map to the next char's src, or `len(original)`). `v.raw == raw[raw_start:raw_end]` must hold (tested).
7. `alignment_ratio = round6(SequenceMatcher(None, raw_c.text, clean_c.text, autojunk=False).ratio())` (1.0 when both are empty).
8. `diff` (for the "Diff vs raw" view): `SequenceMatcher` on the **original** `raw` vs `clean`, one `DiffOp` per opcode with the original spans. `allowed = op == equal or no violation span on that op's side(s) overlaps it`.

### 4.5 Level (b): reorder allowance (resolves 00 §10.14)
Runs only if level (a) failed with only `insertion`/`deletion` violations (any `numeric_mismatch` means content changed, so no reorder can explain it).
1. **Line units:** raw lines after steps 1–3 of §4.2. An AE2 pair is merged into one unit first. Each unit is canonicalized (steps 4–5). **Sentence units:** split `raw_c` at `(?<=[.!?][)"”’]?)\s(?=[A-Z0-9•(])`.
2. For line units, then sentence units (each skipped if > `REORDER_MAX_UNITS` = 200): find a permutation with `cover(units, clean_c.text)`.
   - It is a DFS over the target position. At each position it tries the distinct remaining unit strings in first-raw-occurrence order; a unit fits if it matches at that position followed by `" "` or the end.
   - Matching uses the loose form: both sides with every `-` between two letters deleted.
   - The step budget is `REORDER_MAX_STEPS` (10,000); exceeding it means no permutation (fail closed).
3. With a permutation π, build `raw_π` = the unit MappedTexts in π order joined by `" "` (src preserved), and rerun **level (a)** on `raw_π` vs `clean`. It must pass with all the normal allowances. This proves the only extra edit is order.
4. **Evidence gate (revised after the module 3 review):** a permutation (line units or sentence units alike) is accepted **only if attested**: another independent reader of the same block (the other parser's text or the OCR text, i.e. `evidence.alt_texts`) read the clean order. Attested = some alt text, canonicalized and in loose form, contains every unit in π order at strictly increasing positions, each as a **whole unit** (preceded by the start or a space and followed by a space or the end; revised after the second module 3 review: `5 Nm is the limit.` is not attested by `15 Nm is the limit.`, `Check it` not by `Check items`). Layout risk (a multi-column page, a displaced block, an overlap) is never sufficient on its own: the review showed a procedure with step 3 moved first passing at 0.9 on an `n_columns=2` page, and step order is a fact. `evidence.layout_risk` is still recorded but no longer accepts anything; an accepted reorder keeps the faithfulness value 0.9.
5. **Accepted:** `passed=True`, no violations. The `diff` ops that overlap moved units (units not in the LIS of π) get `op = reorder, allowed = True` (the contract addition). `alignment_ratio` stays the level-(a) value. The signal value is 0.9.
6. **Not accepted** (permutation found, no evidence): `passed=False`, one `reorder` violation per moved unit, with the unit's raw span and its clean span.
7. No permutation: the level-(a) result stands.

Known limit: in a raw block whose columns are interleaved, an AE2 join pairs lines from different columns, so the check fails closed (human review). Open issue 17.

### 4.6 Result
`FaithfulnessResult(passed = violations == [], alignment_ratio, violations sorted by (raw_start or -1, clean_start or -1, kind), diff, numeric_variant)`. A failure gives signal value 0.0 (critical), so confidence = 0.0 and the diff is attached for the Verify screen. Cost: one or two char-level `SequenceMatcher` runs per cleaned block (0.6 ms mean measured).

## 5. Combiner (`combine.py`, pure)
```python
EXCLUDED_FROM_COMBINER: Final = frozenset({SignalName.has_numeric_spec})
def combine(signals: Iterable[Signal]) -> float | None:
    used = [s for s in signals if s.name not in EXCLUDED_FROM_COMBINER]
    if not used: return None
    crit = sorted(s.value for s in used if s.critical); soft = sorted(s.value for s in used if not s.critical)
    c = (crit[0] if crit else 1.0) * (0.0 if 0.0 in soft else math.exp(math.fsum(map(math.log, soft)) / len(soft)) if soft else 1.0)
    return round6(min(1.0, max(0.0, c)))
```
- **Criticality is decided by the signal producer** (the `critical` flag), and the combiner only reads it. The critical set:
  - faithfulness: always;
  - figure_method: always (figures);
  - parser_agreement and textlayer_vs_ocr: when `has_numeric_spec` or value < 0.8;
  - ocr_min: when `has_numeric_spec`.

  Everything else is soft.
- **Missing signals are omitted.** Treating them as 1.0 would inflate the geometric mean by dilution; treating them as 0.0 would floor every block that lacks a reader (born-digital has no `ocr_*`). Absence of evidence is neither.
- Monotone in each value for fixed flags; ≤ min(critical); independent of signal order (values are sorted and `fsum` is exact); `None` only when no signal applies.
- Known property: the soft mean dilutes with signal count (one soft s among n gives s^(1/n)). SPEC fixes the formula; the value-dependent critical flags in §2.2/§2.3 keep strong disagreement from being diluted.

## 6. Queue and status (`queue.py`)
```python
def assign_status(confidence: float | None, has_numeric_spec: bool, threshold: float) -> BlockStatus:
    return auto_approved if confidence is not None and confidence >= threshold and not has_numeric_spec else queued
def build_queue(scored: Iterable[ScoredBlock]) -> list[BlockId]
```
- Threshold = `ProjectConfig.threshold` (default 0.85). A failed faithfulness check gives confidence 0.0, so such a block is always queued.
- `build_queue` takes `status == queued`, excludes header/footer types, and sorts by `(-1.0 if confidence is None else confidence, ids.block_sort_key(id))`: worst first, ties by block id.
- Figure blocks are in the same queue (one id space). The figure's sidecar gets `confidence` = the figure block's confidence and `review` = its status, **only if** the existing `review ∈ {queued, auto_approved}`. Human decisions are never overwritten.
- Module 3 status is machine status only (`auto_approved`/`queued`). Human statuses are module 7's overlay. A threshold change re-runs `assign_status` from stored confidences, with no re-scoring.

## 7. Pipeline, persistence, CLI (`pipeline.py`)

**Why `blocks.json` is not modified:** module 2's figures fingerprint hashes `blocks.json` (02 §10). If scoring wrote it, every `labor figures` run would re-extract. `blocks.json` stays parse-owned and immutable. Scores live in an overlay:
- `docs/<slug>/scores.json` = `ScoreFile{doc_id, algo_version, fingerprint, threshold, blocks: list[BlockScore]}`, sorted by `block_sort_key`.
- `BlockScore{block_id, signals: list[Signal] (sorted by name), confidence: Unit|None, status: Literal["auto_approved","queued"], has_numeric_spec: bool, numeric_specs: list[str], faithfulness: FaithfulnessResult|None}`.
- `load_scored_blocks(paths, slug) -> list[Block]` merges the overlay via `Block.model_validate({**block.model_dump(), **score_fields})`, so it runs the contract validators. Modules 4–11 and the API read blocks **only** through it.

**Per doc** (`run_score`, docs in slug order):
1. Load `document.json`, `blocks.json`, `parse/layout.json` (`list[PageLayout]`, keyed by page), `figures_report.json` (required iff the doc has figure blocks), `figures/index.json`, sidecars, `project.json`, and the prior `scores.json`. Recorded `NumericVariant`s come from the prior `BlockScore.faithfulness.numeric_variant` until module 7 owns them.
2. `fingerprint = sha256(canonical_json({algo, document_sha, blocks_sha, layout_sha, figures_report_sha|None, figures_index_entries_for_doc, sidecar_inputs: {fid: [attach_rule, articles]}, threshold, verifier_ref, cleanup_ref, variants}))`. Sidecar `confidence`/`review` are outputs, so they are never part of it.
3. **Skip** if the fingerprint equals the prior one. Even then, re-apply sidecar `confidence`/`review` from `scores.json` if they differ, because a `labor figures` run resets them (02 §9). Emit `status: skip` (or `sidecars` if any were rewritten).
4. Otherwise `score_document(doc, blocks, layouts, fig_inputs, variants, threshold, verifier) -> list[BlockScore]`, pure except for verifier calls. Then write `scores.json` (`write_json`, atomic), then sidecars (only if the bytes differ), then append history.
5. **History** `score_history.jsonl`: one compact sorted-keys line `HistoryEntry{seq, block_id, fingerprint[:16], confidence, status, signals}` per block whose `(confidence, status, signals)` differs from its last line. No timestamp, so it is deterministic for the same run sequence.
6. Progress line: `{"doc","stage":"score","status","blocks","auto_approved","queued","numeric","figures","faith_failed","elapsed_ms","detail"}`, where `detail` carries the verifier/unavailable counters. An error emits `status:error`, the next doc continues, and the exit code is 1.

**Stage order:** `parse → figures → score`. Module 7's stage graph marks score stale on a parse or figures re-run (by the fingerprint, which is automatic). Module 5 re-runs `score` after cleanup.

**Calibration hook (SPEC §5.4):**
- Module 3 guarantees that every block (figures too) has a `BlockScore` with a complete, sorted `signals` snapshot and a `confidence` (None only if no signal applied).
- Module 7 builds `Decision(score=block.confidence, threshold=config.threshold, signals=block.signals, …)` from `load_scored_blocks` at decision time.
- `score_history.jsonl` keeps the pre-cleanup vs post-cleanup trajectory for the module 10 edit-rate buckets.
- Module 3 computes nothing for calibration.

## 7a. Module 5 interplay (algo version 4)
- `SCORING_ALGO_VERSION = "4"` (3: module 5; 4: AE3 edge-only header/footer removal, AE4 signs, AE6 coverage, `table_consistency` raw coverage, stale `clean.json` detection by `raw_sha256`). A `clean.json` overlay (module 5) is read per document and its content hash is part of the fingerprint, so a changed cleanup re-scores; scoring then evaluates each block's `clean_text` against `raw_text`.
- When cleanup rejected a candidate and kept its deterministic result (`fallback`), the faithfulness signal is capped at `FAITH_FALLBACK_VALUE = 0.5` (`scoring/types.py`) instead of 1.0, with the rejection reason in `detail`.
- `faith_kwargs(block, ctx, variants)` (`scoring/pipeline.py`) is the single builder of the full-context arguments to `check_faithfulness_ex`; scoring and cleanup both call it, so their verdicts on the same (raw, clean) pair are identical by construction.

## 8. Determinism and performance
| Source | Handling |
|---|---|
| difflib | `autojunk=False` everywhere. `SequenceMatcher` is deterministic for the same inputs. |
| Iteration | blocks by `reading_order` / `block_sort_key`; parsers by sorted key; the pair order is fixed (§2.2); unit DFS in first-raw-occurrence order; no set iteration (frozensets are only used for membership) |
| Floats | `math.fsum`; `round6` at the signal and at combine; thresholds compared after rounding |
| LIS ties | patience sorting with `bisect_right`, reconstructed from the last pile (§2.5) |
| LLM | verifier only; temperature 0; cached by input hash; absent in every determinism test |
| Output | `write_json` (sorted keys, LF); no timestamps or absolute paths in `scores.json`/history; elapsed time only on stdout |

Budget: 1,000 blocks with `clean_text` set and no verifier < 10 s (prototype estimate ≈ 1–2 s). 200 pages (~3,000 blocks) of born-digital score in < 10 s, well inside SPEC §9's 5 minutes. There is no dictionary dependency to pin (§12.1).

## 9. Seeded corruption harness (gate, `tests/scoring/corrupt.py`, test-only)
`Corruption = Callable[[Block, list[Block]], Block]`. Each applies `block.model_copy(update=…)` to the parsed fixture block and re-scores it with its real page context. Targets are deterministic: the first block in `reading_order` matching the predicate.

| # | Fixture | Target | Mutation | Must be caught by | Assert |
|---|---|---|---|---|---|
| H1 | clean | 1st paragraph containing `35 N·m` | `clean_text = raw.replace("35","36",1)` | faithfulness (deletion + numeric_mismatch) | value 0.0, conf 0.0, queued |
| H2 | clean | same | docling text `35`→`36` | parser_agreement ≤ 0.5, critical | conf < 0.85 |
| H3 | clean | same | pymupdf text and raw_text `35`→`3S` (OCR still `35`) | textlayer_vs_ocr (detail `confusable '3S' vs '35'`) + parser_agreement | conf ≤ 0.5 |
| H4a | twocol | p2: column-0 and column-1 paragraphs with ≥ 2 lines (via `block_columns`) | pymupdf text and raw_text of A := lines interleaved A1,B1,A2,B2… | parser_agreement < 0.8 → critical | conf < 0.8 |
| H4b | twocol | same | `clean_text(A)` = interleaved | faithfulness (insertion) | conf 0.0 |
| H5a | tables | table 1 | `clean_text` = its GFM markdown minus body row 3 | faithfulness (deletion + numeric) | conf 0.0 |
| H5b | tables | table 1 | `shape_by_parser["docling"].rows -= 1` and docling text minus that row | table_consistency 6/7 + parser_agreement (numeric) | conf < 0.85 |
| H5c | tables | table 1 | GFM `clean_text` with one value moved into an adjacent empty cell | faithfulness (cell position) | conf 0.0 |
| H6 | clean | 1st non-numeric paragraph | `clean_text` with `not ` inserted before token 2 | faithfulness (insertion) | conf 0.0. The same insert into docling text only lowers parser_agreement below 1.0 with the span in detail: a documented limit, not asserted < 0.85 |
| H7 | clean | 1st paragraph on p3 | raw_text += `"\nAcme X200 Service Manual"` and `"\nPage 7"`; clean_text = the original raw | **must pass**: faithfulness 1.0, no violations | `passed` |
| H8a | clean | 1st paragraph with ≥ 2 sentences, non-numeric | clean_text = s2 + " " + s1, no evidence | faithfulness `reorder` violation | conf 0.0 |
| H8b | clean | same | same, docling text also s2 s1 (attested) | passes, DiffOp `reorder` allowed | faithfulness 0.9 |
| H9 | scanned | 1st block whose ocr text contains `35` | ocr text and raw_text `35`→`3S`, ocr_alt unchanged | parser_agreement numeric | conf ≤ 0.5 |
| H10 | clean, tables, twocol, scanned | every non-empty non-header/footer block | `clean_text` = `CorruptingMockProvider(mode)` cleanup of `f"{RAW_OPEN}{raw}{RAW_CLOSE}"`, modes digit / insert / delete / cycle | faithfulness | 100% fail, conf 0.0; control: `MockProvider` echo passes 100% |

## 10. Test list (`tests/scoring/`)
Fixtures: reuse the session `parsed` and `figproj` fixtures from `tests/conftest.py`. `scoredproj` (session) = copy of `figproj` + `run_score`. Unit tests build `Block`s by hand.

| # | File | Assertion |
|---|---|---|
| 1 | test_text | N1–N6: `ﬁ`→fi, `adjust-\nment`, bullets stripped, `TOKW("0.25 mm ±0.05") == ["0.25","mm","±","0.05"]`, `M8`, `N·m` → 3 tokens; weighted_agreement steps 3–5 (spacing replace, directional fold one way only, LOOKALIKES note) |
| 2 | test_ocr_signals | all words 0.97 → 0.97/0.97; one word 0.4 → min 0.4; all 0 → 0; bullet word excluded; text-layer block → omitted; critical iff numeric |
| 3 | test_textlayer_vs_ocr | identical 1.0; measured Tesseract degradations (`N-m`, `+0.05`, `witha`, `10A`, `«`) 1.0; reverse direction 0.5; `3S`/`35` 0.5 with confusable note; OCR empty 0.5; shifted-font mojibake vs readable OCR < 0.2 and critical; critical iff numeric or < 0.8 |
| 4 | test_parser_agreement | identical 1.0; docling without bullets and joined lines 1.0; 1 numeric diff 0.5, 2 diffs 0.25; one non-numeric word in 30 ≈ 0.97 soft; interleaved columns < 0.8 critical; single source 0.6; other reader unavailable → omitted; both empty → omitted |
| 5 | test_reading_order | `lis_keep` cases incl. ties; single column 1.0; 2-col page 0.9; displaced 0.6; overlap 0.7; header/footer excluded; fixture: twocol p2 `-09` displaced in pymupdf, the 5 tables captions displaced in docling, clean and scanned none |
| 6 | test_table_consistency | agreeing 7×4 + header 1.0; 7×4 vs 6×4 → 6/7; (0,0) 0.5; single parser 0.7; ragged rows; no header 0.8; fixture ragged table < 1.0 |
| 7 | test_garbage | prose 1.0; spec text `P/N 4471-A, 35 N·m, 0.25 mm ±0.05` 1.0; `#$%@ ^&*(` ≤ 0.2; `(cid:12)` and U+FFFD bad; `ovpmn o o s s e ln` ≤ 0.2; Cyrillic `Т` in `Тorque` bad; leaders `......` fine; German and French prose 1.0; no clean/twocol/tables block < 0.9 |
| 8 | test_figure_signals | native/vector/crop bases; near-dup cap 0.5; small-region cap; failure 0.0 critical; 72 dpi → 0.48; None dpi omitted; attach placeholder omitted, value table when set; `scoredproj`: scanned figures queued (crop), figures.pdf natives auto, p7 near-dup queued |
| 9 | test_numeric | each rule: positive/negative table (above); `1.1 General Precautions`, `see Figure 3`, `Page 3`, product-model `X200` → False; table rule; union over readers (`3S N·m` primary, OCR `35 N·m` → True); header/footer/figure False; GT recall on clean/twocol/tables == 1.0, precision printed |
| 10 | test_combine | worked examples; hypothesis: in [0,1], monotone per value with flags fixed, ≤ min(critical), permutation-invariant (identical float), `has_numeric_spec` ignored, empty → None, soft 0 → 0, round6 |
| 11 | test_faith_allowed | each of AE1–AE6 passes alone and combined; dehyphenation drop and keep; hf exact and `hf_key` (`Page 7`) removal and keep; `¢` bullet in a list; ligatures; NBSP; NFD input; GFM table vs raw; raw→raw |
| 12 | test_faith_violations | inserted word (insertion, clean span); deleted word (deletion); digit swap (deletion + numeric_mismatch); `a cross`→`across` (deletion); `notable`→`not able` (insertion); `Page 4` in clean not in raw; `¢` replaced in a paragraph; `±`→`+`; dropped table row; moved table cell; for every violation `raw[raw_start:raw_end] == v.raw` and the same for clean; `diff` ops overlapping violations have `allowed=False` |
| 13 | test_faith_numeric | duplicated number fails; reordered numbers under accepted reorder pass; attested NumericVariant exempts (`3S`→`35`, source ocr); unattested variant ignored → fails and `numeric_variant is None` |
| 14 | test_faith_reorder | de-interleaved lines attested by the other parser pass with `reorder` DiffOps; layout_risk alone fails; same without evidence → `reorder` violations with spans; attested sentence swap passes; unattested fails; reorder + inserted word fails; step cap and > 200 units fail closed |
| 15 | test_faith_props (hypothesis) | raw→raw passes for arbitrary text (incl. U+00AD, NBSP, `|`, bullets, hyphens at line ends); random compositions of AE1–AE5 pass; one inserted non-space char outside allowed contexts fails; `canonicalize` idempotent; all spans in bounds |
| 16 | test_corrupting_mock | H10 on 4 fixtures × 4 modes |
| 17 | test_verifier | skip reasons (no verifier, same model as cleanup, failed faithfulness, no canonical token changed, §2.10a); a span counts only on a raw/clean change (§2.10a); NONE → no signal (score unchanged); weak spans (`e`, `.`, `the`) ignored; valid span → 0.2 soft; invalid outputs (absent span, > 300 chars, blank line) omitted + counted; ProviderError omitted; second call `cached=True`; spy temperature 0 |
| 18 | test_corruption_harness (**gate**) | H1–H9 with their asserts and the named catching signal |
| 19 | test_queue | numeric at confidence 1.0 still queued; confidence == threshold → auto; None → queued and sorted first; worst-first with `block_sort_key` ties (p010 after p009); shuffled input → same order; header/footer excluded; sidecar `review` not overwritten when `approved` |
| 20 | test_pipeline_cli | `labor score` via CliRunner: JSON progress lines; every block has a BlockScore; `load_scored_blocks` validates as Block; `blocks.json` byte-unchanged; 2nd run `skip` with unchanged bytes; `--force` identical bytes; subprocess `PYTHONHASHSEED=123` on a fresh copy → byte-identical `scores.json`, history, sidecars; `labor figures --force` then score → `sidecars` status restores confidence; `parse --force` → re-scored; missing `figures_report.json` → `status:error`, exit 1, other docs scored; history appends only on change |
| 21 | test_recall_scanned (SPEC §11.2) | blocks = scanned non-figure, non-header/footer, non-empty. `G_p` = page GT `raw_lines` joined `"\n"` per block, NFC, N3 bullets stripped, whitespace collapsed, blocks joined `" "`. differs(b) = normalized raw_text not a substring of `G_p`. Asserts differs ≥ 10 (non-vacuous), **recall = caught(conf < threshold)/differs ≥ 0.95**, and queue recall (status queued) == 1.0; prints recall, counts and review load (measured 24/24, load 49/176) |
| 22 | test_performance | 1,000 blocks (clean blocks replicated with ids re-minted on synthetic pages, clean_text = dehyphenated + line-joined raw) scored with no verifier < 10 s |
| 23 | test_real_scanned (live-only) | skips unless `tests/fixtures/real/real-manual.pdf` and `ground_truth_sample.json` exist and `MANUALLABOR_LIVE=1`; the #21 metric per GT block: region = non-figure blocks with bbox coverage ≥ 0.5 (figures never catch text; an uncovered GT block is a miss); differs = GT comparison tokens (OCR glyph folds) not a contiguous run of the region's tokens; caught = every region block carrying a differing token has confidence < threshold; asserts ≥ 10 differing and recall ≥ 0.95, prints recall |
| 24 | test_fixture_baseline | on `scoredproj`: no raw→raw faithfulness failure anywhere; every non-numeric body block on clean/twocol auto-approved; every numeric block queued; tables' table blocks queued |

Gate commands (into PROGRESS.md): `MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest -q tests/scoring` (18, 16 and 21 are the gate numbers); `uv run pytest -q`; `uv run ruff check manuallabor tests && uv run mypy manuallabor`; `uv run labor schemas export --check`; `cd frontend && npm run gen-types && npm run typecheck && npm test -- --run`.

## 11. Constants (`types.py`, single source)
`DIGIT_WEIGHT=3, NUMERIC_WINDOW=2, NUMERIC_PENALTY=0.5, AGREEMENT_CRITICAL_BELOW=0.8, SINGLE_SOURCE_VALUE=0.6, OCR_EMPTY_VALUE=0.5, RO_DISPLACED=0.4, RO_OVERLAP=0.3, RO_MULTICOL=0.1, TABLE_SINGLE_PARSER=0.7, TABLE_NO_STRUCTURE=0.5, TABLE_NO_HEADER=0.8, TABLE_RAGGED_WEIGHT=0.5, GARBAGE_FRAG_FREE=0.2, GARBAGE_FRAG_SLOPE=2.0, FIG_BASE={native:1.0, vector:0.95, crop:0.70}, FIG_CAP=0.5, FIG_SMALL_PT=36, FIG_SMALL_FRAC=0.002, FIG_DPI_FULL=150, ATTACH={caption_ref:1.0, caption_match:0.9, proximity:0.6, none:0.4}, VERIFIER_FLAG_VALUE=0.2, VERIFIER_MAX_SPAN=300, FAITH_REORDER_VALUE=0.9, REORDER_MAX_UNITS=200, REORDER_MAX_STEPS=10_000, FAITH_MAX_CHARS=50_000, FAITH_REWRITE_QUICK_RATIO=0.5`. Module 10 calibration may propose new values, never silently.

## 12. Open issues (each resolved with a choice)
1. **Dictionary source for `garbage_ratio`:** none. Token-shape rules G1–G3 plus fragmentation, with no wordlist.
   - Why: an English dictionary misfires on non-English manuals, and on part codes, units and model numbers, so it would penalise the spec blocks already queued for a better reason.
   - Block-level class entropy measured as non-separating (§0).
   - `wordfreq` is not installed and adds ~30 MB on a disk-constrained machine.
   - A `Lexicon` hook (per-language pinned wordlist) can be added later behind a `parse_algo`-style version bump.
2. **Reorder allowance (00 §10.14):** a two-level check.
   - Level (b) proves a unit permutation and then re-checks with level (a).
   - It is accepted only with evidence: another reader having that order, for line or sentence units (layout risk alone is not evidence; see §4.5 step 4).
   - An unevidenced transposition is a `reorder` violation, because step order is a fact.
   - Contract addition: `DiffOpKind.reorder`.
3. **Critical set:** faithfulness and figure_method always; parser_agreement and textlayer_vs_ocr when numeric **or** < 0.8; ocr_min when numeric. All others soft. `has_numeric_spec` is excluded.
4. **Tables and `has_numeric_spec`:** one non-header cell with a digit is enough. Not "every cell numeric": one wrong torque value in a parts table is the failure we care about.
5. **Single-parser blocks:** `parser_agreement = 0.6` (critical if numeric) when the other parser ran but missed the region. Omitted when that reader is unavailable for the whole doc (no evidence either way), with a progress warning.
6. **`garbage_ratio` critical on scanned:** no. ocr_min and two-engine agreement measure the same failure more directly, and the shape rules have false positives on code-dense text that would floor spec tables.
7. **Overlay instead of mutating `blocks.json`** (forced by module 2's fingerprint). Everyone reads through `load_scored_blocks`.
8. **Sidecar confidence is reset by every `labor figures` run** (02 §9 `build_record`). The score stage restores it on skip; module 7 orders figures → score.
9. **Whitespace strictness** beyond SPEC's literal wording: token merges and splits are violations (§4.1).
10. **AE5 glyph identity** (NFC, ligatures, soft hyphen, NBSP) is added to SPEC's list. It is lossless and never changes a token.
11. **Threshold slider semantics:** SPEC §5.3 says "drag the threshold to 0 to see everything", but with `confidence ≥ threshold → auto` a threshold of 1.0 queues everything. Module 9 should implement the slider as a view filter or invert it; `assign_status` stays as specified.
12. **One `NumericVariant` per block** (contract). A block with two text-layer/OCR conflicts can resolve only one; the other stays a violation until a human edits it.
13. **Table OCR false alarms:** OCR misses row-span cells, so `textlayer_vs_ocr` is low on 2 of 6 fixture tables. Accepted, because tables are numeric and queued anyway; calibration can revisit.
14. **Scanned review load** is 49/176 (28%), mostly RapidOCR noise in `parser_agreement`. That is the price of recall 24/24. Module 10 may tune `AGREEMENT_CRITICAL_BELOW` per doc kind.
15. **Module 1 follow-ups** that affect scoring:
    - The fused scanned caption `b-scanned-p006-08`.
    - Scanned blocks are split relative to GT (176 vs 150); test 21 uses page-substring matching so splits don't count as errors.
    - Header/footer lines fused into body blocks; AE3's `hf_key` match covers them.
16. **Geometric-mean dilution** with variable signal counts. SPEC formula kept; mitigated by the value-dependent criticals.
17. **Interleaved-column raw text with hyphenation** fails the reorder check (fails closed, goes to review).
18. **Header/footer blocks** are scored but never queued (they are `unassigned/header_footer` in the manifest).
19. **`labor check`** is still `_not_implemented`. Modules 7/11 add the `score` stage to it, mocked (verifier skipped because project-a uses the same mock model for cleanup and verifier).
