# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Manual Labor turns manuals (PDF, scanned PDF, DOCX) into a reviewed knowledge base with a human in the loop. `README.md` says what it does for a person. `SPEC.md` says what it must do. `docs/ARCHITECTURE.md` says where the code is and how the parts connect. This file says how to work on it.

## State of the build

Every module in the build order below is complete, gated and recorded in `docs/PROGRESS.md` (M0 to M11 the spec build, M12 onboarding and trust evidence, M13 the UI redesign). `docs/ACCEPTANCE.md` records the SPEC §11 acceptance run as COMPLETE on live local models. New work is a change to a finished product, not a continuation of the build: design it, implement it against the design, have it reviewed by a fresh agent, run the gate, record it.

Open follow-ups the owner has not decided on (do not start them unasked):

- Additive server fields: per-section blocker counts on `/api/export/status` and per-document queued counts in `/api/verify/queue` `docs[]`, for quiet milestones in the UI.
- The agent task's default local model (`llama3.2:1b`) cannot follow the proposal schema. Per project, set `models.agent` to a 7B-class model or an API model (`labor probe --apply medium` is refused on a 16 GB machine without `--force`, and `--apply` resets `models.agent` unless `--keep-overrides`). A better default is still undecided.
- Parsed-fixture caching to shorten the full pytest run (15 to 19 minutes) and Playwright (about 6 minutes).

## Invariants (never trade these away)

1. **Faithfulness is hard.** Cleanup is lossless normalisation (the allowed edits AE1 to AE7 in `docs/design/03-scoring.md`). If a model-based step makes a faithfulness test fail, constrain or reject the model output. Never loosen the test. If a sentence reads better after cleanup, that is a bug.
2. **The model never rates itself.** Confidence comes from disagreement between independent sources (two parsers, text layer against OCR, a separate verifier model) and deterministic checks. A model's self-reported confidence is not a signal.
3. **Nothing is dropped silently.** Every parsed block ends up in a group or in `unassigned`, and the manifest's `accounting` proves it. Every count the UI shows reconciles against separately computed server counts.
4. **Deterministic core, probabilistic edges.** Parsing, IDs, scoring, faithfulness, assembly and export are pure functions with unit tests. Model calls go through one `Provider` interface at temperature 0, cached by input hash, mockable with `--mock`.
5. **Contracts are code.** Shapes live as Pydantic models in `manuallabor/contracts/`. Change the model, regenerate schemas, OpenAPI and TypeScript, commit all of it together. Never hand-edit a generated file (list in `docs/ARCHITECTURE.md` §5).
6. **Fully local.** No runtime network calls except to configured model providers. Fonts are bundled. API keys come from environment variables only and are never written into a project.
7. **IDs are stable.** Block and figure IDs derive from document slug, page and per-page index in reading order, computed once at parse. Re-parsing the same bytes reproduces them.
8. **Model output is validated before use.** Cleaned text and agent proposals pass the same deterministic checks as everything else; a failed re-check is shown, not hidden.

## Commands

Python, from the repo root:

```
uv run pytest                                          # unit + contract tests; slow tests deselected by default
uv run pytest tests/scoring/test_combine.py -q         # one file
uv run pytest -q -k faithfulness                       # by keyword
uv run pytest -q -m slow                               # the slow (Docling/OCR) tests
uv run ruff check manuallabor/ tests/ && uv run ruff format --check manuallabor/ tests/
uv run mypy manuallabor/                               # strict
uv run labor schemas export --check                    # JSON schemas match the contracts
uv run labor openapi export --check                    # frontend/src/api/openapi.json matches the app
uv run labor check ./tests/fixtures/project-a          # end-to-end smoke, models mocked
uv run labor check --live ./tests/fixtures/project-a   # same with real local models; skips cleanly if none
MANUALLABOR_REQUIRE_DOCLING=1 bash scripts/acceptance.sh --live   # full SPEC §11 acceptance, ~95 min
```

Frontend, from `frontend/`:

```
npm run typecheck && npm test -- --run                 # tsc, vitest
npm run gen-types && npm run gen-api && npm run gen-guide   # after a contract, route or guide-text change
npm run check-types-fresh && npm run check-api-fresh   # drift checks
npm run build                                          # dist served by `labor serve`
npx playwright install chromium                        # once per machine
npm run e2e                                            # Playwright; builds the fixture project on first run; needs ports 5173, 8765, 8766
```

Codegen order after a contract change: `uv run labor schemas export`, `uv run labor openapi export`, then `npm run gen-types` and `npm run gen-api`. After editing `frontend/src/onboarding/*.ts` or `hotkeys.ts`, run `npm run gen-guide`; a vitest fails while `docs/USER_GUIDE.md` is stale.

Run the app on a scratch copy, never on a fixture:

```
bash scripts/e2e-project.sh                            # builds frontend/e2e/.cache/project (cached; e2e does this too)
mkdir -p build && rm -rf build/demo-project && cp -R frontend/e2e/.cache/project build/demo-project
uv run labor serve build/demo-project --mock --port 8780
curl -X PUT localhost:8780/api/ui/guide -H 'content-type: application/json' -d '{"seen":false}'   # first-run state
```

`labor serve ./tests/fixtures/project-a` writes state into the fixture. Do not do it.

## How to make a change

1. **Read the design for the module you are touching** in `docs/design/`. It records the alternatives that were rejected and why. If the change contradicts a decision there, say so and update the design in the same commit.
2. **Design before code** for anything beyond a small fix: a short section appended to the module's design (interfaces, data shapes, failure modes, test list). The owner approves it unless told to run autonomously.
3. **Failing test first.** For a bug, reproduce it with a test that fails, then fix. For a feature, write the tests from the design. A "flaky" test is a hypothesis, not a diagnosis: read the assertion message, the server lines in the e2e log and the Playwright trace's network bodies, then rerun alone three times. Three of three flakes in this repo were real races.
4. **Fresh reviewer.** The implementer never grades its own work. A subagent that has not seen the implementation conversation reads the design, the code and the tests, runs the gate, and checks specifically for faithfulness regressions, nondeterminism, contract drift, untested branches and model output used without validation. Fix what it finds; re-review a non-trivial fix. For UI changes add a UX-check agent that drives the app with Playwright as a first-time user and asserts through the API as well as the screen.
5. **Run the gate yourself** and paste the output into `docs/PROGRESS.md`. A gate passes because the command ran, not because the code should work.
6. **Commit** one gate per commit; the message states the gate and the command that proved it.

## Working with subagents here

- Give each agent exactly what it needs: the spec section, the design, the contracts, the fixture paths. Not the conversation.
- Reviewers run in a git worktree of HEAD so an in-progress edit cannot change what they see.
- Resource cap on a 16 GB machine: at most two Docling-bearing pytest runs plus one Playwright run at a time, each with its own `--basetemp=.pytest_tmp_<name>`. A shared temp dir wiped by a concurrent run invalidates a gate silently. Keep more than 3 GB of disk free; `.pytest_tmp_*` dirs are safe to delete when no run is active.
- Never kill a process that belongs to another Claude session.

## Things that are easy to get wrong

- **Writing a path by hand.** Project paths come from `ProjectPaths` / `DocPaths` in `manuallabor/project.py`; add new ones there (two older exceptions remain, `.llm_cache/` and `probe.json`). A new stage output must also be registered in `manuallabor/jobs/graph.py` or it will never be seen as missing or stale.
- **Temp files under `docs/`, `figures/` or `learning/`.** A job's start-up cleaner deletes stray `*.tmp` in all three. Writers outside the worker lock (API page renders) use `.part`, one unique name per call. A temp-file fix has two halves: the writer's unique name and every cleaner whose glob could match it.
- **Counting before the data is there.** The Scope summary is recomputed on the client from the block index; a click that lands before the index loads is recounted when it arrives (`useSelectionEngine`). Keep that effect when touching the engine.
- **Claiming work is happening.** "Processing" is only shown while a job runs. A stage that has never run says "Not run yet" with a Run button (a CLI-ingested project arrives like that).
- **Applying a stale queue snapshot after a write.** The Verify queue discards any response that started before the latest settled write (`useVerifyWrites` / `useVerifyState`). Keep that when touching the queue or approve path.
- **Treating `faithfulness` below 1.0 as failed.** 0.9 is a pass via evidence-backed reorder and 0.5 is "cleanup candidate rejected, deterministic result kept". Failed is `passed == false`.
- **Blocking the UI on model calls.** All model work is a background job with progress; the review queue stays usable while later blocks are still scoring.
- **Forgetting the scanned case.** Exercise every feature on `scanned.pdf`, not just `clean.pdf`.
- **Figure IDs from array position.** See invariant 7.
- **Colour as the only signal, or a verdict without its evidence.** The UI rules are in `PRODUCT.md` and `DESIGN.md`: terracotta is your action, marigold is waiting for you, sage is cleared, brick is failed, blue is focus only; every count reconciles on screen; every explanation sits where the decision is; works keyboard-only and at 200 percent zoom.

## Repo layout

- `manuallabor/`: the Python package, CLI `labor`, FastAPI app, pipeline stages. `contracts/` holds the Pydantic models; `schemas/` at the root holds the JSON exported from them.
- `frontend/`: React + TypeScript + Vite. `src/types/generated.ts` and `src/api/types.ts` are generated.
- `tests/`: pytest, mirroring the package. `tests/fixtures/` holds generated golden PDFs and DOCX with ground truth, and `project-a/` for the smoke test.
- `scripts/`: `acceptance.sh`, `e2e-project.sh`, `e2e-serve.sh`, helpers.
- `docs/design/`: one design per module. `docs/PROGRESS.md`: gates. `docs/ACCEPTANCE.md`: final checklist with evidence. `docs/USER_GUIDE.md`: generated.
- `task_plan.md`, `progress.md`, `findings.md`, `docs/plans/`: the planning files from the autonomous build. History, not instructions.

## Conventions

- Python: ruff + mypy strict on `manuallabor/`; Pydantic v2; structured logging, one JSON line per model call in the project's `llm_calls.jsonl`.
- Frontend: TypeScript strict; small components; a single `hotkeys.ts` map; TanStack Query, no global state library.
- Tests: deterministic; model calls mocked unless marked `live`; Docling tests skip when its models are not cached, fail under `MANUALLABOR_REQUIRE_DOCLING=1`.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
