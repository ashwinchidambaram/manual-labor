# Progress Log

## Session: 2026-10-28

### Phase P: Plan
- **Status:** complete
- **Started:** 2026-10-28
- Actions taken:
  - Read SPEC.md + CLAUDE.md; /init had already added header, layout, and commands to CLAUDE.md.
  - Verified toolchain: uv 0.11.7, Python 3.12.12, Node 22.22.1, tesseract 5.5.2, Ollama (nomic-embed-text, llama3.2:1b, gemma4:e4b). Hardware: Apple M3, 16 GB. Repo is not a git repo.
  - Wrote findings.md (requirements, environment, decisions, open questions).
  - Wrote docs/plans/2026-10-28-manual-labor-build.md (12 modules, ~48 subagent dispatches, model per task, gate per module, brief templates).
  - Wrote task_plan.md (phase tracker) and this file.
- Files created/modified:
  - CLAUDE.md (modified earlier this session), findings.md, task_plan.md, progress.md, docs/plans/2026-10-28-manual-labor-build.md (created), docs/design/ (empty dir)

### Phase 0: Scaffold, contracts, fixtures, CI
- **Status:** in_progress
- **Started:** 2026-10-28 14:25
- Actions taken:
  - git init, .gitignore, commit f79461f.
  - Dispatched M0.2 contracts design (Opus) and M0.3 scaffold (Haiku) in parallel.

## Test Results
| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| — | — | — | — | — |

## Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| — | — | — | — |

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase P complete; Phase 0 not started |
| Where am I going? | Phases 0–11 in strict order, each gated |
| What's the goal? | Manual Labor v1 with every gate proven in docs/PROGRESS.md and §11 in docs/ACCEPTANCE.md |
| What have I learned? | See findings.md |
| What have I done? | See above |
  - M0.3 scaffold done (Haiku), verified by orchestrator: ruff/mypy/pytest/npm green. Commit e366500.
  - M0.2 design approved (Opus, 474 lines, 57 tests listed, 16 SPEC ambiguities resolved in §10). Committed 5efd28c.
  - Dispatched M0.4 contracts implement (Sonnet) ∥ M0.5 fixture generator (Sonnet).
  - M0.4 contracts done (Sonnet): 82 tests, mypy clean, schemas byte-stable. Deviations noted: tags keep SPEC order; Proposal.all_checks_passed dropped on input; schemas_export is a re-export shim. Commit ffd2f8e.
  - Dispatched M0.6 type-gen + CI wiring (Haiku).
  - M0.6 type-gen done (Haiku): 50 types from schemas/_all.json, deterministic; CI freshness checks added. Commit 86215cb.
  - M0.5 fixtures done (Sonnet): 6 fixtures, GT, project-a, CHECKSUMS, determinism proven by double-generate diff. Orchestrator rendered 3 pages and confirmed layout features. Commit b69e0e7.
  - Dispatched M0.7 review (Opus, fresh).
  - M0.7 review (Opus): gate met (96 passed, mypy/ruff clean, schemas + fixtures + types stable). 5 majors: self-referential manifest accounting, vector figures overflow GT bbox, sidecar file under-validated, embed output unchecked, CI never run. 12 minors. Spot-checks: 328/328 blocks match PDF words in bbox; raster figure bboxes within 0.1pt.
  - Dispatched M0.8 fix (Sonnet) for items 1–14.
  - M0.8 fix done (Sonnet): 14/14 items, 163 tests. Orchestrator ran gate; recorded in docs/PROGRESS.md; commit M0.

### Phase 1: Ingest + dual parse + block model
- **Status:** in_progress
- **Started:** 2026-10-28
- Actions taken:
  - Dispatched M1.1 design (Opus) ∥ focused re-review of M0.8 contract changes (Sonnet).
  - M0 re-review (Sonnet): 4/5 fixes confirmed; 2 small manifest gaps (article/figure source_doc vs id slug) fixed inline by orchestrator + test c12b; mock digest closure caveat noted in design §10.22. Commit 6667766.
  - M1.1 design done (Opus, 373 lines, 31 tests, measured Docling/OCR). Orchestrator decision: OCR default 'auto' (tesseract if present else rapidocr). Commit d231ecd.
  - Dispatched M1.2 implementer A (Sonnet) ∥ M1.3 implementer B (Sonnet).
  - M1.3 implementer B done (Sonnet): tables/ocr/ocr_attach/textalign/docx + 32 tests; Tesseract F1 0.987 vs RapidOCR 0.905 on scanned p2; 6/6 tables exact in both parsers; 13/13 DOCX blocks. A still running.
  - M1.2 implementer A done (Sonnet): token F1 1.000 and exact header/footer on clean/twocol/tables/figures; scanned F1 0.9665, bbox-matched 0.50 (not gated); scanned 53.6 s, 200-page 172.7 s with 2 workers. Disk hit ~700 MB free; orchestrator pruned to 1.0 GB. Gate commands run by orchestrator (fast suite 256 passed, scanned slow 1 passed; 200-page slow test taken from A's run due to disk). Commit 2482501.
  - Dispatched M1.4 review (Opus, fresh).
  - M1.4 review (Opus): gate met, 0 blockers, 4 majors (Docling text order in merge, scanned headings fused into paragraphs, unvalidated LLM metadata, weak tests 8/13/14), minors (header_rows, image-only-page figure skips, title-page heading, worker RSS ~2 GB during RapidOCR). Determinism byte-identical across hash seeds; all candidates accounted once.
  - Dispatched M1.5 fix (Sonnet), failing-test-first on each item.
  - M1.5 fix done (Sonnet, after a disk-full interruption and brief re-send): FIX 1-5 done failing-first; FIX 6 (RapidOCR downscale) measured 1.64→1.47 GB only, reverted. Gate run by orchestrator and recorded; M1 committed.

### Phase 2: Figure extraction
- **Status:** in_progress
- **Started:** 2026-10-28
- Actions taken:
  - Dispatched M2.1 design (Opus) ∥ focused re-review of M1.5 merge/OCR/classify changes (Sonnet).
  - M1 re-review (Sonnet): 5 small defects (order_by_parser min, column-aware piece sort, OCR bullet glyphs ¢/+, cover-page heading rule, Docling header_rows cap); merge order, heading recall 18/18, metadata validation confirmed. Dispatched M1.6 fix (Sonnet) in parallel with M2.1 design.
  - M2.1 design done (Opus, 323 lines, 22 tests): isolated-page SVG export, lossless JPEG→PNG, phash-64 near-dup threshold 8 (measured 0/2–6/10/12+), figures/<slug>/ layout, canonical = best method then area. Found module-1 fused caption on scanned p6 → added to M1.6 fixer. Commit 772b9c0.
  - M1.6 fix done (Sonnet): 6/6 failing-first; scanned lists 8/8, captions own blocks. Full fast suite 280 passed; commit 87cbd81. Disk now 19 GB free (user cleared).
  - Dispatched M2.2 implement (Sonnet).
  - M2.2 implement done (Sonnet): 14/14 methods match GT, dedupe exact+near+cross-slug, SVGs 2.5-3.3 KB, byte-identical across processes; 37 tests. Commit 2b99ca0. Dispatched M2.3 review (Sonnet, fresh).
  - M2.3 review (Sonnet): gate PASS (14/14, dedupe across copies, native sha == GT, byte-identical across hash seeds). 1 major (off-page bbox crashes doc instead of per-figure failure), minors (stale files, near-dup sidecar width/height, --force keeps confidence, zero-area bbox). Dispatched M2.4 fix (Sonnet).
  - M2.4 fix done (Sonnet): 6/6; 44 figure tests. Gate run by orchestrator; M2 recorded + committed.

### Phase 3: Scoring + faithfulness
- **Status:** in_progress
- **Started:** 2026-10-28
- Actions taken:
  - Dispatched M3.1 design (Opus) ∥ real scanned manual fixture acquisition (Sonnet, archive.org public-domain US Army TM, live-only, gitignored with fetch script).
  - Real fixture acquired (Sonnet): TM 5-3895-332-12 pile driver manual, 64 p, image-only 300 DPI build, fetch.py + README + 20-block GT sample; orchestrator viewed p8. Commit 2435a43.
  - M3.1 design done (Opus, 408 lines, 24 tests, prototype recall 24/24 on scanned). Decisions recorded in findings.md. Commit 41ecc83. Dispatched M3.2 implement (Opus).
  - M3.2 implement done (Opus): 201 scoring tests, fast suite 525; H1-H9 all ≤0.5, legit edits ≥0.854; corrupting mock rejected 436/436; scanned recall 1.000; real manual numeric recall 1.000 (metric rewritten after first run 0.643 — flagged for review); review load 47–72% (flagged: numeric-spec rule breadth); 1,000 blocks 1.18 s. Commit c580dc7. Dispatched M3.3 review (Opus, fresh).
  - M3.3 review (Opus): GATE NOT PASSED. Blocker: line reorder accepted on 2-column layout evidence alone (reordered steps auto-approved). Majors: hf_key digit-masked header removal deletes numeric body lines; real-manual test loosened (figure-swallowed paragraph counted as caught; true recall 0.714 = silent drop in module 1/2); numeric-spec lexicon misses volts/inches/pounds/P.S.I./tons/gallons/qts. Minors: rule false positives ('in', 1970s, A-1, OCR garbage); verifier NONE can raise score over threshold; weak verifier spans accepted. Confirmed: combiner 20k random cases exact; byte-identical across seeds; 12 aligner cases correct.
  - Dispatched M3.4 fix (Opus): reorder needs independent-reader evidence; exact/page-templated header removal only; strict real metric + module-1 fix for OCR text inside figure regions; unit lexicon; verifier never raises.
  - 2026-10-29: user proposed 3–4 more real manuals; orchestrator agreed (variety by layout class) and dispatched acquisition (Sonnet) in parallel with the M3.4 fix.
  - 2026-10-29: caffeinate -i -s started (PID 54839) at user request; private GitHub repo manual-labor created and main pushed (16 commits).
  - 4 more real fixtures acquired (Sonnet) and committed (scripts/GT only). M3.4 fix still running.
  - M3.4 fix done (Opus): 7/7 failing-first; real recall 16/16; precision 0.47→0.93. Gate run by orchestrator (665 fast, 337 scoring); recorded; pushed.

### Phase 4: Grouping
- **Status:** in_progress
- **Started:** 2026-10-29
- Actions taken:
  - Dispatched M3 fix re-review (Opus) ∥ M4.1 design (Opus).
  - M4.1 design done (Opus, 276 lines, 36 tests; centered-embedding clustering measured). Dispatched M4.2 implement (Sonnet); M3 re-review still running.
  - M3 re-review (Opus): all claimed fixes hold under attack; 1 medium-high hole (NumericVariant accepted ±1 token → 35→40 could pass) + 5 lows (page-number any-slot, reorder substring evidence, verifier drops 2-char numeric spans, unit gaps 5V/#10-32/1/4-20, figure labels released as paragraphs). Dispatched M3.5 fix (Opus) ∥ M4.2 implement (Sonnet, running).
  - M3.5 fix done (Opus): 6/6 failing-first; 519 scoring+parse green; committed cc4db44. M4.2 still running.
  - Disk-full incident (Docker installer temp, 8.6 GB) blocked all tools 00:30–02:15; recovered via cron retry. M4.2 implement done (Sonnet): 84 grouping tests, fast suite 814, live nomic clean 11 topics / twocol 10, cohesion 0.27–0.68. Gate commands green; committed 24fbc42. Dispatched M4.3 review (Opus, fresh).
  - M4.3 review (Opus): gate PASS (partition exact on 6 fixtures both views; structure tree 0 mismatches vs GT; coverage exact; byte-identical across seeds/cwd/cold cache; LLM output validation rejects all 7 bad cases). 1 major dormant (do-not-merge pairs re-merged by straggler/binding), minors (no subtree-select op needed by M8; 60-cap not re-applied after stragglers; test 13 mismatch; contracts doc; untested branches). Dispatched M4.4 fix (Sonnet).
  - 04:3x: third disk-full; removed stale com.docker.install (8.6 GB, no holders). Resuming M4 gate.
  - M4.4 fix done (Sonnet): 7/7; 106 grouping tests. Gate run by orchestrator (838 fast); M4 recorded + pushed.

### Phase 5: Cleanup + figure attachment
- **Status:** in_progress
- **Started:** 2026-10-29
- Actions taken:
  - Dispatched M5.1 design (Opus).
  - Detached 3 stale Docker installer mounts; disk 11 GB free. M4 recorded (059c2c9). M5.1 design (Opus) running.
  - M5.1 design done (Opus, 343 lines, 40 tests; measured dehyphenate+join = GT 192/192). Dispatched M5.2 implement (Opus).
  - 05:2x: 4th disk-full, caused by tests/cleanup copying whole projects ~15×/run. pytest basetemp moved to .pytest_tmp (wiped per run). Ollama now lists only nomic-embed-text (gemma4/llama3.2 gone) — live LLM tests need a model pulled later. Dispatched M5.4a test-footprint + failures fix (Sonnet).
  - M5.2 implement done (Opus): 158 cleanup tests; corrupting mock 100% rejected on 6 fixtures × 4 modes; scanned auto-approved violations 0; caption_ref 23/23 GT refs; GT text clean 124/125 (fixed), twocol 82/82, tables 69/69, figures 65/65. M5.4a (Sonnet): footprint 2.1→0.68 GB cleanup / 1.7 GB full; 3 failures fixed; docs updated. Fast suite 996. Commit 0beebed. Dispatched M5.3 review (Opus, fresh).
  - M5.3 review (Opus): gate passes on reviewer's own run (0 auto-approved faithfulness failures / 0 numeric diffs across 6 fixtures × 3 LLM modes × corrupting modes). 3 majors: header string deleted mid-sentence auto-approved; table clean text never compared to raw_text (row drop at 1.0); 'Figure 1 to 2 mm' parsed as range. Minors: LLM bullet set wider than deterministic; LLM whitespace inside part numbers; stale clean.json detection by id only; invalid learned rule drops snapshot; residual trigger untested. Dispatched M5.4 fix (Opus).
  - M5.4 fix done (Opus): 9/9; 204 cleanup tests. Gate run by orchestrator (1042 fast); M5 recorded + pushed.

### Phase 6: Provider layer + hardware probe
- **Status:** in_progress
- **Started:** 2026-10-29
- Actions taken:
  - Dispatched M6.1 design (Sonnet).
  - M6.1 design done (Sonnet, 227 lines, T1–T15). Defaults flipped to small tier. Pulling llama3.2:1b + moondream in background. Dispatched M6.2 implement (Sonnet).
