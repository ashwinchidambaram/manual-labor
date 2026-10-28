# Manual Labor — Build Plan

Date: 2026-10-28. Orchestrator: Fable 5.1 (this session). Subagents via the Agent tool with `model` set to `opus`, `sonnet`, or `haiku`. Ollama is not used for delegation; it is the project's live-model backend only.

Read with: `SPEC.md` (what), `CLAUDE.md` (how), `findings.md` (decisions + environment), `task_plan.md` (live status).

## 1. Operating rules (binding for every task below)

1. Modules run strictly in order 0 → 11. Module N+1 starts only after N's gate output is pasted into `docs/PROGRESS.md`.
2. Per module: **design** agent → orchestrator approves design → **implement** agent(s) → **review** agent (fresh, never the implementer) → **fix** agent (implementer or new) → orchestrator runs the gate. UI modules add a **UX-check** agent (Playwright).
3. Every subagent brief contains only: the goal, the exact SPEC sections, the paths to read (`docs/design/<m>.md`, `manuallabor/contracts/`, fixture paths), what to write, what to run, and the report format (≤300 words: what was done, what could not be satisfied, exact commands run with pass/fail). Never the conversation.
4. Implementers never change a design or loosen a test. They report what they could not satisfy. Faithfulness tests are never loosened; model output is constrained or rejected instead.
5. The orchestrator runs these itself at every gate: `uv run pytest -q`; from module 7 on, `uv run labor check ./tests/fixtures/project-a` and `--live`; from module 8 on, `cd frontend && npm test && npm run e2e`. Output is pasted into `docs/PROGRESS.md`.
6. One commit per passed gate. Message: `M<n>: <module> — gate: <command>`.

## 2. Model tier policy

| Role | Default | Escalate to Opus when |
|---|---|---|
| Design | Opus for modules 0 (contracts), 1, 2, 3, 4, 5, 7, 9, 10; Sonnet for 6, 8, 11 | — |
| Implement | Sonnet | Module is on the faithfulness path or has subtle alignment/state logic: 3, 5, 9 |
| Review | Sonnet | Faithfulness, determinism, or data-integrity risk: 0, 1, 3, 5, 7, 10, 11 |
| UX check | Sonnet | — |
| Mechanical (scaffold, CI, type-gen wiring, boilerplate, ruff/mypy cleanup, README template) | Haiku | Haiku output fails QA twice → Sonnet |

Escalation on failed review or failed gate: Haiku → Sonnet → Opus; re-dispatch with the original brief plus the reviewer's findings. Never re-run the identical failing brief.

Approximate dispatch count: ~48 agents across 12 modules (≈4 per module; modules 8–9 have 5).

## 3. Brief templates

**Design brief** (`model: opus|sonnet`): "Write `docs/design/<nn>-<module>.md` for module <n> of Manual Labor. Read `SPEC.md` §<x> and `CLAUDE.md` 'Operating principles' + 'Things that are easy to get wrong'. Read existing `docs/design/*.md` it depends on and `manuallabor/contracts/`. The design must contain: public interfaces (module paths, function signatures, Pydantic models used/added), data flow and on-disk artifacts, determinism guarantees, failure modes and how each is surfaced on the block, and a numbered test list where each test names its fixture and the assertion. Do not write code. Report: the test list and any contract changes you need."

**Implement brief** (`model: sonnet|opus`): "Implement module <n> exactly per `docs/design/<nn>-<module>.md`. Contracts live in `manuallabor/contracts/`; do not change them without reporting it. Fixtures: `tests/fixtures/` (ground truth in `tests/fixtures/ground_truth/`). Write the tests listed in the design under `tests/`. Run `uv run pytest -q tests/<module>` and `uv run ruff check manuallabor/ && uv run mypy manuallabor/` until green. Do not loosen any existing test. Report: files written, every command run with its result, anything in the design you could not satisfy and why."

**Review brief** (`model: opus|sonnet`, fresh): "Review module <n> of Manual Labor. Read `SPEC.md` §<x>, `docs/design/<nn>-<module>.md`, the code under `manuallabor/<pkg>/`, and `tests/<module>/`. Run `uv run pytest -q` and the gate command `<cmd>`. Answer: does this meet SPEC acceptance criteria and the contracts? List defects ranked by severity, each with file:line and a failing-case description. Check specifically: faithfulness regressions, nondeterminism (IDs, ordering, floating-point, dict order), contract drift, untested branches, model output used without validation, silently dropped blocks. Do not fix anything."

**UX-check brief** (`model: sonnet`): "Drive the running app at <url> against the fixture project `tests/fixtures/project-a` with Playwright. Verify each behavior in SPEC §7.<n> listed here: <list>. For each, write a Playwright test under `frontend/e2e/` that fails if the behavior is absent, run `npm run e2e`, and report pass/fail per behavior with screenshots saved to `frontend/e2e/artifacts/`."

## 4. Module tasks

Notation: **M<n>.<k>** · model · parallel? · depends-on. Gate = what the orchestrator runs and pastes.

### M0 — Repo scaffold, contracts, fixtures, CI
Gate: `uv run pytest -q` green; `uv run labor schemas export` writes `schemas/*.json`; `ls tests/fixtures` shows 5 PDFs + 1 DOCX + ground truth; `cd frontend && npm test` green.

- **M0.1** Orchestrator (direct): `git init`, `.gitignore`, first commit of SPEC/CLAUDE/plan files.
- **M0.2** Design · Opus · no · — : `docs/design/00-contracts.md`. All SPEC §6 shapes as Pydantic v2 models: `Document`, `Block` (incl. `signals`, `status`, `bbox`, `type` enum), `FigureRecord` (sidecar §6.3), `Group`/`Topic`, `ArticleFrontmatter` (§6.2), `Manifest`, `Flag`, `Decision` (calibration record §5.4), `Proposal` (§5.5), `ProjectConfig` (threshold, task→model map, article split), `LLMCallLog`. ID helper functions with the exact regexes from §6.1. `Provider` protocol (chat / vision / embed) + `MockProvider` spec + cache-by-input-hash spec. Deterministic JSON serialization rules (sorted keys, fixed float precision). Fixture generator design: the six fixtures from `findings.md` and the ground-truth JSON shape (per block: page, type, text, bbox; per figure: page, bbox, method expected, caption, duplicate-of).
- **M0.3** Scaffold · Haiku · yes · M0.1: `pyproject.toml` (uv, Python 3.12, deps: pydantic, fastapi, uvicorn, typer, pymupdf, docling, rapidocr-onnxruntime, python-docx, pillow, imagehash, cairosvg, litellm, sentence-transformers, reportlab; dev: pytest, pytest-cov, ruff, mypy strict, respx, hypothesis), `manuallabor/__init__.py`, `manuallabor/cli.py` (typer app with `schemas export`, `check`, `serve`, `ingest`, `parse`, `export` stubs that exit non-zero "not implemented"), `tests/conftest.py`, `frontend/` via Vite React+TS+Tailwind with Playwright and vitest configured, `frontend/src/hotkeys.ts` (empty map), `.github/workflows/ci.yml` (pytest + npm test), `docs/PROGRESS.md` skeleton. QA by orchestrator: `uv sync && uv run pytest -q && cd frontend && npm ci && npm test`.
- **M0.4** Contracts implement · Sonnet · yes (with M0.5) · M0.2, M0.3: `manuallabor/contracts/*.py`, `manuallabor/ids.py`, `manuallabor/providers/base.py` + `mock.py` + `cache.py`, `labor schemas export`, tests: SPEC §6.2 frontmatter and §6.3 sidecar examples round-trip; ID regex positive/negative cases; schema export is byte-stable across two runs; MockProvider is deterministic.
- **M0.5** Fixture generator · Sonnet · yes (with M0.4) · M0.2: `tests/fixtures/gen/make_fixtures.py` producing `clean.pdf`, `twocol.pdf`, `tables.pdf`, `figures.pdf`, `scanned.pdf`, `manual.docx`, plus `ground_truth/<name>.json`, and `tests/fixtures/project-a/` (a project folder referencing `clean.pdf` + `figures.pdf`). Deterministic: fixed seed, fixed creation/mod dates, test asserts sha256 of each file equals a committed value. Contents: real-manual-like prose with numeric specs (torque 35 N·m, M8, 12 V, part numbers), running headers/footers, "see Figure N" references, captions, a duplicated diagram across pages, two-column flow, tables with headers, one table with a merged cell.
- **M0.6** Type-gen + CI wiring · Haiku · no · M0.4: `frontend/package.json` script `gen-types` (json-schema-to-typescript over `schemas/`) → `frontend/src/types/generated.ts`; CI step that fails if generated types are stale.
- **M0.7** Review · Opus (fresh) · no · M0.4–M0.6: contracts vs SPEC §6 field-by-field; fixture ground truth spot-checked by opening the PDFs (PyMuPDF) and asserting a sample of texts/bboxes; determinism of IDs and schemas.
- **M0.8** Fix · Sonnet · no · M0.7. Then orchestrator runs the gate and records it.

### M1 — Ingest + dual parse + block model
Gate: tests show both parsers ran on all 5 PDFs + DOCX; parse twice → identical block ID lists and texts; headers/footers detected on `clean` and `twocol`; born-digital block text matches ground truth ≥ 0.98 token F1 per fixture; scanned fixture produces per-word OCR confidence on every block.

- **M1.1** Design · Opus: `docs/design/01-parse.md`. Ingest (sha256, type detection by text-layer coverage per page, metadata extraction with "inferred" flag via MockProvider-compatible call), `ParserAdapter` protocol, PyMuPDF and Docling adapters → `RawBlock`, reading-order algorithm (column detection), header/footer detection (repeat-across-pages with position tolerance; record stripped strings), block ID assignment (doc slug + page + per-page reading-order index, computed once), table cells + Markdown rendering with row/col counts from each parser, OCR adapter (RapidOCR with per-word confidence; Tesseract optional) incl. background OCR of born-digital renders, DOCX adapter, on-disk layout `project/<docslug>/parse/{pymupdf,docling,ocr}.json` + `blocks.json`. Test list with fixtures.
- **M1.2** Implement ingest + PDF adapters + reading order + IDs + header/footer · Sonnet · yes (with M1.3).
- **M1.3** Implement OCR adapter + DOCX adapter + tables · Sonnet · yes (with M1.2). Both follow the same design; the orchestrator merges and runs tests.
- **M1.4** Review · Opus (fresh): emphasis on ID stability, silently dropped blocks (every ground-truth block must have a parsed counterpart or an explicit `unparsed` record), nondeterministic ordering.
- **M1.5** Fix · Sonnet. Gate.

### M2 — Figure extraction
Gate: on `figures.pdf`, ≥95% of ground-truth figures extracted with method `native` or `vector`; phash dedupe test: `figures.pdf` ingested twice under two slugs → one image file, two references; every figure has a sidecar JSON validating against the schema.

- **M2.1** Design · Opus: `docs/design/02-figures.md`. Region → method decision (single xref image → native bytes at original resolution; vector drawing commands → clipped SVG + 300 DPI PNG; else 300 DPI crop with margin), phash (imagehash) dedupe across project, caption detection (nearest caption-type block below/above), figure ID assignment at parse time, DOCX native images, sidecar writing.
- **M2.2** Implement · Sonnet.
- **M2.3** Review · Sonnet (fresh).
- **M2.4** Fix · Sonnet. Gate.

### M3 — Scoring + faithfulness check
Gate: one unit test file per signal in SPEC §5.1 and for the combiner (`uv run pytest -q tests/scoring`); property test that combiner is pure and clamped; seeded-corruption tests (swap a digit, merge two columns, drop a table row, insert a word, delete a header string) each produce confidence < 0.85 and a logged violation; `has_numeric_spec` blocks are always queued regardless of score.

- **M3.1** Design · Opus: `docs/design/03-scoring.md`. Every signal's exact formula and inputs, critical vs soft classification, the combiner `min(critical) × geomean(soft)`, the faithfulness aligner (character-level alignment, allowed-edit classes, numeric multiset check, alignment ratio, diff attachment), the numeric-spec regex set, `llm_verifier` as optional signal via Provider with constrained output parsing, queue sorting.
- **M3.2** Implement · **Opus** (faithfulness path).
- **M3.3** Review · **Opus** (fresh).
- **M3.4** Fix · Opus. Gate.

### M4 — Grouping (structure + topic views)
Gate: on every fixture, every block appears in exactly one topic or `unassigned` (test asserts the partition); structure tree page ranges match ground truth; coverage mapping test: pick a topic, compute coverage per structure section, sum of covered blocks equals topic size; cohesion computed for every topic; all with MockProvider (deterministic).

- **M4.1** Design · Opus: `docs/design/04-grouping.md`. Structure view from heading tree; topic view = embed (Provider) → cluster (agglomerative/HDBSCAN, deterministic seeds) → LLM naming + straggler assignment with validated JSON output (reject/retry on invalid); cohesion = mean intra-cluster cosine; coverage mapping both directions; selection model (set of block IDs) persisted.
- **M4.2** Implement · Sonnet.
- **M4.3** Review · Sonnet (fresh).
- **M4.4** Fix · Sonnet. Gate.

### M5 — Cleanup + figure attachment
Gate: cleanup over all fixtures with MockProvider and with a deliberately corrupting mock → zero faithfulness violations on auto-approved blocks (violating outputs are rejected, raw text used, confidence floored); attach-rule tests: every "see Figure N" reference in ground truth attaches to the right article with rule `caption_ref`; caption-match and proximity cases recorded with their rule; VLM description stored and labelled `generated`.

- **M5.1** Design · Opus: `docs/design/05-cleanup.md`. Deterministic cleanup passes (dehyphenate, join wraps, strip header/footer remnants, normalize whitespace/bullets, table reconstruction) and the optional LLM pass, both gated by M3's faithfulness check; attachment rules in priority order with rule recording; caption/description via Provider vision with labelling.
- **M5.2** Implement · **Opus**.
- **M5.3** Review · **Opus** (fresh).
- **M5.4** Fix · Opus. Gate.

### M6 — Provider layer + hardware probe
Gate: one contract test parametrized over `ollama`, `anthropic`, `openai_compatible` backends (API ones via respx mocks; Ollama live when reachable, else skipped with reason); every call writes one JSON log line (task, model, tokens, latency, input hash); cache hit on identical input makes zero network calls; `uv run labor probe` prints a suggestion table on this macOS machine (sysctl path) and the code path for nvidia-smi/rocm-smi is unit-tested with canned output.

- **M6.1** Design · Sonnet: `docs/design/06-providers.md`. LiteLLM-backed implementation of the `Provider` protocol from M0; task→model config; cache; logging; probe (CPU/RAM/GPU/VRAM/disk) and suggestion table (small/medium/large per task + all-API); never auto-installs.
- **M6.2** Implement · Sonnet.
- **M6.3** Review · Sonnet (fresh).
- **M6.4** Fix · Sonnet. Gate, including `--live` with `gemma4:e4b-it-q4_K_M` and `nomic-embed-text` on this machine.

### M7 — API + project state
Gate: `uv run labor check ./tests/fixtures/project-a` passes end-to-end with mocks; resumability test spawns `labor parse` in a subprocess, SIGKILLs it mid-run, restarts, and asserts completion with no duplicated or missing blocks; every HIL action is a row in `project.db` and reopening resumes at the same queue position.

- **M7.1** Design · Opus: `docs/design/07-api-state.md`. FastAPI routes for the three screens (§7), background job runner with progress (never block the UI on LLM calls), SQLite schema (actions, decisions, jobs, flags, proposals, threshold history), stage outputs as files, `labor check` orchestration (parse → score → auto-select → clean → assemble → validate), OpenAPI → frontend client types.
- **M7.2** Implement · Sonnet (may split into state/jobs and routes/check as two parallel Sonnet agents).
- **M7.3** Review · **Opus** (fresh): data integrity, resumability, blocked UI.
- **M7.4** Fix · Sonnet. Gate.

### M8 — UI: Scope
Gate: Playwright test: toggle topics/structure preserves selection and shows coverage percentages; counts update live; full keyboard navigation; low-cohesion topics marked; `npm test && npm run e2e` green.

- **M8.1** Design · Sonnet: `docs/design/08-ui-scope.md` (components, state shape, hotkeys entries, API calls).
- **M8.2** Implement · Sonnet.
- **M8.3** UX check · Sonnet (Playwright, fresh).
- **M8.4** Review · Sonnet (fresh).
- **M8.5** Fix · Sonnet. Gate.

### M9 — UI: Verify
Gate: Playwright test processes 20 queued blocks keyboard-only (A/E/F/J/K); diff view shows exact raw↔clean diff; figure re-attach works and is persisted; state autosaves per action and survives reload.

- **M9.1** Design · Opus: `docs/design/09-ui-verify.md` (four panes, pdf.js rendering with block outlines and disagreement spans, queue sorting, edit/diff, figure rail, flag chips, autosave).
- **M9.2** Implement · **Opus** (may split pane work to Sonnet agents under the Opus design).
- **M9.3** UX check · Sonnet (fresh).
- **M9.4** Review · Sonnet (fresh).
- **M9.5** Fix · Sonnet. Gate.

### M10 — Agent pass + calibration
Gate: with MockProvider returning 5 proposals (one deliberately unfaithful), the agent pass displays all 5 with per-check pass/fail, the unfaithful one shown as failing; reject returns item to queue with proposal history attached; calibration computes edit rate per score bucket from seeded decisions and suggests a threshold without changing the active one.

- **M10.1** Design · Opus: `docs/design/10-agent-calibration.md`.
- **M10.2** Implement · Sonnet.
- **M10.3** Review · **Opus** (fresh): proposals re-checked through M3 before display; nothing hidden.
- **M10.4** Fix · Sonnet. Gate.

### M11 — Assemble + export
Gate: export zip for `project-a` validates against the manifest schema; every `FIG-` reference in every article resolves to a file and a sidecar; README generated; overrides listed; SPEC §11 checklist run end-to-end and recorded in `docs/ACCEPTANCE.md` with evidence (commands + output), including the fully-local `--live` run with network disabled.

- **M11.1** Design · Sonnet: `docs/design/11-export.md` (article assembly from approved blocks, frontmatter, inline figure refs with `FIG-ID — caption` alt text, manifest, README template, zip layout, validation).
- **M11.2** Implement · Sonnet. README template · Haiku.
- **M11.3** Review · **Opus** (fresh): faithfulness end-to-end (article text == cleaned approved block text, nothing added), manifest completeness (every block accounted for).
- **M11.4** Fix · Sonnet.
- **M11.5** Orchestrator: run SPEC §11 acceptance checklist 1–8, write `docs/ACCEPTANCE.md`, final commit.

## 5. Verification that is real, per gate

| Gate | Proof artifact |
|---|---|
| Unit/contract | `uv run pytest -q` output pasted in PROGRESS.md |
| Determinism | Tests that run the stage twice and compare serialized output byte-for-byte |
| Faithfulness | Corruption-seeding tests + a corrupting MockProvider that must be rejected |
| Resumability | Subprocess SIGKILL test |
| UI | Playwright tests committed under `frontend/e2e/`, run by `npm run e2e` |
| Live | `labor check --live` with the Ollama models on this machine; skip is recorded as skip, never as pass |
| Acceptance | `docs/ACCEPTANCE.md` with command + output per §11 item |

## 6. Risks and mitigations

- Docling install/parse time on an M3 with 16 GB: measure at M1.2; if `uv sync` > 10 min or parse of a 20-page fixture > 60 s, switch parser #2 to pdfplumber (adapter interface makes this a one-file change).
- gemma4 e4b may lack vision: M6 verifies; if absent, `--live` vision tasks skip with reason and the acceptance run records it.
- Synthetic fixtures may be "too clean": the scanned fixture adds skew + noise; corruption seeding covers the rest. A real manual is a follow-up, not a gate.
- Subagent context drift: every brief points at files, not prose; implementers report unmet items instead of improvising.
