# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `SPEC.md` first. It says *what*. This file says *how you work*.

## Where to start

- `docs/PROGRESS.md` is the source of truth for which build-order gate was last passed. If it does not exist, nothing has been built: start at module 0 (and `git init` first; the repo was created on 2026-10-28 with only `SPEC.md` and this file).
- `docs/design/<module>.md` must exist and be approved before that module's implementation starts.

## Operating principles

1. **Plan before code, per module.** The spec is high-level on purpose. For every module below, produce a short design (interfaces, data shapes, failure modes, test plan) before implementation, and get it approved unless told to run autonomously.
2. **Fresh context for focused work.** Use subagents for anything that benefits from a clean, full context window: designing a module, implementing it, reviewing it, or writing its tests. Do not let one long session accumulate stale assumptions. Pass each subagent exactly what it needs: the relevant spec sections, the contracts in `manuallabor/contracts/`, and the fixture paths — not the whole conversation.
3. **The implementer never grades its own work.** Every module gets a review from a subagent that did not write it, with a brief limited to: the spec section, the code, the tests, and the question "does this meet the acceptance criteria and the contracts?" Fix what it finds; re-review if the fix was non-trivial.
4. **Faithfulness is a hard invariant.** Any change to cleanup, scoring, or assembly must keep the faithfulness tests green. If a model-based step makes a test fail, the fix is to constrain or reject the model output, never to loosen the test.
5. **Deterministic core, probabilistic edges.** Parsing, IDs, scoring math, faithfulness alignment, assembly, export: pure functions with unit tests. LLM calls: behind one interface, temperature 0, cached by input hash, mockable in tests.
6. **Contracts are code.** The data shapes in SPEC §6 live as Pydantic models in `manuallabor/contracts/` and as JSON schemas exported from them. The frontend types are generated from those schemas. Change the model → regenerate → both sides move together.

## Repo layout (fixed — module 0 creates it, everyone else follows it)

- `manuallabor/` — the Python package: CLI `labor`, FastAPI app, pipeline stages. `manuallabor/contracts/` holds the Pydantic models for SPEC §6; `schemas/` holds the JSON schemas exported from them.
- `frontend/` — React + TypeScript + Vite app. Its types are generated from `schemas/`, never hand-written.
- `tests/` — pytest. `tests/fixtures/` holds the golden PDFs/DOCX, hand-written ground truth, and `project-a/` (the smoke-test project).
- `docs/design/`, `docs/PROGRESS.md`, `docs/ACCEPTANCE.md` — per-module designs, gate log, final checklist.

## Commands

Python (from repo root):

```
uv run pytest -q                                   # all unit + contract tests
uv run pytest tests/test_scoring.py::test_combiner -q   # one test
uv run pytest -q -k faithfulness                   # tests matching a keyword
uv run ruff check manuallabor/ && uv run ruff format --check manuallabor/
uv run mypy manuallabor/                           # strict mode is configured in pyproject
uv run labor check ./tests/fixtures/project-a      # end-to-end smoke, LLM mocked
uv run labor check --live ./tests/fixtures/project-a   # same with real local models; skips if none
uv run labor serve ./my-project                    # API + UI
```

Frontend (from `frontend/`): `npm test` (unit), `npm run e2e` (Playwright). The schema-export and type-generation commands are defined in module 0; whatever names it picks, record them in `docs/PROGRESS.md` and run both whenever a contract model changes.

## Build order (each is a milestone with its own verification gate)

| # | Module | Gate to pass before moving on |
|---|---|---|
| 0 | Repo scaffold, contracts, fixtures, CI | `uv run pytest` green; schemas exported; 5 fixture PDFs + 1 DOCX in `tests/fixtures/` with hand-written ground truth for a sample of blocks and all figures |
| 1 | Ingest + dual parse + block model | Both parsers run on every fixture; blocks have stable IDs across re-runs; headers/footers detected on ≥2 fixtures |
| 2 | Figure extraction | ≥95% native/vector on the figure-heavy fixture; phash dedupe works across two copies of the same file |
| 3 | Scoring + faithfulness check | Unit tests for every signal and the combiner; seeded corruptions (swap a digit, merge two columns, drop a table row) all land below threshold |
| 4 | Grouping (structure + topic views) | Every block assigned exactly once; coverage mapping between views is correct on all fixtures; cohesion computed |
| 5 | Cleanup + figure attachment | Faithfulness violations = 0 on auto-approved blocks; attach rule recorded; caption-ref attachments correct on fixtures |
| 6 | Provider layer + hardware probe | Ollama + Anthropic + OpenAI-compatible each pass the same contract test; probe returns a suggestion table on Linux/macOS |
| 7 | API + project state | Resumable: kill mid-run, restart, continue; every action persisted |
| 8 | UI: Scope | Toggle preserves selection; counts live; keyboard-navigable |
| 9 | UI: Verify | 20 blocks processed keyboard-only in a Playwright test; diff view correct; figure re-attach works |
| 10 | Agent pass + calibration | Proposals re-checked; rejected proposals return to queue with history; calibration suggests a threshold from seeded decisions |
| 11 | Assemble + export | Zip validates; every FIG reference resolves; README generated; SPEC §11 acceptance checklist run end-to-end and recorded in `docs/ACCEPTANCE.md` |

Do not start module N+1 until module N's gate is recorded as passed (a short note in `docs/PROGRESS.md` with the command that proves it).

## Subagent pattern (use this literally)

For each module:

1. **Design subagent** → writes `docs/design/<module>.md`: interfaces, data flow, edge cases, test list. Input: SPEC sections, contracts, prior designs it depends on.
2. **Implement subagent** → implements against the design, writes unit tests, runs them. Input: the design doc, contracts, fixtures. It reports what it could not satisfy rather than quietly changing the design.
3. **Review subagent** (fresh, has not seen 1 or 2's conversation) → reads design + code + tests, runs the gate, lists defects ranked by severity, and checks specifically for: faithfulness regressions, nondeterminism, contract drift, untested branches, model output used without validation.
4. **Fix** → implementer (or a new one) addresses the review. Re-run the gate. Record in `docs/PROGRESS.md`.

For the UI modules, add a **UX check subagent** that drives the app with Playwright against a fixture project and confirms the keyboard flows and the behaviors in SPEC §7.

## Verification you must run yourself, every time

- `uv run pytest -q` (unit + contract tests)
- `uv run labor check ./tests/fixtures/project-a` — an end-to-end smoke that parses, scores, auto-selects, assembles, and validates the export against the manifest schema, with LLM calls mocked
- `uv run labor check --live ./tests/fixtures/project-a` — same with real local models when available (skips cleanly if not)
- Frontend: `npm test` and `npm run e2e`

A gate is not passed because the code "should" work; it is passed because the command above ran and its output is pasted into `docs/PROGRESS.md`.

## Things that are easy to get wrong here

- **Treating a model's self-reported confidence as a signal.** Don't. Use disagreement between independent sources (two parsers, text layer vs OCR, a separate verifier model) and deterministic checks.
- **Letting cleanup "improve" the text.** Cleanup is lossless normalization. If a sentence reads better after the LLM touched it, that is a bug.
- **Silently dropping blocks.** Every block from the parse must end up assigned (to a group or `unassigned`) and accounted for in the manifest.
- **Figure IDs tied to array position.** IDs derive from doc slug + page + per-page index in reading order, computed once at parse. Re-parsing the same bytes must reproduce them.
- **Blocking the UI on LLM calls.** All model work is background jobs with progress; the review queue is usable while later blocks are still being scored.
- **Forgetting the scanned case.** Every feature must be exercised on the scanned fixture, not just the clean one.

## Conventions

- Python: ruff + mypy strict on `manuallabor/`; Pydantic v2; structured logging (one JSON line per LLM call).
- Frontend: TypeScript strict; components small; a single `hotkeys.ts` map; no global state library until it's needed.
- Commits: one module gate per PR-sized commit; message states the gate and the command that proved it.
- Docs: `docs/design/*.md` (per module), `docs/PROGRESS.md` (gates), `docs/ACCEPTANCE.md` (final checklist with evidence).
