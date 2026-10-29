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
