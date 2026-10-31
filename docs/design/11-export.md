# Module 11 design: assemble + export + acceptance

Inputs: SPEC §1, §3, §4.7, §6, §7.4, §9, §11 · CLAUDE.md (gate 11, "silently dropping blocks", `labor check`) · `00-contracts.md` §4.3, §4.9, §4.10, §10.4/5/7/11 · `02-figures.md` §6, §9, §14 · `03-scoring.md` §1 · `04-grouping.md` §2-§5 · `05-cleanup.md` §1, §4, §5 · `07-api-state.md` §2.3, §3, §5.3, §6 · code as it is now (`contracts/{article,manifest,figure}.py`, `ids.py`, `project.py`, `state/review.py`, `api/routers/export.py`, `cleanup/attach.py`, `jobs/{graph,executor}.py`, `check.py`, `schemas/Manifest.json`).
Gate (CLAUDE.md): zip validates; every FIG reference resolves; README generated; SPEC §11 checklist run end-to-end and recorded in `docs/ACCEPTANCE.md`.
Implementer: one Opus agent for `export/` + pipeline/API/check wiring; one Sonnet agent for `scripts/acceptance.sh` + `docs/ACCEPTANCE.md` rendering (§9). Report what you cannot satisfy; do not change this design.

## 0. Facts this design rests on (read from the code, 2026-10-29)

| # | Fact | Consequence |
|---|---|---|
| 1 | Blocks reach module 11 only through `state.review.load_review_blocks(paths, store, slug)`: machine scores + `clean.json` overlay + human decision overlay (`status`, edited `clean_text`, `numbers_verified`). Figure, header, footer blocks have `clean_text=None`. | text source = `clean_text` (overlay) else `raw_text`; figures come from attachments, not block text |
| 2 | `attach.json` (module 5) already fixes article ids, per-article figure lists, rule, `anchor_block_id`, sorted by `(anchor reading order, figure_id)`; `cleanup.attach.build_articles` is the single article-membership function | assemble reuses `build_articles`; it never re-derives membership |
| 3 | `Manifest` validators (a)-(g) already enforce the exact partition, `duplicate_of`/`file` agreement and per-doc `block_ids` | assemble builds a `Manifest` and lets it self-validate; `validate.py` re-checks from the zip |
| 4 | Project figure files live at `figures/<slug>/FIG-*.png|svg|json`; a duplicate's sidecar `file` is `../<canon-slug>/<canon-id>.png`; `figures/index.json` has the dedupe truth | export copies one image per canonical; sidecars of duplicates are exported too |
| 5 | `BlockAccounting.unassigned_reasons` allows `not_selected, header_footer, rejected, empty` only; nothing in modules 1-10 yet produces status `rejected` | no new reasons are needed (policy P2); `rejected` is honoured when something produces it |
| 6 | `jobs/graph.py` already declares `assemble`/`export` as project-level nodes (not in `DOC_NODES`); `Plan.units` are `(node, slug)` pairs | project-level units use slug `""` |
| 7 | `ExportStatus{unlocked, open_flags, overrides}` and `ActionKind.export_override` exist; the three routes are stubs (`not_implemented`) | §6 fills them |
| 8 | `check.run_check(..., extra_checks=)` exists; `tests/fixtures/project-a` holds only `clean.pdf` + `figures.pdf` | the 6-fixture round-trip needs a project the acceptance script builds (§9) |
| 9 | No runtime offline guard exists; module 6 has only the test-time `install_guard` | §9 adds `MANUALLABOR_OFFLINE=1` |

## 1. Policies (decisions; every one is tested)

| # | Policy |
|---|---|
| P1 | **Contributing blocks.** A block contributes text to an article iff its overlay status is `auto_approved`, `approved` or `edited`. Text = `clean_text` (for `edited`, the human text). `raw_text` is used only when `clean_text is None` on a text block that is approved (a block cleanup never touched). |
| P2 | **Non-approved blocks (`queued`, `flagged`) are never exported silently and never exported with a marker.** The export **gate** (stricter than SPEC §7.4's "zero open flags", see open issue 1) blocks while any in-scope block is `queued` or `flagged`. `unlocked = (open_flags == 0 and queued == 0)`. Without an override, `labor export` / `POST /export` refuse with the counts and the first 20 offending block ids. **With an override** the blocks are exported with their machine `clean_text` (else `raw_text`), exactly like approved ones (no inline marker: the body stays pure source text), counted in `review.overrides` of their article, and listed one by one in `manifest.overrides` (`target_id` = block id, `flag_id` = its open flag or None, `reason`, `at`). `rejected` blocks are never exported (assigned `unassigned`, reason `rejected`). |
| P3 | **Override record.** `POST /export/override` / `labor export --override "<reason>"` appends an `actions` row (`kind=export_override`, `payload{reason, target_id|None, flag_id|None}`). `target_id=None` (and no `flag_id`) is blanket (covers every queued/flagged block at export time, including flags raised after it was recorded). A `flag_id` covers that flag (and the queued/flagged state of the block it targets). A `target_id` covers the block's queued/flagged review state and **never an open flag** on it, whichever was recorded first (amended 2026-10-30, §14; before, it covered the flags already open when it was recorded, which let a batch of block overrides swallow a flag); `POST /export/override` refuses a `target_id` (without `flag_id`) on a block with an open flag (422). Overrides count only if their action id is greater than the last `export_run` action (new `ActionKind`, appended after every successful export), so an old override never silently covers new problems. |
| P4 | **Selected + header/footer.** Unselected body blocks and header/footer blocks are `unassigned` (`not_selected`, `header_footer`). A selected non-figure block whose `collapse_ws(raw_text) == ""` is `unassigned` (`empty`) and removed from its article. An article left with no member that renders anything (all `empty`) is not written. |
| P5 | **Figures.** A figure is exported iff `attach.json` attaches it to ≥ 1 *written* article (a caption_ref pulls in a figure whose own block is unselected; that block stays `unassigned/not_selected`, the figure is still exported). Its canonical (`duplicate_of` chain root) is exported too, even if unattached (manifest rule f). One image file per canonical; every duplicate keeps its own sidecar. Vector figures export **both** `FIG-x.svg` and `FIG-x.png`; Markdown references the PNG. |
| P6 | **A figure renders once per article, at its attachment point** (never at its own block position unless that is the anchor). A figure block whose figure is anchored elsewhere, or whose extraction failed, renders nothing; the block is still in `article.block_ids` (accounted). |
| P7 | **Stale inputs refuse.** `assemble` requires every doc's nodes up to `score2` to be `fresh` (module 7 `node_state`); otherwise `ExportError("stale: <doc>:<node>")`, exit 1. |
| P8 | **No splitting, no truncation.** One article per group/document regardless of size; `ExportSummary.warnings` lists articles whose body exceeds 500,000 bytes. |

## 2. Package layout (`manuallabor/export/`)

| File | Contents (pure unless "I/O") |
|---|---|
| `types.py` | `EXPORT_ALGO_VERSION="1"`, `ExportError`, `Problem{code, where, detail}`, `ExportPlan`, `BuiltArticle{id, path, text: str, frontmatter: ArticleFrontmatter, block_ids, figure_ids, body_parts: list[BodyPart]}`, `BodyPart{kind: title\|block\|figure, block_id\|figure_id, text}` (kept so tests can re-derive), `Assembled{articles, figures: list[BuiltFigure], manifest, readme, files: dict[str, bytes\|Path]}` |
| `gate.py` | `export_gate(blocks_by_doc, flags, overrides) -> Gate{unlocked, open_flags, queued, blockers: list[BlockId], covered: dict[BlockId, Override]}` (P2/P3) |
| `render.py` | `render_block(block, heading_depth) -> str`, `render_list`, `alt_text`, `figure_line`, `yaml_frontmatter(fm) -> str` (§3.2-3.4) |
| `assemble.py` | `assemble(inputs: AssembleInputs, clock) -> Assembled` (pure over loaded data) and `load_inputs(paths, store) -> AssembleInputs` (I/O: `load_review_blocks`, `GroupsFile`, `AttachFile`, `DescribeFile` not needed, sidecars, `figures/index.json`, selection, flags, actions) |
| `manifest.py` | `build_manifest(...) -> Manifest`, `used_models(paths, cfg)`, `learning_provenance(paths, cfg, slugs)` |
| `readme.py` | `render_readme(manifest, summary) -> str` (§5.2) |
| `zip.py` | `write_zip(assembled, out_path)`, `ZIP_DATE=(1980,1,1,0,0,0)` (§5.1) |
| `validate.py` | `validate_zip(path, *, schema_path=None) -> list[Problem]` (§5.3); reads the zip only |
| `pipeline.py` | `run_assemble(paths, store, clock, emit, force) -> status`, `run_export(...)`, `fingerprint`, `export_status(paths, store) -> ExportStatus`, `record_override(...)` (I/O) |

CLI (`cli.py`): `labor assemble <project> [--force]`, `labor export <project> [--override REASON] [--target ID] [--now ISO] [--out PATH] [--json] [--force]`. Exit: 0 ok · 1 stale/validation/internal failure · 2 gate locked (prints blockers) · 3 project lock held. `labor export` runs `executor.run_node("export")` so upstream staleness is detected. `--now`/`MANUALLABOR_NOW` inject the clock (tests, acceptance); default `utc_now`, truncated to whole seconds.
Paths (`project.py`): `ProjectPaths.export_dir = root/"export"`, `.assembled = export_dir/"assembled"` (staging tree, same layout as the zip), `.export_state = export_dir/"state.json"`, `.zip_path = export_dir/f"{slug(config.name)}-kb.zip"`.

## 3. Assemble

### 3.1 Per-doc, then per-article (all deterministic; no set iteration reaches output)
1. Load per doc: review blocks, `GroupsFile`, `AttachFile`, `Document`, sidecars, selection (`load_selection` or `default_selection`), `split = selection.article_split`.
2. `members = build_articles(slug, gf, selected, split, order)`; drop `empty` blocks (P4); drop articles with no renderable member.
3. Each remaining member is classified by status (P1/P2/gate). Gate-covered blocks (override) are marked `override=True`. `rejected` → unassigned.
4. **Title**: per-topic → `Group.title` of the topic (t000 → "Unassigned blocks"); per-document → `Document.title or Path(filename).stem`. **sections**: distinct `section_number` of the structure groups owning ≥ 1 contributing block (groups without a number skipped), sorted by integer tuple. **pages**: distinct `block.page` of contributing blocks, sorted. **figures**: ids in order of first appearance in the body. **blocks**: `len(block_ids)` (all members after P4/rejected removal, including figure blocks). **review**: `approved` = members with status in {auto_approved, approved, edited}, `edited` = status edited, `overrides` = override-covered members. Hence `approved + overrides <= blocks` (ArticleFrontmatter keeps `approved <= blocks`; override-covered blocks are *not* in `approved`).
5. `product_model` = `Document.product_model`; `source_file` = `Document.filename`.

### 3.2 Body grammar (the only text transformations; test E1 re-derives it byte for byte)
```
article   := frontmatter "\n" "# " title "\n\n" part ("\n\n" part)* "\n"
frontmatter := "---\n" yaml "---\n"
part      := block_part | figure_part
```
| Block type | `part` |
|---|---|
| heading (structure node: first block of a structure group whose `title_sources` is `heading`) | `"#" * min(6, 1 + group.level) + " " + t` (`group.level` = tree depth, 1 = top; H1 is reserved for the article title). The heading text keeps its section number. |
| heading that cleanup/grouping demoted (D1-D3), any non-node heading | `t` as a plain paragraph |
| paragraph, caption, other, table | `t` verbatim (tables: `clean_text` is already GFM; a table without `TableData` is `raw_text` verbatim) |
| list | `render_list(t)`: each line `L` → `"* " + L[2:]` if `L` starts with `"• "`; `L` unchanged if it matches `^(?:\(?\d{1,2}[.)]\|[a-z][.)])\s`; otherwise (item without glyph) `"* " + L`. `*` is used, not `-`, because `FAITH_NUM_RE` treats a sign before a number as part of the number (`- 12 V`). |
| figure block | no part (P6); placement of the figure itself is §3.3 |

`t` = P1 text, no trimming, no escaping, no reflow. Markdown meta-characters in source text are **not** escaped (escaping would alter the text; open issue 3). Separator between parts is exactly one blank line. No marker is ever inserted for overridden blocks.

### 3.3 Figure placement (per article, from `attach.json` `ArticleAttachments.figures`, already sorted)
| Rule | Position `P(F, A)` |
|---|---|
| `caption_ref`, `caption_match`, `human` with an anchor | immediately after the part of `anchor_block_id`, when that block contributes to A |
| `proximity`, or `human` with no anchor | immediately after F's caption block (`FigureExtraction.caption_block_id` from `figures_report.json`) when it contributes to A; else immediately after F's own figure block position (the parts before/after it in reading order) |
| fallback | anchor/caption/figure block absent or excluded: the end of the article |

Several figures at one position keep attach order. `figure_part = "![" + alt + "](" + image_path + ")"`.
- `image_path` = `images/<canon-slug>/<canon-id>.png` (**rewritten to the canonical** for duplicates; the alt text keeps the figure's own id).
- `alt` = `f"{fid} — {cap}"`, ` — ` = U+2014 with single spaces. `cap` = `caption_original` (whitespace-collapsed) if present; else `"[generated] " + description_generated`; else `"(no caption)"`. `\`, `[`, `]`, `)` in `cap` are backslash-escaped (CommonMark punctuation escapes, so a caption containing `](` can never break the link; review fix M11.4); newlines become spaces. Alt text is metadata, not article text, so it is outside the byte-derivation rule except for its id prefix.
- Regex every figure line must satisfy: `^!\[FIG-[a-z0-9-]+-p\d{3,4}-\d{2,3} — .*\]\(images/[a-z0-9-]+/FIG-[a-z0-9-]+-p\d{3,4}-\d{2,3}\.png\)$`.

### 3.4 Frontmatter (`render.yaml_frontmatter`)
Keys exactly in `ArticleFrontmatter` declaration order (= SPEC §6.2): `id, title, source_doc, source_file, product_model, pages, sections, figures, blocks, review, generated_at`. Hand-written emitter (no `yaml.dump`) so bytes are stable across PyYAML versions:
- lists: flow style `[41, 42]`, items scalars; empty list `[]`; `review: { approved: 7, edited: 1, overrides: 0 }` (SPEC spacing); `null` for None.
- string scalar: plain iff it matches `^[A-Za-z][A-Za-z0-9 _.,&()/'-]*$`, has no trailing space and is not one of `true false null yes no on off ~`; otherwise `json.dumps(s, ensure_ascii=False)` (a valid YAML double-quoted scalar). `sections: ["5.1"]` is therefore quoted.
- `generated_at`: `2026-10-28T18:00:00Z` unquoted as in SPEC; `validate.py` loads YAML with a SafeLoader whose timestamp resolver is removed, so it stays a string.
- `generated_at` is the same injected-clock value for every article and for `manifest.project.generated_at`.

### 3.5 Manifest (`manifest.build_manifest`; `Manifest.model_validate` runs all validators; `write` via `contracts.io.dump_json`)
| Field | Source |
|---|---|
| `project` | `{name: config.name, tool_version: manuallabor.__version__, generated_at: clock}` |
| `docs` | all registered docs (also docs with nothing exported), `block_ids` in parse order |
| `articles` | one per written article; `block_ids` in reading order; `figures`, `pages`, `sections` as the frontmatter |
| `figures` | exported figures (P5): `{id, sidecar, file: sidecar.file, source_doc, duplicate_of from figures/index.json}` |
| `review_stats` | over **all** blocks of all docs (overlay statuses): counts per status; `overrides` = number of override-covered blocks; `numbers_verified_blocks` = ids with `numbers_verified` |
| `models` | for each task present in `llm_calls.jsonl`, the last logged `ModelRef(provider, model)`; falls back to `config.model_for(task)` for tasks that left stage provenance (`groups.json.embedding_model`, `grouping_model`) but no log |
| `threshold`, `article_split` | `config.threshold`; `selection.article_split` |
| `overrides` | one `Override` per override-covered block (P2), sorted by `target_id` |
| `accounting` | `assignments`: every parsed block id → article id or `"unassigned"`; `unassigned_reasons` per P4/P2 |
| `learning` (**new field**, §10) | `{enabled, docs: {slug: {group: <GroupsFile.learning_snapshot>, clean: <CleanFile.learning_snapshot>}}}` |

## 4. Figure files and sidecars (copied into the staging tree)
- Image bytes are copied verbatim (no re-encode). Canonical `images/<slug>/FIG-x.png` (+ `.svg` for vector). Dedupe never copies a duplicate's own file.
- Sidecar `images/<slug>/FIG-x.json` = the project sidecar re-validated as `FigureRecord` with only these fields rewritten: `articles` = exported article ids that reference it (sorted), `review` = the figure block's overlay status (`approved` for a figure whose block is unselected but pulled in by caption_ref is not invented: it keeps the sidecar's status). `file`/`svg` stay as module 2 wrote them (own path, or `../<canon-slug>/<canon-id>.png|svg`). Written with `write_json`; never contains absolute paths.
- A figure with `extraction == vector` and `svg` missing on disk, or a PNG that Pillow cannot decode, is an `ExportError` (not skipped).

## 5. Zip, README, validate

### 5.1 `zip.py` (deterministic)
Entries sorted by path (byte order): `README.md`, `articles/*.md`, `images/<slug>/*` , `manifest.json`. Each `ZipInfo`: `date_time=ZIP_DATE`, `create_system=3`, `external_attr=0o644<<16`, no extra fields, no comment, no directory entries. `.md/.json/.svg` use `ZIP_DEFLATED` level 9; `.png` uses `ZIP_STORED`. Text is UTF-8, `\n` newlines, JSON via `canonical_json` + trailing newline. Written to `<out>.tmp` then `os.replace`. `labor export` prints `sha256` of the zip.
Staging: `assemble` writes the same tree under `export/assembled/` (clean dir first); `export` zips from it, so `assemble` is inspectable and `export` is a pure function of it.

### 5.2 `README.md` (`readme.render_readme`, no timestamps beyond `manifest.project.generated_at`)
Sections in order: **What this is** (project name, tool version, generated_at, N articles / M figures / P pages, source documents with sha256 prefix); **Contents** (the zip layout); **IDs** (doc slug, block id, `FIG-<docslug>-p<page>-<n>`, article id, the two regexes `FIG-[a-z0-9-]+-p\d{3}-\d{2}` and the alt-text rule, "figure references resolve to `images/<slug>/<id>.png` and a `.json` sidecar"); **How to ingest** (glob `articles/*.md`; split on the first two `---` lines; frontmatter keys; read `manifest.json` for the id → file → block map; for text-only retrieval use `description_generated`, labelled generated, and `caption_original`); **Faithfulness** (article text is source text cleaned, never rewritten; `review` counts; `numbers_verified_blocks`); **Overrides** (count; "N blocks were exported without human approval; see manifest.overrides" or "none"); **Models and threshold used**; **Learning provenance**.

### 5.3 `validate.py`: `validate_zip(path) -> list[Problem]` (empty = valid). Reads **only** the zip.
| Code | Check |
|---|---|
| Z1 | zip opens; no duplicate/absolute/`..` names; entries sorted; only `README.md`, `manifest.json`, `articles/*.md`, `images/<slug>/FIG-*.png|svg|json` |
| Z2 | `manifest.json` validates against `schemas/Manifest.json` (jsonschema) and then `Manifest.model_validate` (partition, duplicate rules) |
| Z3 | `{articles in zip} == {manifest.articles paths}`; each file's frontmatter parses, has exactly the 11 keys in order, validates as `ArticleFrontmatter`; `blocks == len(manifest block_ids)`; `pages/sections/figures` equal the manifest; `generated_at == manifest.project.generated_at` |
| Z4 | every `![...](...)` line matches the figure regex of §3.3; the path is a zip entry; `FIG` id has a sidecar entry; sidecar validates as `FigureRecord`; the sidecar's `file` (path-normalized relative to its directory) equals the Markdown path; PNG decodes (Pillow `verify`), SVG parses as XML |
| Z5 | every `FIG_ID_SEARCH_RE` match anywhere in an article body is in `manifest.figures`; `frontmatter.figures` == first-appearance order of figure lines |
| Z6 | `{sidecars in zip} == {manifest.figures}`; each sidecar's `articles` ⊆ manifest articles and each of those articles' bodies references it; no orphan image/svg file (every file is the target of some sidecar `file`/`svg`); a `duplicate_of` figure has no own image file; its canonical has |
| Z7 | `sum(article.review.overrides) == review_stats.overrides == len(manifest.overrides)`; each override `target_id` is a block of an article |
| Z8 | README present, non-empty, mentions the manifest's article count |
Each problem has a stable `code` so tests can assert the specific check that caught a mutation.

## 6. Pipeline, CLI, API

**Stage graph.** Add `assemble` (upstream: every doc at `score2` + decisions + selection) and `export` (upstream: `assemble`). Project-level units are `("assemble","")`, `("export","")`. `make_plan(to="assemble"|"export")` adds them after all doc units; `node_state` for them: output missing → `missing`; fingerprint ≠ recorded → `stale`; any doc node not fresh → `stale`.
- `assemble` fingerprint = sha256(canonical_json{algo, per doc: sha of blocks.json, scores.json, clean.json, attach.json, groups.json, figures index entries, sidecars; selection sha; `max(decisions.seq)` per doc and the set of open flag ids; override action ids (since last `export_run`); config threshold/name/split}). The clock is excluded, so a rerun with a new clock is a skip (no byte churn); `--force` re-stamps.
- `export` fingerprint = sha of `export/assembled/` tree hashes; it zips, then calls `validate_zip` and refuses to leave a zip that does not validate (writes `<zip>.rejected` instead, exit 1). Success appends one `actions` row `kind=export_run` with `{zip_sha256, articles, figures, overrides}`.
- Gate: `export_gate` runs inside `assemble` before any file is written; locked → no staging files, exit 2.

**API (`api/routers/export.py`; all `def`, no model calls).**
| Route | Behaviour |
|---|---|
| `GET /api/export/status` → `ExportStatus` | `unlocked`, `open_flags`, `queued` (new), `blockers` (≤ 20 block ids), `flag_blockers` (every uncovered open flag, §14), `counts: ExportScopeCounts` (§14), `overrides` (active, P3), `summary: ExportSummary \| None` (last export), `zip_path` |
| `POST /api/export` (`RequestIn`) → 202 `JobInfo` | checks the gate synchronously: locked → 409 `{"code":"export_locked", counts}`; else enqueues job `kind="export"` (plan `{to:"export"}`); the worker dispatches to `run_plan(to="export")`; resumable like any job |
| `POST /api/export/override` (`OverrideIn`) → `ExportStatus` | appends the `export_override` action (idempotent via `request_id`); 422 if `target_id`/`flag_id` unknown |
| `GET /api/export/download` → `FileResponse` | 404 until an export exists; header `X-Content-SHA256` |
`ExportSummary{articles, figures, pages_covered, docs, review: {blocks, auto_approved, approved, edited, overrides, numbers_verified, total_blocks, left_out}, warnings: list[str], zip_bytes, zip_sha256, generated_at}` (the `review` buckets as amended in §14); `pages_covered` = distinct `(doc, page)` of contributing blocks. The summary is what the Export screen shows (SPEC §7.4).

## 7. Faithfulness, end to end
| Invariant | Mechanism |
|---|---|
| F1 body is the concatenation of block text | `BuiltArticle.body_parts` records `(block_id, t)`; test E1 recomputes `t` independently from `load_review_blocks` and the body grammar (a test-local renderer, not `render.py`) and compares the whole file byte for byte |
| F2 numbers | per article, `Counter(FAITH_NUM_RE.findall(body))` computed on the body minus title line, heading `#` prefixes and list `* ` markers equals the union over contributing blocks of `Counter(FAITH_NUM_RE.findall(t))` (E2); a synthetic list block `• 12 V` pins the marker choice |
| F3 no block lost | `Manifest` partition + validate Z2 + `check` K13 against `blocks.json` ids |
| F4 no new text | the only strings not from `t`: title line, `#` prefixes, `* ` markers, figure lines, frontmatter, README (E3 greps the body for any line not explained by these) |
| F5 export of approved text only | gate + P1; E5/E6 |

## 8. Determinism
Same project state + same clock ⇒ byte-identical `manifest.json`, articles, README and zip across processes and `PYTHONHASHSEED`s (E14). Sources of order: `block_sort_key`, sorted ids, `ZIP` order, canonical JSON. Nothing reads wall time except through the injected clock; no absolute path, hostname or job id is written. Without a clock injection the only varying bytes are `generated_at`.

## 9. `labor check` completion and acceptance
**`labor check`** (mock and `--live`; `check.py` gains steps after K1-K9, same table):
| # | Step / check |
|---|---|
| K10 | gate refuses: before any review, `export_status.unlocked is False` when ≥ 1 block is queued, and `labor export` exits 2 with blockers listed (skipped if the project has no queued block) |
| K11 | scripted reviewer: approve every queued in-scope block through `ReviewService.act` (request ids `cli-check-approve-<block_id>`, stored as real decisions); then `run_inline(RunPlanIn(to="export"))` with a fixed clock |
| K12 | `validate_zip` returns no problems; row detail = `N articles, M figures, K bytes` |
| K13 | accounting equals `blocks.json`: every parsed block id is in exactly one article or `unassigned` with a reason (headers/footers `header_footer`); `review.overrides == 0` |
| K14 | per-doc round-trip table `doc | blocks | auto_approved | faith_violations(auto) | articles | figures`; fails if any `faith_violations(auto) != 0` (SPEC §11.1) |
| K15 | determinism: export a second time with the same clock into a temp zip; sha256 equal |
| K16 | every `FIG-` reference in every article resolves to a file and a sidecar (independent re-scan, not `validate.py`) |
Live mode runs the same minus K7. `labor check` stays read-only on the source project (temp copy).

**Network disable (`MANUALLABOR_OFFLINE=1`).** New `manuallabor/providers/offline.py` (so the T5 static scan still allows `socket` only under `providers/`): `install_guard(allowed: set[tuple[str,int]])` monkeypatches `socket.getaddrinfo`, `socket.socket.connect/connect_ex`, `socket.create_connection`; allowed = `OLLAMA_HOST` (default `127.0.0.1:11434`) and AF_UNIX. Any other destination appends to `$MANUALLABOR_OFFLINE_LOG` (default `<tmp>/offline-violations.log`) and raises `OSError("offline guard")` (the log catches swallowed errors). Installed first thing in `cli.app` callback and in `jobs/worker.py` main. Also sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `LITELLM_LOCAL_MODEL_COST_MAP=True`. Negative control test: a subprocess with the guard tries `socket.create_connection(("1.1.1.1",443))` and must raise and log.

**`scripts/acceptance.sh [--live]`** (bash, `set -u`, never `set -e`; each step runs, its exit code and output are captured; the script's own exit = 1 if any required step failed, 0 otherwise). Steps write `build/acceptance/<n>.{cmd,out,rc}`; then `uv run python scripts/render_acceptance.py build/acceptance > docs/ACCEPTANCE.md`.
| AC | Command(s) | Evidence pasted | Verdict rule |
|---|---|---|---|
| 0 | `uv run pytest -q`, `uv run ruff check manuallabor tests`, `uv run mypy manuallabor`, `uv run labor schemas export --check`, `uv run labor openapi export --check` | last 5 lines each | all rc 0 |
| 1 | the script builds `$TMP/project-all` (project-a's `project.json` + all six `tests/fixtures/{clean,twocol,tables,scanned,figures}.pdf` + `manual.docx` in `sources/`) and runs `uv run labor check $TMP/project-all` | the full check table incl. K3, K13, K14 (per-fixture faith violations on auto-approved = 0), K12 | rc 0 and K3, K14 PASS |
| 2 | `uv run pytest tests/scoring -m acc2 -s -q` (module 3 test 21: scanned-fixture recall; prints `RECALL k/n at threshold 0.85`) | the RECALL line | recall printed; n ≥ 1; rc 0 (design target 24/24) |
| 3 | `uv run pytest -m acc3 -s -q` (module 2 test: figures.pdf `native+vector / total` ≥ 0.95, prints `FIGURES native=a vector=b crop=c`; module 5 test: every caption-ref figure's article == GT, prints `ATTACH ok k/n`) | both lines | rc 0 |
| 4 | `cd frontend && npm run e2e -- --grep "@AC4"` (module 9: 20 queued blocks, keyboard only) | Playwright summary | rc 0 |
| 5 | `uv run pytest -m acc5 -s -q` (module 10: 5 seeded flags, every proposal carries its re-check results; prints `PROPOSALS 5/5 with checks`) | the line | rc 0 |
| 6 | `cd frontend && npm run e2e -- --grep "@AC6"` (module 8: toggle keeps selection, coverage correct) | summary | rc 0 |
| 7 | `uv run pytest tests/export -q`, then on the AC1 project's export: `uv run labor validate-export <zip>` (new tiny CLI over `validate_zip`, prints `OK: N articles, M figures` or the problems) | both outputs, zip sha256 | rc 0 |
| 8 | `ollama list` (models present), then `MANUALLABOR_OFFLINE=1 MANUALLABOR_OFFLINE_LOG=build/acceptance/net.log uv run labor check --live $TMP/project-all`, then `test ! -s build/acceptance/net.log` | check table with `provider` column from `llm_calls.jsonl` (`ollama` only), "0 network violations" | rc 0, log empty, `llm_calls.jsonl` has ≥ 1 `ollama` row and 0 non-ollama rows |
`SKIP` is not a pass: if Ollama or its small-tier models are absent (AC8), or `--live` is not given, AC8 is rendered `NOT VERIFIED` with the `ollama pull` commands, and `docs/ACCEPTANCE.md` header says `status: INCOMPLETE`. `docs/ACCEPTANCE.md` header also records tool version, `uv.lock` sha256, OS/RAM, date, and per-AC verdict table; each AC section has the command, rc, and the pasted output (full for tables, last 80 lines otherwise). The orchestrator runs the script last and commits the rendered file.
Marker registration (`pyproject.toml`): `acc2, acc3, acc5` on the named existing tests (implementer adds the marker + the `print` evidence line; if a named test does not exist yet, report it).

## 10. Contract and model changes (regenerate `schemas/`, TS types, OpenAPI)
| # | Change |
|---|---|
| C1 | `Manifest.learning: ManifestLearning` (`enabled: bool`, `docs: dict[DocSlug, {group: str, clean: str}]`), default empty; `schema_version` stays `"1.0"` (additive); the README and Z2 use it |
| C2 | `state/models.py`: `ExportStatus` gains `queued: int = 0`, `blockers: list[BlockId] = []`, `summary: ExportSummary \| None = None`, `zip_path: str \| None = None`; new `ExportSummary`; `ActionKind.export_run` |
| C3 | `project.py` paths of §2; `cli.py` commands `assemble`, `export`, `validate-export`; `jobs/worker.py` dispatches `kind == "export"` |
| C4 | `jobs/graph.py` / `executor.py`: project-level units and `node_state` for `assemble`/`export` |
| C5 | `providers/offline.py` + guard installs (§9); `pyproject.toml` markers `acc2, acc3, acc5` |

## 11. Test list (`tests/export/`; session fixture `exported_a` = project-a through `run_check`-style pipeline + scripted reviewer + export with clock `2026-10-29T12:00:00Z`; `exported_dup` = `figures.pdf` + a byte copy `figures-copy.pdf`; `synthetic` = hand-built `AssembleInputs` with no parser)
| # | Test | Fixture | Assertion |
|---|---|---|---|
| E1 | body byte derivation | `exported_a` (clean, figures) | for every article, the file equals frontmatter + `# title` + parts derived by a test-local renderer from `load_review_blocks` text and `attach.json` placement |
| E2 | numeric multiset | `exported_a`; synthetic list block `• 12 V`, `• - 12 V` | per-article `FAITH_NUM_RE` multiset of the body (minus title/prefix/markers) == union of its blocks'; `* 12 V` yields `12`, not `-12` |
| E3 | no foreign text | `exported_a` | every body line is explained by: a block line, `# title`, a heading prefix, a list marker, a figure line, or blank |
| E4 | frontmatter order and format | `synthetic` | keys exactly `id,title,source_doc,source_file,product_model,pages,sections,figures,blocks,review,generated_at`; `sections: ["5.1"]` quoted; `review: { approved: 7, edited: 1, overrides: 0 }`; `null` product_model; title with `&`, `:` and `#` quoted correctly; round-trips through the timestamp-less YAML loader to `ArticleFrontmatter` |
| E5 | statuses (P1) | `synthetic` | approved/edited/auto_approved contribute `clean_text` (edited = human text); `rejected` excluded and `unassigned/rejected`; raw fallback only when `clean_text is None` |
| E6 | gate refuses (P2) | `synthetic` + store | 1 queued or 1 open flag ⇒ `unlocked False`, `labor export` exit 2, no staging files, blockers listed; resolving/approving ⇒ unlocked |
| E7 | override (P2, P3) | `synthetic` | blanket override: queued + flagged blocks exported with machine text, no marker in body, `review.overrides` counts them, `manifest.overrides` lists each with reason and `flag_id`; targeted override covers only its block; an override older than the last `export_run` does not apply |
| E8 | alt text and path regex | `exported_a` (figures.pdf) | every figure line matches the §3.3 regex; alt starts with `<FIG-ID> — `; caption original used when present, `[generated] ...` otherwise, `(no caption)` last; `[`/`]` escaped |
| E9 | placement | `synthetic` | caption_ref: right after the referencing block; proximity: after the caption block, else at the figure block, else end; caption_ref figure whose own block is in another article renders only where attached; two figures at one anchor in attach order; anchor excluded ⇒ fallback chain |
| E10 | dedupe | `exported_dup` | the zip has one PNG per canonical; copy figures' articles reference the canonical path; the copy's sidecar exists with `file = ../figures/FIG-figures-p00N-0M.png`; `manifest.figures[].duplicate_of` set; canonical present even when only the copy is attached |
| E11 | vector figure | figures.pdf vector figure | both `.png` and `.svg` in the zip; sidecar `svg` set; Markdown references the PNG |
| E12 | manifest partition | `exported_a` + `synthetic` | every parsed block id exactly once in `accounting`; header/footer blocks `unassigned/header_footer`; unselected `not_selected`; `empty` per P4; `Manifest.model_validate(json)` ok; `blocks == len(block_ids)` per article |
| E13 | per_document vs per_topic | `exported_a` with `article_split` toggled | ids `<slug>` vs `<slug>--<topic>`; same contributing blocks; t000 ⇒ `<slug>--unassigned` |
| E14 | determinism | `exported_a` ×2 processes, `PYTHONHASHSEED=1` vs `99` | zip sha256, `manifest.json`, README byte-identical; a different clock changes only `generated_at` lines |
| E15 | zip structure | `exported_a` | sorted entries, `date_time==ZIP_DATE`, no directory entries, PNG stored, text deflated, `testzip()` None |
| E16 | validate positive | `exported_a`, `exported_dup` | `validate_zip == []` |
| E17 | validate negative (mutate a copy of the zip, assert the specific code) | `exported_a` | delete a sidecar ⇒ Z4/Z6; rewrite an image path to a missing file ⇒ Z4; drop an article from `manifest.articles` ⇒ Z2/Z3; remove a block id from `accounting` ⇒ Z2; reorder frontmatter keys ⇒ Z3; add a stray `FIG-x-p001-01` prose mention ⇒ Z5; orphan PNG ⇒ Z6; corrupt PNG bytes ⇒ Z4; override count mismatch ⇒ Z7; remove README ⇒ Z8 |
| E18 | README | `exported_a` | present, names the article count, contains both FIG regexes, "How to ingest", and the override sentence ("none" here) |
| E19 | stale inputs (P7) | `exported_a` copy | touching `selection.json` / re-running clean after assemble ⇒ `node_state` stale; `assemble` after editing `blocks.json` ⇒ `ExportError("stale")`, exit 1 |
| E20 | fingerprint | `exported_a` | second `labor export` is `skip` with unchanged bytes (clock differs); a new approval, a new override or `--force` rebuilds |
| E21 | resume | `exported_a` | kill after `assemble`, rerun ⇒ export completes; `.tmp`/`.rejected` absent; staging tree equals a clean run |
| E22 | API | FastAPI client over `exported_a` store | status shape and `queued/blockers/summary`; `POST /export` 409 `export_locked` then 202 after approvals; override route records an action and is idempotent per `request_id`; `GET /export/download` serves the zip with matching `X-Content-SHA256` |
| E23 | `labor check` new stages | project-a (mock) | exit 0; rows K10-K16 PASS; K10 shows the refusal; project-a source tree untouched |
| E24 | summary | `exported_a` | `ExportSummary` counts equal a direct recount (articles, figures, `pages_covered`, review stats) |
| E25 | offline guard | subprocess | guard blocks `1.1.1.1:443`, allows `127.0.0.1:<stub>`, logs violations; `MANUALLABOR_OFFLINE=1 labor check` (mock) exits 0 with an empty log |
| E26 | six-fixture round-trip (marker `slow`, `acc1`) | `project-all` (clean, twocol, tables, scanned, figures, manual.docx) | check passes; per doc: ≥ 1 article, K14 `faith_violations(auto) == 0`, partition exact, `validate_zip == []`; the scanned doc's figures exported |
| E27 | live (`MANUALLABOR_LIVE=1`, skips with pull commands) | project-a + small-tier Ollama, `MANUALLABOR_OFFLINE=1` | `labor check --live` passes, log empty, `llm_calls.jsonl` only `ollama` |

## 12. Open issues (each resolved with a choice)
1. **Gate stricter than SPEC §7.4.** SPEC unlocks at zero open flags; numeric blocks are always queued (§5.1) and an unreviewed queued block cannot be exported as approved text. Choice: gate = open flags 0 **and** queued 0; the override path exports them (P2) so SPEC's "override allowed" is intact. UI wording: "N blocks not yet reviewed".
2. **Queued blocks excluded vs raw-with-marker.** Choice: neither is silent. Exclusion would hide content; a marker would add text that is not source. The override exports machine text and records every block in the manifest; there is no third state.
3. **Markdown escaping.** Source text starting with `#`, `>`, `1.` or containing `*`/`_` may render unexpectedly. Choice: no escaping in v1 (faithfulness over rendering); README states the body is source text. A later optional `--escape-markdown` would be a contract change.
4. **Per-document ordering.** Choice: reading order (`reading_order`), never by section or topic; per-topic articles use reading order within the topic.
5. **SVG + PNG for vector.** Choice: both, PNG referenced inline.
6. **Max article size.** Choice: no split; warn above 500,000 bytes (P8).
7. **caption_match placement vs "after the caption block".** The attach anchor is the matched body block (evidence), so caption_ref and caption_match place after the anchor; only proximity/human-no-anchor use the caption block.
8. **Caption-ref figure whose own block is unselected** is exported while its block is `unassigned/not_selected`; accepted, accounted in the manifest (`figures` lists it, `accounting` lists the block).
9. **Failed figure extraction** renders nothing; the figure block is accounted in its article. A visible placeholder would be non-source text. (Optional follow-up: `Manifest.figure_failures`.)
10. **`review.approved + overrides <= blocks`** (override blocks are not "approved"); the existing `ArticleFrontmatter` validator already allows this.
11. **Clock.** `generated_at` is whole seconds, one value per export.

## 13. Gaps to confirm in modules 5/7 output (implementer: check first, report, do not work around silently)
| # | Needed | Where |
|---|---|---|
| G1 | `FigureExtraction.caption_block_id` is present in `figures_report.json` for proximity placement; `AttachFile` has no caption id | module 2/5; read the report |
| G2 | A way to list `export_override` and `export_run` actions after a given id: `Store.actions(kind=..., after_id=...)` (check it exists; add a read-only helper if not) | module 7 `store.py` |
| G3 | `Store.flags(status=open)` entries must map to blocks: `Flag.target_id` may be a figure/article id; the gate counts only block/figure targets in scope | module 7 |
| G4 | `executor.make_plan`/`node_state` do not yet know project-level nodes (C4) | module 7 |
| G5 | Marker-bearing tests for AC2/AC3/AC5 (module 3 test 21, module 2 figure-method test, module 5 caption-ref test, module 10 seeded flags) and Playwright tags `@AC4`/`@AC6` | modules 2, 3, 5, 8, 9, 10; the acceptance script reports any missing as `NOT VERIFIED` |
| G6 | `tests/fixtures/project-a` has two PDFs; the six-fixture project is built by the script, not committed | acceptance script |
| G7 | Nothing produces `rejected` yet; the exclusion path is covered by a synthetic test only | modules 9/10 |

## 14. Flags under overrides, and counts that partition (2026-10-30, browser-run findings)

A first-time tester driving only the browser found two defects (`REPORT.md` section C items 1, 4, 13 of the human run; project `build/human-test`).

**F1. A batch of block overrides swallowed a flag.** The flag dialog promises "this flag locks the export until it is resolved". The Export screen's "Record N overrides" sent one `target_id` override per listed blocker, the flagged block included, and P3 let a block override cover the flags already open on that block. The lock went away and the block shipped with its machine text, with nothing on screen naming the flag. SPEC §7.4 allows overriding a flag; it does not allow doing it without saying so.

Rule (P3 amended):

| Override | Covers |
|---|---|
| blanket (no target, no flag; CLI `--override` only) | every blocker, flags included (unchanged; the CLI user asks for "everything") |
| `flag_id` | that flag, and the review state of the block it targets |
| `target_id` | the block's queued/flagged review state; **never** an open flag on it, whichever was recorded first |

- `export_gate` checks each open flag against blanket and `flag_id` overrides only; the action-sequence comparison (`flag_seq`) is gone.
- `record_override(target_id=b)` without `flag_id` raises `InvalidOp` (422) when `b` (or its figure) has an open flag, naming the flag id: such an override would look like a decision about the flag and change nothing.
- `ExportStatus.flag_blockers: list[ExportFlagBlocker{flag_id, block_id, category, note}]`: every open in-scope flag no override covers, uncapped, in the blockers' order.
- Export screen: the batch leaves out every listed blocker that has an open flag and says so ("1 flagged block left out of this batch"); each flag gets its own reason and button ("Export despite this flag", sends `flag_id`) in a separate "open flags" section. A blocker flagged between reading and sending is left out too and reported in the tally.

**Marking in the export.** Unchanged and deliberate (P2, open issue 2): no marker in the article body. An overridden block is counted in its article's `review.overrides` and listed in `manifest.overrides` with its reason and, for a flagged block, its `flag_id`; README says how many went out unreviewed. Which paragraphs a person checked is not visible in the article text. Whether to add per-block review provenance (a marker, or a per-block review map in the manifest) is a product decision for the owner, not made here.

**F2. The Export screen's counts did not add up, and after a success it showed the lock.** `ExportSummary.review` copied `manifest.review_stats`, which counts every parsed block by status (page headers and footers included, all auto-approved) and adds `overrides` as a cross-cut over queued and flagged blocks: 7 approved + 1 edited + 75 auto-approved + 101 overridden = 184, against 160 blocks in scope (51 auto-approved + 24 headers/footers = 75; 100 queued + 1 flagged = 101 overridden, also counted in `queued`/`flagged`). After the export, the gate is locked again because the export spends its overrides (P3), and the screen put "Export is locked" with the same blockers on top and the result below the fold.

Rules:

- `ExportStatus.counts: ExportScopeCounts{in_scope, auto_approved, approved, edited, rejected, overridden, blocking}` partitions the in-scope body blocks (the Verify scope: selected blocks plus attached figure blocks of ready documents, page headers and footers excluded): a queued, flagged or open-flagged block is `overridden` when an active override covers it, else `blocking`; every other block counts by its status. `in_scope`, `auto_approved`, `approved`, `edited` and `rejected` equal the Verify `ReviewCounts`; `overridden + blocking == queued + flagged_open` when no approved block carries an open flag.
- The gate no longer counts page headers and footers: they are never exported (P4) and Verify never shows them, so a queued header could lock the export with no way to resolve it.
- `ExportSummary.review` partitions the exported blocks (assigned to an article): `blocks == auto_approved + approved + edited + overrides` (an override-covered block only as an override, as in the frontmatter), and `left_out` counts the other parsed blocks by manifest reason: `total_blocks == blocks + sum(left_out)`. It is computed in `assemble` (`Assembled.review`) and kept in `export/state.json` (`AssembleRecord.review`) so a resumed export reports the same; an assemble record without it is rebuilt, and an old `state.json` whose summary lacks the new fields reads as no state. `manifest.review_stats` keeps its all-blocks meaning (it is the knowledge base's contract).
- Export screen order: the last export (title with its time, Download, the two equations, "Export finished" as a status message right after the job) is on top whenever one exists; below it the gate for a *new* export, headed "A new export is locked" (saying the last export used up its N overrides) or "Ready to export again". Before any export, the gate is on top. The locked view shows the scope equation ("160 blocks in scope = 51 auto-approved + 7 approved by you + 1 edited by you + 80 overridden + 21 still blocking"), which moves as overrides are recorded. The screen rereads the status when its export job finishes.

Tests: `tests/export/test_synth.py::test_e7_a_block_override_never_covers_an_open_flag`, `::test_gate_counts_partition_the_scope_and_skip_page_headers`; `tests/export/test_flags_counts.py` (batch never covers a flag, refusal at the service and the route, flag raised after a block override, scope partition against `ReviewCounts` on project-a unreviewed / partly reviewed / reviewed and the duplicate-figures project, the summary partition after an override export); `frontend/src/export/ExportScreen.test.tsx` U10b (batch leaves the flag out and the flag gets its own override, scope equation, last export on top after an override export and after a clean one, the job-finished flow, no summary before any export).

## 15. The status poll is a cache read (code review F4, 2026-10-30)
`export_status(paths, store, review=None)`: the API passes its serving `ReviewService`, and the gate (`export_gate` over the overlays and scopes) and the active overrides are cached on `(document slugs, each document's blocks/scores/clean/groups/attach stats, store.max_action_id())`. Every input the gate reads is in that key: the files of the machine view, the groups (the selection's normalisation and `with_new_docs`), the attachments (figure scope), and the action log, which every decision, flag, resolution, selection change, `export_override` and `export_run` appends to. A poll with nothing changed costs a few stats and one `MAX(id)`; after a write, the miss re-derives from the review cache instead of re-reading and re-validating every block. `export/state.json` and the zip are read per call. The semantics of section 14 (`counts`, `flag_blockers`, coverage) are untouched; `tests/api/test_cached_reads.py` compares the cached status with the CLI's uncached one after each write kind. Design 07 section 16.1 has the cache rules (no cache inside a transaction).

## 16. Article file names (2026-10-30, first-use report C12)
A tester read `connector-data-2.md` as broken. An article's path is `articles/<id>.md` and its id is `ids.article_id(doc slug, topic slug)` = `<doc slug>--<topic slug>` (per document: `<doc slug>`); `Manifest` validates exactly that, and the id is also what attach overrides, figure rails and agent proposals store. The fix is therefore in the topic slug, not in the export: since design 04 §3.4.1 the topic slug is made from the topic's shown title, with a section or page disambiguator where two topics of a document share a name (`pump-service-tables--connector-data-section-5.md`), never a bare `-2` and never a model's unrelated slug. `assemble` is unchanged.

The document slug stays in every name, not only when two documents share a topic name: it is part of the article id stored in overrides and proposals, so dropping it when unambiguous would rename an article (and orphan what points at it) the moment a second manual with the same topic arrives. It also tells a reader of the zip which manual the article came from. Stability: the same documents, selection, groups and config give the same names on every export (`assemble` is pure; grouping is deterministic); a re-group that renames a topic renames its file, as any title change does. Tests: `tests/export/test_assemble_names.py` (paths read as the title, no counter suffix, no model slug, stable across two exports).


## 17. One count of what waits for a person (2026-10-30, second first-use report C2, C6)
**What failed.** After Dana overrode every unflagged block, the rail ("Verify 105 to review"), the next-step card ("105 blocks still wait for review") and the Verify status strip ("105 waiting for you") all said 105 next to "105 overridden + 1 still blocking" (her shots 107 to 112). During scoring the next-step card said "60 blocks wait for you" while the Verify list said nothing was waiting yet (shot 048).

**Root cause.** Three sources answered "how many wait for you": the rail and the next-step card read `ExportStatus.queued` (`onboarding/StepNav.tsx` `stepStates`, `shell/nextStep.tsx` `defaultNextStep`), which `export_gate` counts as every queued in-scope block whether or not an override covers it (`gate.py` `queued_ids`, kept for the gate's `unlocked`); the Export screen's "N blocks still to review" read the same field; the Verify strip read `ReviewCounts.queued` and `pending` (`verify/StatusStrip.tsx`), status buckets that know nothing of overrides. Only the scope equation read the partition. During scoring, `defaultNextStep` ignored the running job, and its count came from an export status read at a different moment than the Verify queue (two polls, one document finished scoring between them).

**Rule: one partition, the gate's.**
- `ExportScopeCounts` gains `to_review` and `flagged`, which split `blocking` (`blocking == to_review + flagged`, `blocking` kept for older clients): a blocking block is `flagged` when an open flag on it is not covered (or its status is `flagged`), else `to_review`. So `in_scope == auto_approved + approved + edited + rejected + overridden + to_review + flagged`, each block counted once by `export_gate`.
- Words: "to review" / "waits for you" is `to_review` and nothing else; an override-covered block is "overridden (not reviewed)", never "to review"; on the export side "open flag" means an uncovered one (`flag_blockers`), while the Agent step keeps `open_flags` (a flag covered by an override is still open for the Agent).
- One client module, `shell/scopeTerms.ts`: `scopeTerms(status)` turns `ExportStatus.counts` into the terms every screen shows, and `reviewTerms(counts)` is the fallback from the Verify `ReviewCounts` (an older server, or the status not loaded yet; no override term). The rail, the next-step card, the Verify status strip (its stats, its bar and its equation, which gains "+ N overridden" when there are any) and the Export screen's reasons read it. The queue's `ReviewCounts` still drive the list (its length, the view filter).
- The Verify strip shows two reads, the gate's partition and the list's own counts (`scopeTerms.stripTerms`): the gate's terms when they agree bucket for bucket; after a write the gate has not seen yet (same scope), the list's buckets with the gate's overrides kept apart from those waiting; when the scope differs (a manual scored between the reads), the list's counts alone, so the strip never names blocks the list below does not have. The empty-list next step (`verify/Queue.tsx` `EmptyNext`) reads the partition too.
- A block being scored is not waiting: while a pipeline job is queued or running, the Verify next-step says the blocks are being scored and names no waiting count, as the rail's "scoring in progress" already did.
- The Verify step is done only with blocks in scope and none to review, flagged or overridden; with only overridden blocks left it reads "N overridden".

**Tests.** pytest `tests/export/test_flags_counts.py` (`assert_partition` checks the new split on every scenario; `test_overriding_every_unflagged_block_leaves_nothing_to_review`), `tests/export/test_synth.py` (gate counts). Vitest `src/shell/countsAgree.test.tsx`: rail, next-step card and status strip rendered from one fake status after the overrides, part way through, and during scoring, asserting they say the same numbers; `src/onboarding/stepStates.test.tsx` updated.

## 18. Overriding the rest in one decision (2026-10-30, second first-use report C3)
**What failed.** "Record 20 overrides" covered 20 blocks per click and emptied the reason box after each batch: six submits and six retyped reasons for one decision. From the second batch on it said "Record 19 overrides" under text about "the 20 blocks listed above".

**Where the 20 comes from.** `export/types.py` `BLOCKER_LIMIT = 20`: `ExportStatus.blockers` lists at most the first 20 blocker ids (P2, section 6). It is a server rule of the status, not of the override route: `POST /api/export/override` records one override per call and has no cap. The status is read after every approve, so it stays small. The Export form (`export/ExportScreen.tsx` `OverrideForm`) sent one override per listed unflagged blocker, so a click covered at most 20, and it cleared the reason on success.

**Decision.** The cap stays. The form becomes one decision: "Override the remaining N with this reason", N = `counts.to_review` (every unflagged blocker, not only the listed ones). One click runs successive rounds: override every listed blocker that has no uncovered flag in the latest status, then read the next page of blockers from the last answer (every override POST answers with the status), until no unflagged blocker is listed. A round that records nothing ends the run (a 422 on every listed block), so it cannot loop. The run never records more than the N the button named: a block that starts blocking during the run (a manual finished scoring) is left for a new decision and the screen says so ("1 more block started blocking during the run and is not covered"). When blocks are still to review at the end but none was listed (the first 20 blockers in reading order are all flagged), the screen says that too and points at the flag decisions, never "Recorded 0" alone. Progress is a `<progress>` and a status line ("Recorded 40 of 105"). The reason stays in the box after the run until the person clears it; each click gets a fresh run id, and request ids are `<run>:<block>` so a retry after a stop records nothing twice. A flagged block is never included: it is skipped when the latest status lists its flag, and the server refuses a block override on a flagged block (422, section 14) if one is flagged in between. The flag decisions keep their own box and reason.

**Cost of one click.** Each override is one POST. `record_override` checked its target by re-reading every document's review blocks (`load_review_blocks`), 154 ms per override on the e2e project (216 blockers: about 35 s for one click). It now takes the API's serving `ReviewService` (`record_override(..., review=)`) and checks the target against the cached overlays: under 5 ms per override including the status the route answers with. The CLI still reads uncached (one override per run). The refusals are unchanged; `tests/export/test_flags_counts.py::test_record_override_reads_the_serving_review_cache` pins both.

**Rejected.** A server "override every unflagged blocker" kind: it would be a blanket override that leaves flags out and covers blocks that start blocking later (P3), a change of what an override promises, for the owner to decide. Raising `BLOCKER_LIMIT`: the status poll would carry thousands of ids on a large project.

**Tests.** Vitest `src/export/ExportScreen.test.tsx` U10c (45 unflagged blockers listed 20 at a time plus a flagged one: one click records 45 overrides with one reason, never the flagged block, shows progress, keeps the reason) and U10d (a first page of flags only; a block that starts blocking during the run). Playwright `e2e/override-flow.spec.ts`: on a fresh scratch project every unflagged block is overridden by one click with one reason; the flagged block stays out; the rail, the next-step card and Verify say "overridden", never "to review"; the flag's own override unlocks the export.

## 19. The CLI stays in the docs
The flag sentence (`verify/labels.FLAG_RESOLUTION`, design 09 section 10) no longer mentions `labor export --override`: nobody using the screens has a command line, and the screens never record a blanket override. The CLI's blanket override is documented in README (CLI table) and in section 14. The Export screen's list of active overrides names a CLI one as "an override for everything".
