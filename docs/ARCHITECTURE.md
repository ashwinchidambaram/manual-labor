# Architecture

The code map for anyone changing Manual Labor. [README.md](../README.md) says what the tool does; [SPEC.md](../SPEC.md) says what it must do; this file says where each part lives and how the parts connect. Line numbers drift; names do not, so search by name.

## 1. One picture

```
sources/*.pdf|docx
   │  ingest                      manuallabor/ingest.py
   ▼
docs/<slug>/document.json
   │  parse (PyMuPDF + Docling + OCR, merged)   manuallabor/parse/
   ▼
docs/<slug>/blocks.json  ──── rewritten only by a re-parse
   │  figures                     manuallabor/figures/
   │  score                       manuallabor/scoring/      → scores.json (overlay)
   │  group                       manuallabor/grouping/     → groups.json
   │  clean (+attach, describe)   manuallabor/cleanup/      → clean.json, attach.json, describe.json
   │  score2 (re-score clean text, faithfulness)             → scores.json
   ▼
project.db  (decisions, flags, proposals, selection, jobs)   manuallabor/state/
   │  agent pass / calibration    manuallabor/agent/, manuallabor/calibration/
   │  assemble + export           manuallabor/export/       → export/assembled/, <name>-kb.zip
   ▼
FastAPI  manuallabor/api/   ⇄   React UI  frontend/src/
```

The stage order and the per-stage output files are declared once, in `manuallabor/jobs/graph.py`. Everything that runs stages (CLI, serve, check) builds a plan from that graph.

## 2. Packages

| Package | Responsibility | Start reading |
|---|---|---|
| `manuallabor/contracts/` | Pydantic models for every data shape in SPEC §6: `Block`, `Document`, `FigureRecord`, `Group`, `Decision`, `Flag`, `Proposal`, `Manifest`, `ProjectConfig`, probe and LLM records, 21 enums | `block.py`, `config.py`, `enums.py` |
| `manuallabor/project.py` | `ProjectPaths` and `DocPaths`: the only place file locations are defined | `ProjectPaths` |
| `manuallabor/ingest.py` | Copies sources, assigns slugs, writes `document.json` with the source sha256 | |
| `manuallabor/parse/` | `pdf_pymupdf.py`, `pdf_docling.py` (models from `MANUALLABOR_DOCLING_ARTIFACTS`, else docling's own cache, else the HF hub cache; never downloads), `docx.py`, `ocr.py`, `headers.py` (headers and footers), `layout.py` (reading order, columns), `merge.py` (reconciles the two parsers into blocks with stable IDs), `render.py` (page PNGs) | `merge.py` |
| `manuallabor/figures/` | Native image extraction, vector-to-PNG, page crops as last resort, phash dedupe, caption pairing | `pipeline.py` |
| `manuallabor/scoring/` | One module per signal, `combine.py`, `faithfulness.py`, `pipeline.py` | `pipeline.py`, `combine.py` |
| `manuallabor/grouping/` | Structure view from headings; topic view from embeddings and clustering; model-named topics; cohesion | `pipeline.py` |
| `manuallabor/cleanup/` | Deterministic rules, optional residual LLM cleanup, figure attachment, figure description | `pipeline.py`, `rules.py` |
| `manuallabor/providers/` | One `Provider` protocol for chat, vision and embeddings; LiteLLM backends; mock; cache; call log; offline guard; hardware probe | `base.py`, `registry.py`, `probe.py` |
| `manuallabor/jobs/` | Stage graph, fresh/stale logic, plan executor, out-of-process worker, in-process runner | `graph.py`, `executor.py`, `runner.py` |
| `manuallabor/state/` | SQLite schema and migrations, store, projections to JSON files, learning store | `migrations.py`, `store.py` |
| `manuallabor/agent/` | Agent pass: one fresh model call per open flag, every proposal re-checked | `pipeline.py` |
| `manuallabor/calibration/` | Threshold suggestion from recorded decisions | |
| `manuallabor/export/` | Assemble the staging tree, write articles and sidecars, zip deterministically, validate | `assemble.py`, `validate.py` |
| `manuallabor/api/` | FastAPI app, routers, static UI serving, OpenAPI export | `app.py`, `routers/` |
| `manuallabor/cli.py`, `cli_serve.py`, `cli_agent.py` | Typer app. `serve` and `openapi` live in `cli_serve.py`; `agent` and `calibration` in `cli_agent.py` | |
| `manuallabor/check.py` | `labor check`: the end-to-end smoke on a temp copy | |

## 3. The project on disk

`ProjectPaths` in `manuallabor/project.py` resolves the paths below, except `.llm_cache/` and `probe.json`, which older code builds by hand. Add new paths to `ProjectPaths`.

| Path | Holds |
|---|---|
| `project.json` | `ProjectConfig`. Created with defaults by `ensure_config()` |
| `sources/` | Byte copies of ingested files |
| `docs/<slug>/` | Per-document stage outputs, see below |
| `figures/<slug>/FIG-*.{png,svg,json}`, `figures/index.json` | Figures and sidecars |
| `project.db` (+ `-wal`, `-shm`) | SQLite. Tables: `meta`, `blobs`, `actions`, `decisions`, `flags`, `proposals`, `selection`, `group_overrides`, `attach_overrides`, `figure_overrides`, `review_cursor`, `threshold_history`, `learning_snapshots`, `jobs` |
| `selection.json`, `agent/proposals.json` | Projections of DB tables for humans and scripts. The DB is the source of truth |
| `.labor.lock`, `.labor.worker.lock` | Project lock (serve and CLI) and job-worker lock |
| `logs/jobs/<id>.jsonl`, `<id>.plan.json` | Job progress log and the plan it ran |
| `llm_calls.jsonl` | One `LLMCallLog` line per model call |
| `.llm_cache/<sha256>.json` | Cached model responses |
| `learning/` | `active.json`, `snapshots/<id>/`, per-stage learned rules, `calibration.json` |
| `export/` | `assembled/` (the zip's exact layout), `state.json`, the zip |
| `probe.json` | Written by `labor probe --project` |

Inside `docs/<slug>/`: `document.json`, `blocks.json`, `scores.json`, `score_history.jsonl`, `groups.json`, `group_overrides.json`, `clean.json`, `attach.json`, `attach_overrides.json`, `describe.json`, `figures_report.json`, `figure_overrides.json`, `stages.json`, `pages/p###.png`, `pages_view/p###-<dpi>.png`, and `parse/` with one JSON per parser plus `ocr.json`, `layout.json`, `merge.json`.

`$MANUALLABOR_HOME` (default `~/.manuallabor`) holds the global learning and calibration store shared across projects.

## 4. Stages, freshness and jobs

**Graph.** `manuallabor/jobs/graph.py` fixes the node order `ingest, parse, figures, score, group, clean, score2, assemble, export` and, per node, the files whose presence means "ran". A node is one of `failed`, `missing`, `stale`, `fresh`, checked in that order:

1. `failed` if `stages.json` recorded a failure for it.
2. `missing` if its output files are absent.
3. `stale` if its stored fingerprint differs from the recomputed one (source bytes, threshold, learning layer, algorithm version constants), or an upstream node ran later (higher `seq`), or an upstream node is not fresh.
4. Otherwise `fresh`.

`stages.json` is `{counter, nodes: {node: {seq, status, fingerprint, error}}}`. No timestamps are used for freshness.

**Running.** `executor.py` turns "everything not fresh up to `--to`" into a plan and runs it node by node, updating `stages.json` after each. `inline.py` runs plans in-process for `labor run` and `labor check`. Under `labor serve`, `runner.py` (`JobRunner`) is the only writer of the `jobs` table; it spawns `python -m manuallabor.jobs.worker <root> <job>`, which takes `.labor.worker.lock`, reads the plan file and streams NDJSON progress to `logs/jobs/`. The worker has no DB access. On restart the runner adopts a live worker or marks a dead one `interrupted` and re-enqueues its plan. SIGTERM to the worker is a cancel request.

**Two rules that follow from this.** First, a job's start-up cleaner removes stray `*.tmp` files under `docs/`, `figures/` and `learning/`; anything written outside the worker lock (API page renders) must use another suffix, which is why `render_tmp_path` writes `.part`. Second, any new stage output file must be registered in `graph.py` or it will never be considered missing or stale.

## 5. Contracts and generated files

The Pydantic models in `manuallabor/contracts/` are the single definition of every shape. From them:

| Generated file | Command | Drift check |
|---|---|---|
| `schemas/*.json`, `schemas/_all.json` | `uv run labor schemas export` | `uv run labor schemas export --check` |
| `frontend/src/types/generated.ts` | `cd frontend && npm run gen-types` | `npm run check-types-fresh` |
| `frontend/src/api/openapi.json` | `uv run labor openapi export` | `uv run labor openapi export --check` |
| `frontend/src/api/types.ts` | `cd frontend && npm run gen-api` | `npm run check-api-fresh` |
| `docs/USER_GUIDE.md` | `cd frontend && npm run gen-guide` | a vitest fails when stale |
| `tests/fixtures/*` | `uv run python -m tests.fixtures.gen.make_fixtures --out tests/fixtures` | `... --check` against `CHECKSUMS.json` |

Never hand-edit a generated file. `frontend/src/api/schema.ts` is a hand-written set of aliases over `types.ts`; the rule there is "never hand-write a payload type".

## 6. Scoring and faithfulness

Signals live one per module in `manuallabor/scoring/`, named by `SignalName` in `contracts/enums.py`:

| Signal | Meaning |
|---|---|
| `ocr_mean`, `ocr_min` | Mean and minimum per-word OCR confidence |
| `textlayer_vs_ocr` | PDF text layer against OCR, token agreement |
| `parser_agreement` | PyMuPDF against Docling, digits weighted ×3 |
| `reading_order_risk` | Displacement, overlaps, multi-column pages |
| `table_consistency` | Shape agreement, ragged rows, header present |
| `garbage_ratio` | Token-shape rules and fragmentation |
| `faithfulness` | Deterministic diff of clean text against raw text |
| `figure_method`, `figure_resolution`, `figure_attach_rule` | Native 1.0, vector 0.95, crop 0.70; DPI; attach rule |
| `has_numeric_spec` | A rule, not a score: the block is always queued and the signal is excluded from the combiner |
| `llm_verifier` | Optional second-reader model; the config validator rejects one that equals the cleanup model |

`combine.py`: `min(critical) × geometric_mean(soft)`, clamped to [0, 1], rounded to 6 places, missing signals omitted. Each signal's producer decides whether its value is critical: `faithfulness` and `figure_method` always; `parser_agreement` and `textlayer_vs_ocr` when the block has a numeric spec or the value is below 0.8; `ocr_min` with a numeric spec; `table_consistency` when the cells disagree with the raw text. Learned rules (`learned.py`) can only queue a block or lower its confidence.

`faithfulness.py` allows exactly the edits AE1 to AE7 from design 03: whitespace, de-hyphenation, header and footer removal, bullet normalisation, glyph identity and NFC, table reconstruction, and reordering backed by another reading. Values: fail 0.0; pass after an evidence-backed reorder `FAITH_REORDER_VALUE` 0.9; cleanup candidate rejected and the deterministic result kept `FAITH_FALLBACK_VALUE` 0.5 (both in `scoring/types.py`). The UI treats anything that passed as passed and shows the value as a secondary line.

**Invariant.** A model-based step that makes a faithfulness test fail is fixed by constraining or rejecting the model output, never by loosening the test.

## 7. Providers

`providers/base.py` defines the `Provider` protocol (`chat`, `vision`, `embed`, `cache_namespace`) and `BaseProvider`, which adds caching, logging and output validation around every backend. `ProviderSet.get(task)` picks the model for a task from `ProjectConfig.models`. Backends in `registry.py`: `ollama`, `anthropic`, `openai`, `openai_compatible`, `vllm`, `llamacpp` (all via LiteLLM in `litellm_provider.py`). `mock` (deterministic, used by tests and `--mock`) is registered in `base.py` under `DEFAULT_FACTORIES`.

Cache key: sha256 of canonical JSON `{namespace, task, kind, inputs}`, stored under `.llm_cache/`. Every call appends an `LLMCallLog` (`contracts/llm.py`) to `llm_calls.jsonl`. `offline.py` blocks all sockets except the Ollama host when `MANUALLABOR_OFFLINE=1`; the acceptance script uses it as a negative control.

API keys come from the environment variable named in `ModelRef.api_key_env` or the provider default (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). `probe.py` and `probe_catalog.py` size the small, medium, large and api tiers from RAM, GPU and disk.

## 8. API

Routers in `manuallabor/api/routers/`, mounted in `api/app.py`:

| Prefix | Routes |
|---|---|
| `/api` project | `project`, `status`, `probe` (GET, POST), `config/threshold`, `config/apply-tier` |
| `/api` sources | `sources` (GET, POST), `docs/{slug}/source`, `docs/{slug}/pages/{page}.png`, `docs/{slug}/pages/{page}/blocks`, `docs/{slug}/figures` |
| `/api/scope` | `groups`, `blocks`, `selection` (GET, PUT), `summary`, `regroup`, `models`, `confirm` |
| `/api` verify | `verify/queue`, `verify/cursor` (GET, PUT), `verify/blocks/{id}`, `verify/actions` (POST: approve, edit, flag, skip), `flags`, `flags/{id}/resolve` |
| `/api` figures | `articles/{id}/figures`, `figures/{fid}/image`, `attach`, `detach`, `bbox` |
| `/api/jobs` | create, list, get, `{id}/log`, `{id}/cancel` |
| `/api/learning` | settings (GET, PUT), snapshots, activate, rollback, reset, disable item, publish; `decisions/export` |
| `/api` agent | `agent/run`, `agent/items`, `agent/proposals` (accept, edit, reject), `accept-all-passing`, `calibration`, `calibration/apply` |
| `/api/export` | `status`, POST `` (start an export job), `override`, `download` |
| `/api/ui` | `guide` (first-run state) |

The UI is served from the first of `$MANUALLABOR_FRONTEND_DIST`, `manuallabor/_frontend`, `frontend/dist`; `/assets` is static and a catch-all returns `index.html`. `labor serve` listens on 127.0.0.1:8765 by default; `--dev` serves the API only and expects Vite on 5173 proxying `/api`; `--mock` swaps every provider for the mock; exit code 3 means the project is locked.

Every count the UI reconciles (in scope = to review + auto-approved + done + flagged + rejected; blocks found = in topics + unplaced + headers and footers) is computed server-side and returned as separate fields. The UI only adds them up to check.

## 9. Frontend

`frontend/src/`, React 18, TypeScript strict, Vite 5, Tailwind 3.4, TanStack Query.

| Folder | What it holds |
|---|---|
| `router.tsx` | `/` redirects to `/scope`; `/scope`, `/verify`, `/agent`, `/export`, all inside `AppShell` |
| `shell/` | `AppShell`, step rail host, `JobsBar` (background job progress and cancel), `Help`, `Toast`, `ErrorBoundary`, `blockTitles.ts` (place titles for blocks) |
| `onboarding/` | `StepRail`, `WelcomeBand`, `Hint`, `guide.ts`, `hints.ts`, `userGuide.ts`. Not a route; embedded in the shell. The user guide is generated from here |
| `scope/` | Group tree, two views, selection engine, document count lines, confirm |
| `verify/` | Queue and cards, status strip (the progress bar), page strip, source pane, diff view, `WhyList` (evidence per signal), flag dialog, figure rail, edit |
| `agent/` | Agent run, proposal cards with re-check results, calibration |
| `export/` | Gate status, blocker list, override form, download with SHA-256 |
| `api/` | `openapi-fetch` client, `queries.ts` (every `useQuery` and `useMutation`), generated `types.ts` and `openapi.json`, hand-written `schema.ts` aliases |
| `hotkeys.ts` | The single key map. Every shortcut in the app and in the guide comes from here |
| `hooks/` | `useHotkeys`, `useJobsPolling`, `useSelectionEngine` |
| `assets/` | Atkinson Hyperlegible, bundled (no runtime network fonts) |

Design rules the components follow are in `DESIGN.md` (colour meaning: terracotta is your action, marigold is waiting for you, sage is cleared, brick is failed, blue is focus only) and the decisions in `docs/design/12-onboarding.md` and `docs/design/13-ui-craft.md`.

**Verify write path.** `useVerifyWrites` counts settled writes; the queue query records that counter when its request starts; `useVerifyState` discards a snapshot whose counter is older than the latest settled write and refetches instead. This is what keeps an approve from being undone by a refetch that left before it. Keep it when touching the queue.

**Tests.** vitest with jsdom and msw (`src/test/server.ts`; unhandled requests are errors). Playwright (`frontend/playwright.config.ts`): one worker, Chromium, three web servers: API in dev mode on 8765, Vite on 5173, and the built dist via `labor serve` on 8766. `scripts/e2e-project.sh` builds the fixture project into `frontend/e2e/.cache/project` (clean, figures and scanned PDFs through `score2` with mock models) and caches it by a hash of fixtures, scripts, every Python file and the algorithm-version constants. Each server gets its own temp copy. `UX_READER=1` enables the reader-pass screenshot spec.

## 10. Tests

`tests/` mirrors the packages: `agent`, `api`, `calibration`, `check`, `cleanup`, `contracts`, `export`, `figures`, `fixtures_gen`, `grouping`, `jobs`, `parse`, `providers` (with the shared `contract/` suite every backend must pass), `scoring`, `state`, plus `test_cli.py` and `test_ids.py`.

Markers (`pyproject.toml`): `slow` is deselected by default (`addopts` includes `-m 'not slow'` and a `--basetemp`); `live` needs `MANUALLABOR_LIVE=1`; `acc1`, `acc2`, `acc3`, `acc5` tag acceptance runs. Docling-dependent tests skip when its models are not cached unless `MANUALLABOR_REQUIRE_DOCLING=1`.

Fixtures are generated, not hand-drawn: `clean.pdf` (born-digital, Figure 3 placed before 1 and 2 to test caption-reference attachment), `twocol.pdf`, `tables.pdf`, `figures.pdf` (figure-heavy), `scanned.pdf` (image-only, rotated 0.5°), `manual.docx`, each with ground truth JSON. `tests/fixtures/project-a/` is the mock-provider smoke project used by `labor check` and the e2e build. Never run `labor serve` on it; it writes state into the fixture.

`scripts/acceptance.sh [--live]` runs SPEC §11 end to end into `build/acceptance/` and renders `docs/ACCEPTANCE.md`.

## 11. Where the reasons are

- `docs/design/00` to `11`: one design per pipeline module, including the alternatives rejected.
- `docs/design/03-scoring.md`: the allowed-edit list AE1 to AE7 and the critical-signal rule.
- `docs/design/12-onboarding.md` (guide, hints, trust evidence) and `13-ui-craft.md` (the redesign: decisions D1 to D8 and D1a, and the only assertion changes it was allowed to make).
- `docs/PROGRESS.md`: every gate, with pasted output. `docs/ACCEPTANCE.md`: the SPEC §11 checklist with evidence.
