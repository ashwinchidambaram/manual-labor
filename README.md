# Manual Labor

Turn equipment manuals (PDF, scanned PDF, DOCX) into a reviewed knowledge base that an AI agent can answer from, with a person checking only the parts the machine could not clear.

Everything runs on your machine. Parsing, scoring, the faithfulness check and assembly are deterministic code. Language models are used only for cleanup, topic names, figure descriptions and the optional agent pass, and every model output is re-checked by code before you see it. With local models configured, nothing leaves the laptop.

**Who it is for.** Technicians and documentation owners who are accountable if a torque value in the knowledge base is wrong. The tool is built so that a first-time user can sit down for an hour, review what needs a person, and export with a record of every decision.

## What you get

A zip containing:

- `articles/<id>.md`: one Markdown article per topic (or per document), with YAML frontmatter naming the source file, pages, sections, figures and review status.
- `images/<doc>/FIG-<doc>-p###-##.png` (plus `.svg` for vector art) and a JSON sidecar per figure with its caption, page, bounding box and how it was extracted.
- `manifest.json`: every document, article and figure, the review statistics, the models and threshold used, every override with its reason, and an accounting that proves every parsed block ended up in an article or in the unassigned list.
- `README.md` describing the layout.

IDs are stable and greppable: block `b-<doc>-p012-03`, figure `FIG-<doc>-p012-01`. Re-parsing the same file reproduces the same IDs.

## Requirements

- macOS or Linux, Python 3.12 (`uv` manages the environment), Node 22 for building the UI.
- Around 16 GB of RAM for the default local models. A machine without a GPU parses and scores a 200-page manual in a few minutes; the model steps take longer.
- Optional: [Ollama](https://ollama.com) for local models, or API keys for API models. The `api` tier needs both `ANTHROPIC_API_KEY` (chat, vision, verifier) and `OPENAI_API_KEY` (embeddings). Keys are read from the environment only, never stored in the project.
- Docling layout models, downloaded once (see Install). The parser never downloads at runtime.
- OCR: Tesseract is used when its binary is on `PATH`, otherwise the bundled RapidOCR. `ocr_engine` in `project.json` pins one.

## Install

```bash
git clone https://github.com/ashwinchidambaram/manual-labor.git
cd manual-labor
uv sync                                 # Python package + CLI `labor`
(cd frontend && npm ci && npm run build) # the UI, served by `labor serve`
uv run docling-tools models download    # once; layout models for the second parser (~/.cache/docling/models)
```

If you already have the Docling models somewhere else, point `MANUALLABOR_DOCLING_ARTIFACTS` at that directory.

Check that it all works end to end, with model calls mocked:

```bash
uv run labor check ./tests/fixtures/project-a
```

## Quick start

```bash
# 1. Bring your manuals in. This creates ./my-project and its project.json.
uv run labor ingest ./my-project ./manuals/*.pdf

# 2. Pick models for this machine. `probe` alone only prints a suggestion table
#    and the `ollama pull` commands for each tier; --apply writes the choice into project.json.
uv run labor probe
uv run labor probe --apply small --project ./my-project    # or medium, large, api

# 3. Parse, score and group. Resumable: a killed run continues where it stopped.
uv run labor run ./my-project

# 4. Open the app and review.
uv run labor serve ./my-project
```

Then open http://127.0.0.1:8765. The first run shows a short welcome that names your manuals and the four steps. Export from the app, or headless with `labor export ./my-project`.

Two things to know:

- `probe --apply` refuses a tier that does not fit your memory or disk (on a 16 GB machine `medium` needs `--force`). Pull the models it names before running without `--mock`.
- Alternatively skip steps 1 and 3 and add manuals through the app's "Add documents" button, which runs the pipeline as a background job. A project ingested from the CLI shows "Not run yet" with a Run button until step 3 has happened.

## The four screens

The app guides you through four steps. The same text is in the in-app guide and in [docs/USER_GUIDE.md](docs/USER_GUIDE.md), which also lists every keyboard shortcut.

1. **Scope** (`1`). Choose which blocks go into the knowledge base. Two views of the same blocks, suggested topics and document structure, so switching never changes your selection. Under each document a line adds up its blocks: found = in topics + unplaced + headers and footers left out. `G` confirms and starts scoring.
2. **Verify** (`2`). The queue lists only the blocks the checks could not clear, most doubtful first. Each card says what held it and shows the evidence: the two readings line by line, the least certain word, and the source page magnified directly above the text. `A` approves, `E` edits, `F` flags, `J` skips. Blocks with numbers, units or part numbers are always queued, because a language model cannot see an OCR mistake in a number. A progress bar shows in scope = to review + auto-approved + done + flagged + rejected, with every count coming from the server.
3. **Agent** (`3`). Hands your open flags to a model with your note. Each proposal is re-run through the same checks before you see it; accept is offered only when every check passed. Rejecting keeps the flag open with a record of what was tried. Calibration shows how often you edited blocks at each confidence level and suggests a threshold. It never changes the threshold for you.
4. **Export** (`4`). Unlocks when no flag is open and nothing in scope is waiting. While locked it lists exactly which blocks hold it, each with a link. You can override with a reason, and every override is written into the manifest. Download the zip and compare its SHA-256.

Everything works keyboard-only, at 200 percent zoom, and with a screen reader.

## How it decides what needs you

Confidence comes from disagreement between independent sources, never from a model rating itself.

- **Two parsers, always.** PyMuPDF and Docling both read every document. Where they disagree on a block, the block scores lower. Digits are weighted three times.
- **Text layer against OCR.** Every page is OCR'd, even born-digital ones, so a wrong character in the text layer shows up as a disagreement.
- **Deterministic checks.** Reading-order risk, table consistency, garbage ratio, OCR word confidence, figure extraction method.
- **An optional verifier model** that is required to be a different model from the one that did cleanup.
- **The faithfulness check.** Cleanup is lossless normalisation: whitespace, de-hyphenation, header and footer removal, bullet and ligature normalisation, table layout, and reordering only where another reading confirms the new order. Any other change to characters or numbers fails the check and the block is queued with the diff. If a sentence reads better after cleanup, that is a bug.

Signals combine as the minimum of the critical ones times the geometric mean of the rest. Blocks at or above the threshold (default 0.85) are auto-approved and shown with their evidence; the rest wait for you. A block with a numeric spec is queued regardless of score.

## Headless use

| Command | What it does |
|---|---|
| `labor probe [--apply TIER --project P]` | Inspect CPU, RAM, GPU and disk; suggest model tiers; optionally write them to an existing project's `project.json`. Never installs anything. |
| `labor ingest P FILES...` | Create the project if needed, copy sources in and register them. |
| `labor parse`, `figures`, `score`, `group`, `clean` | One stage at a time, with `--doc` and `--force`. `labor run` is the usual way. |
| `labor run P [--to STAGE] [--doc SLUG] [--mock]` | Run every stale stage up to `--to` (parse, figures, score, group, clean, score2). Resumable: a killed run continues where it stopped. |
| `labor status P [-v] [--json]` | Per-document stage states: fresh, stale, missing, failed. |
| `labor agent P` | Propose fixes for open flags. Proposals are accepted in the UI, never applied automatically. |
| `labor calibration P [--apply X]` | Suggest a threshold from your decisions; `--apply` records a new one for the next documents. |
| `labor export P [--override REASON]` | Assemble, zip and validate. Exits 2 while the review gate is locked. |
| `labor validate-export ZIP` | Validate any export against the manifest schema and figure-reference rules. |
| `labor check P [--live]` | End-to-end smoke test on a temporary copy of a project. |
| `labor serve P [--port N] [--mock] [--dev]` | API and UI. |

There are also `assemble`, `validate-export`, `learning` (snapshots, rollback, reset), `decisions export`, `schemas export` and `openapi export`. Run `uv run labor --help` and `uv run labor <command> --help` for every option.

## Inside a project folder

```
my-project/
  project.json        models, threshold, parsers, OCR settings (the only file you edit by hand)
  sources/            byte copies of what you ingested
  docs/<slug>/        per-document outputs: blocks.json, scores.json, groups.json, clean.json, pages/
  figures/<slug>/     FIG-*.png|svg + one JSON sidecar each; figures/index.json
  project.db          SQLite: every decision, flag, proposal, selection and job
  selection.json, agent/   human-readable copies of DB tables; the DB is the source of truth
  logs/jobs/          one NDJSON progress log per background job
  llm_calls.jsonl     one line per model call: task, model, tokens, latency, input hash, cached
  .llm_cache/         model responses keyed by input hash, so re-runs reuse them
  learning/           learned rules and calibration, with snapshots you can roll back
  export/             assembled/ staging tree, state.json, and the zip
  .labor.lock, .labor.worker.lock   held by `labor serve` / a CLI run, and by the job worker
```

Scores are an overlay. `blocks.json`, the raw parse, is never touched by later stages. Only a re-parse rewrites it (the source changed, `--force parse`, or `--allow-reparse`), and that is why `labor run` refuses to re-parse a document with recorded decisions unless you say `--discard-decisions`.

## Configuration

`labor ingest` creates `project.json` with defaults named after the directory (`labor run` and `labor export` do too; `labor probe` needs it to exist). The keys you are most likely to change:

- `models`: one `{provider, model, api_base, api_key_env}` per task: `cleanup`, `grouping`, `vision`, `embeddings`, `verifier`, and optionally `metadata` and `agent`. Providers: `ollama`, `anthropic`, `openai`, `openai_compatible`, `vllm`, `llamacpp`, `mock`. `labor probe --apply` fills this for you.
- `threshold` (0.85) and `doc_thresholds` to pin a value per document.
- `cleanup.llm`: `off`, `residual` (model only where the rules left something) or `always`.
- `ocr_engine` (`auto`, `rapidocr`, `tesseract`) and `ocr_dpi` (300 minimum).
- `learning.enabled`: whether your edits become rules for later blocks. Every rule is visible on the block it touched and can be disabled or reset.

Environment variables: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OLLAMA_HOST` (default `http://localhost:11434`), `MANUALLABOR_OFFLINE=1` to block every network call except the Ollama host, `MANUALLABOR_HOME` for the global learning store (default `~/.manuallabor`).

## Troubleshooting

- **"frontend not built"** at the root URL: run `npm run build` in `frontend/`, or point `MANUALLABOR_FRONTEND_DIST` at a built copy.
- **`labor serve` exits with code 3**: another `labor` process holds the project. Stop it, or wait; the lock file is `.labor.lock`.
- **Parse fails with "docling models not cached"**: run `uv run docling-tools models download` once, or set `MANUALLABOR_DOCLING_ARTIFACTS` to a directory that already holds them. The parser refuses to download at runtime unless `MANUALLABOR_ALLOW_MODEL_DOWNLOAD=1`.
- **A manual says "Not run yet"**: it was ingested from the CLI and the pipeline has not run. Press Run on the Scope screen, or stop `serve` and run `labor run`.
- **A stage shows stale**: the source file, the threshold or a learning layer changed since it ran. `labor run` recomputes only what is stale. `labor status -v` names the reason.
- **The agent pass proposes nothing usable**: the default 1B local model cannot follow the proposal schema. Set `models.agent` in `project.json` to a 7B-class local model (for example `qwen2.5:7b`) or an API model. `labor probe --apply` resets `models.agent` unless you pass `--keep-overrides`.

## Development

```bash
uv run pytest                                   # unit + contract tests (slow tests are deselected by default)
uv run ruff check manuallabor/ tests/ && uv run ruff format --check manuallabor/ tests/
uv run mypy manuallabor/                        # strict
cd frontend && npm test -- --run                # vitest
npx playwright install chromium                 # once
npm run e2e                                     # Playwright; builds a fixture project (needs the Docling models) and ports 5173, 8765, 8766
```

Contracts are code. Change a Pydantic model in `manuallabor/contracts/`, then regenerate the JSON schemas, the OpenAPI document and the TypeScript types so both sides move together. See [CLAUDE.md](CLAUDE.md) for the exact commands and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the code is laid out.

## Documents

- [SPEC.md](SPEC.md): what the product must do, and the acceptance criteria.
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md): the in-app guide, glossary and every shortcut.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the code map for anyone changing it.
- [docs/design/](docs/design/): one design document per module, with the decisions and their reasons.
- [docs/PROGRESS.md](docs/PROGRESS.md) and [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md): the gate each module passed, with the command output that proved it.
- [PRODUCT.md](PRODUCT.md) and [DESIGN.md](DESIGN.md): the product principles and the design system the UI follows.

## License

MIT. See [LICENSE](LICENSE). The bundled Atkinson Hyperlegible font is under the SIL Open Font License (see `frontend/src/assets`).
