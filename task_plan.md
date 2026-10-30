# Task Plan: Build Manual Labor (doc → KB) through all 12 module gates

## Goal
Deliver Manual Labor v1 per SPEC.md: every CLAUDE.md module gate (0–11) passed with its proving command pasted in docs/PROGRESS.md, and SPEC §11 acceptance recorded in docs/ACCEPTANCE.md.

## Current Phase
M0–M13 passed and recorded in docs/PROGRESS.md; docs/ACCEPTANCE.md COMPLETE (live). Phase 13 (friendly, guided UI craft per docs/design/13-ui-craft.md) passed 2026-10-30.

## Phases
Detailed tasks, model assignments, and gates: docs/plans/2026-10-28-manual-labor-build.md. Decisions and environment: findings.md.

### Phase P: Plan
- [x] Read SPEC.md and CLAUDE.md; verify toolchain (uv, py3.12, node22, tesseract, ollama) and hardware (M3 16GB)
- [x] Record decisions in findings.md (synthetic fixtures by construction, MockProvider in M0, parser pair, model tiers)
- [x] Write docs/plans/2026-10-28-manual-labor-build.md with per-task model assignments and gates
- [x] User approved: run autonomously through all gates
- **Status:** complete

### Phase 0: Scaffold, contracts, fixtures, CI
- [x] git init + first commit (f79461f)
- [x] Design 00-contracts.md (Opus) · Scaffold (Haiku) · Contracts (Sonnet) ∥ Fixture generator (Sonnet) · Type-gen + CI (Haiku) · Review (Opus)
- [x] Fix review findings (Sonnet) → gate re-run → recorded in docs/PROGRESS.md
- [x] Gate: 163 passed; schemas + fixtures byte-stable; 5 PDFs + 1 DOCX + GT; npm test green
- **Status:** complete

### Phase 1: Ingest + dual parse + block model
- [x] Design (Opus) · Implement parsers/IDs (Sonnet) ∥ OCR/DOCX/tables (Sonnet) · Review (Opus) · Fix (Sonnet)
- [x] Gate: 274 passed; both parsers on all 6 fixtures; byte-identical re-parse; header/footer exact on 4; token F1 1.000 born-digital, 0.9665 scanned
- **Status:** complete

### Phase 2: Figure extraction
- [x] Design (Opus) · Implement (Sonnet) · Review (Sonnet) · Fix (Sonnet)
- [x] Gate: 14/14 native|vector; dedupe exact/near/cross-slug; 324 fast tests
- **Status:** complete

### Phase 3: Scoring + faithfulness check
- [x] Pre-req (user-agreed 2026-10-28): add a real scanned manual as 7th fixture (live-only, no checksum gate) — orchestrator picks a clearly public-domain US government/military technical manual, records the exact source URL + license in findings.md, and tells the user which before use and verify the RapidOCR adapter is not losing accuracy vs the raw engine; re-measure engine choice on it
- [x] Design (Opus) · Implement (Opus) · Review (Opus) · Fix
- [x] Gate: unit test per signal + combiner; seeded corruptions all < threshold; numeric blocks always queued
- **Status:** pending

### Phase 4: Grouping
- [x] Design (Opus) · Implement (Sonnet) · Review (Opus) · Fix (Sonnet)
- [x] Gate: 838 fast tests; partition exact both views; coverage exact; cohesion computed; byte-stable
- **Status:** complete

### Phase 5: Cleanup + figure attachment
- [x] Design (Opus) · Implement (Opus) · Review (Opus) · Fix (Opus)
- [x] Gate: 1042 fast tests; 0 violations on auto-approved; corrupting cleanup 100% rejected; caption_ref 23/23
- **Status:** complete

### Phase 6: Provider layer + hardware probe
- [x] Design (Sonnet) · Implement (Sonnet) · Review (Opus) · Fix (Sonnet)
- [x] Gate: 1220 fast tests; contract suite on all backends; live Ollama 12 passed; probe table on macOS
- **Status:** complete

### Phase 7: API + project state
- [x] Design (Opus) · Implement (Sonnet ×2) · Review (Opus, rejected) · Fix (Opus)
- [x] Gate: 178 tests; labor check K1–K16; R1–R6 byte-identical; every action persisted
- **Status:** complete

### Phase 8: UI Scope
- [x] Design (Sonnet) · Implement (Sonnet) · UX check (Sonnet) · Review (Opus) · Fix (Sonnet)
- [x] Gate: 98 vitest + 29 Playwright; toggle/counts/keyboard proven against the server
- **Status:** complete

### Phase 9: UI Verify
- [x] Design (Opus) · Implement (Sonnet) · UX check (Sonnet) · Review (Opus) · Fix (Sonnet ×3)
- [x] Gate: 216 vitest + 55/55 Playwright
- **Status:** complete

### Phase 10: Agent pass + calibration
- [x] Design (Opus) — include VLM (vision provider) as an optional third reader for flagged numeric blocks; it has no per-word confidence so it is never the primary OCR · Implement (Sonnet) · Review (Opus) · Fix
- [x] Gate: proposals re-checked and displayed with pass/fail; reject → queue with history; threshold suggestion from seeded decisions
- **Status:** pending

### Phase 11: Assemble + export + acceptance
- [x] Design (Sonnet) · [x] Implement (Sonnet) · [x] Review (Opus) · [x] Fix (M11.4, Opus) · [x] full-suite drift fixed (a14/f2/p6) · [x] acceptance run (live)
- [x] Gate: zip validates; every FIG resolves; README; SPEC §11 checklist in docs/ACCEPTANCE.md incl. offline `--live` run
- **Status:** complete

## Schedule change (user asked to speed up, 2026-10-29)
- Two tracks after M7: frontend (M8 → M9) ∥ backend (M10 → M11). Designs start while the previous module is in review. One Docling-bearing test run and one Playwright run at a time. M8.1 design started during M7 implementation.

## Cross-cutting (user, 2026-10-29)
- Self-improvement from HIL feedback: capture everything in M7's decision store (mandatory); learning hooks in M5 cleanup, M3/M10 calibration, M4 grouping, M10 agent pass (nice-to-have, never bypasses faithfulness). REQUIRED: immutable baseline, `learning.enabled` toggle, versioned learned layer with snapshots, reset + rollback, provenance of which snapshot produced each output, learned-vs-baseline comparison in calibration. See findings.md.

## Key Questions
1. Synthetic fixtures OK for gates? (assumed yes)
2. Strict module order despite M6 independence? (assumed yes, MockProvider from M0 unblocks M4/M5)
3. Docling as parser #2? (assumed yes; pdfplumber fallback)
4. Run autonomously after plan approval, or approve each design doc? (CLAUDE.md default: approve each design unless told otherwise)

## Decisions Made
See findings.md "Technical Decisions".

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| — | — | — |

## Notes
- Re-read this file and findings.md before each module's design dispatch.
- Log every gate command + output in docs/PROGRESS.md (CLAUDE.md requirement) and summarize in progress.md.

### Phase 12: Onboarding, tooltips, trust evidence, Agent + Export screens (user request 2026-10-29)
- [x] Design (Opus) · [x] Backend guide state (Sonnet) · [x] UI implement (Opus, Impeccable craft) · [x] UX check (Sonnet, first-time user) · [x] Review ×2 (Opus) · [x] Fixes (Opus)
- [x] Gate: 305 vitest, 75 Playwright, 1666 pytest, labor check K1–K16; recorded in docs/PROGRESS.md
- **Status:** complete

### Phase 13: Friendly, guided UI craft (user direction 2026-10-30; docs/design/13-ui-craft.md)
- [x] Impeccable audit + shape brief + 2 direction mocks (impeccable-ui-architect) · [x] Owner decisions D1–D8, D1a · [x] Backend card fields (Opus) · [ ] UI craft (impeccable-ui-architect, in flight) · [ ] UX check as first-time user · [ ] Fresh review · [ ] Gate
- **Status:** in_progress

