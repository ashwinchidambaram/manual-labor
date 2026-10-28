# Task Plan: Build Manual Labor (doc → KB) through all 12 module gates

## Goal
Deliver Manual Labor v1 per SPEC.md: every CLAUDE.md module gate (0–11) passed with its proving command pasted in docs/PROGRESS.md, and SPEC §11 acceptance recorded in docs/ACCEPTANCE.md.

## Current Phase
Phase 0 (scaffold, contracts, fixtures, CI). User approved autonomous run on 2026-10-28.

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
- [ ] Design 00-contracts.md (Opus) · Scaffold (Haiku) · Contracts (Sonnet) ∥ Fixture generator (Sonnet) · Type-gen + CI (Haiku) · Review (Opus) · Fix
- [ ] Gate: `uv run pytest -q`; `uv run labor schemas export`; 5 PDFs + 1 DOCX + ground truth; `npm test`
- **Status:** in_progress

### Phase 1: Ingest + dual parse + block model
- [ ] Design (Opus) · Implement parsers/IDs (Sonnet) ∥ OCR/DOCX/tables (Sonnet) · Review (Opus) · Fix
- [ ] Gate: both parsers on all fixtures; stable IDs across re-runs; headers/footers on ≥2 fixtures; GT token F1 ≥ 0.98
- **Status:** pending

### Phase 2: Figure extraction
- [ ] Design (Opus) · Implement (Sonnet) · Review (Sonnet) · Fix
- [ ] Gate: ≥95% native/vector on figures.pdf; phash dedupe across two copies
- **Status:** pending

### Phase 3: Scoring + faithfulness check
- [ ] Design (Opus) · Implement (Opus) · Review (Opus) · Fix
- [ ] Gate: unit test per signal + combiner; seeded corruptions all < threshold; numeric blocks always queued
- **Status:** pending

### Phase 4: Grouping
- [ ] Design (Opus) · Implement (Sonnet) · Review (Sonnet) · Fix
- [ ] Gate: every block assigned exactly once; coverage mapping correct; cohesion computed
- **Status:** pending

### Phase 5: Cleanup + figure attachment
- [ ] Design (Opus) · Implement (Opus) · Review (Opus) · Fix
- [ ] Gate: 0 faithfulness violations on auto-approved; attach rule recorded; caption-ref attachments correct
- **Status:** pending

### Phase 6: Provider layer + hardware probe
- [ ] Design (Sonnet) · Implement (Sonnet) · Review (Sonnet) · Fix
- [ ] Gate: same contract test passes for ollama/anthropic/openai-compatible; probe table on macOS; `--live` with local Ollama models
- **Status:** pending

### Phase 7: API + project state
- [ ] Design (Opus) · Implement (Sonnet ×2) · Review (Opus) · Fix
- [ ] Gate: `labor check ./tests/fixtures/project-a` passes; SIGKILL-resume test; every action persisted
- **Status:** pending

### Phase 8: UI Scope
- [ ] Design (Sonnet) · Implement (Sonnet) · UX check (Sonnet) · Review (Sonnet) · Fix
- [ ] Gate: Playwright: toggle preserves selection, counts live, keyboard nav
- **Status:** pending

### Phase 9: UI Verify
- [ ] Design (Opus) · Implement (Opus) · UX check (Sonnet) · Review (Sonnet) · Fix
- [ ] Gate: Playwright: 20 blocks keyboard-only; diff view correct; figure re-attach persists
- **Status:** pending

### Phase 10: Agent pass + calibration
- [ ] Design (Opus) · Implement (Sonnet) · Review (Opus) · Fix
- [ ] Gate: proposals re-checked and displayed with pass/fail; reject → queue with history; threshold suggestion from seeded decisions
- **Status:** pending

### Phase 11: Assemble + export + acceptance
- [ ] Design (Sonnet) · Implement (Sonnet, README Haiku) · Review (Opus) · Fix
- [ ] Gate: zip validates; every FIG resolves; README; SPEC §11 checklist in docs/ACCEPTANCE.md incl. offline `--live` run
- **Status:** pending

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
