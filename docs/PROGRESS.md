# Progress (module gates)

Each entry: module, date, gate command, pasted output, commit.

## M0 — Repo scaffold, contracts, fixtures, CI — PASSED 2026-10-28

Design: docs/design/00-contracts.md. Review: fresh Opus agent found 5 majors + 12 minors; all fixed (manifest accounting now requires per-doc block_ids and an exact partition; sidecar file path rule; embed output validation; vector fixtures clipped; ID regexes tightened; faithfulness DiffOp spans + NumericVariant; cache namespace).

Commands this session use: `uv run labor schemas export [--check]`, `cd frontend && npm run gen-types` / `npm run check-types-fresh`, `uv run python -m tests.fixtures.gen.make_fixtures --out tests/fixtures [--check]`.

```
$ uv run pytest
163 passed, 7 warnings in 4.15s
$ uv run ruff check manuallabor/ tests/ && uv run mypy manuallabor/
All checks passed!
Success: no issues found in 26 source files
$ uv run labor schemas export --check
schemas up to date
$ uv run python -m tests.fixtures.gen.make_fixtures --check
ok: 15 files match CHECKSUMS.json
$ ls tests/fixtures/*.pdf tests/fixtures/*.docx tests/fixtures/ground_truth/
tests/fixtures/clean.pdf
tests/fixtures/figures.pdf
tests/fixtures/manual.docx
tests/fixtures/scanned.pdf
tests/fixtures/tables.pdf
tests/fixtures/twocol.pdf

tests/fixtures/ground_truth/:
clean.json
figures.json
manual.json
scanned.json
tables.json
twocol.json
$ (cd frontend && npm run gen-types >/dev/null && git diff --stat -- src/types/generated.ts | tail -1; npm run typecheck && npm test -- --run 2>&1 | grep -E "Tests|passed")
 1 file changed, 20 insertions(+), 4 deletions(-)
      Tests  1 passed (1)
```
(The generated.ts diff line is against the previous commit; it is committed with this gate.)

## M1 — Ingest + dual parse + block model — PASSED 2026-10-28

Design: docs/design/01-parse.md (parser/OCR choices measured: Docling warm 0.25 s/page offline; Tesseract F1 0.987 vs RapidOCR 0.905 on scanned p2 → OCR default `auto`). Review: fresh Opus agent — gate met, 0 blockers, 4 majors (Docling text order in merge, scanned headings fused, unvalidated LLM metadata, weak tests 8/13/14) + minors; all fixed failing-test-first. Scanned bbox-match 0.50 → 0.9375, headings 12/18 → 18/18.

Commands: `uv run labor ingest <project> <files...>`, `uv run labor parse <project> [--force] [--doc SLUG] [--workers N]` (env `MANUALLABOR_WORKERS`, `MANUALLABOR_REQUIRE_DOCLING=1`, `MANUALLABOR_ALLOW_MODEL_DOWNLOAD=1`). Slow tests: `-m slow` (200-page stress test ran once by implementer A: 172.7 s with 2 workers; not re-run by the orchestrator because the machine had <1 GB disk at the time).

```
$ uv run ruff check manuallabor/ tests/ && uv run mypy manuallabor/
All checks passed!
Success: no issues found in 46 source files
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest -m "not slow"
274 passed, 2 deselected, 18 warnings in 217.98s (0:03:37)
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest -m slow -k scanned
1 passed, 275 deselected, 7 warnings in 56.21s
$ uv run labor schemas export --check && uv run python -m tests.fixtures.gen.make_fixtures --check
schemas up to date
ok: 15 files match CHECKSUMS.json
$ cd frontend && npm run gen-types && git diff --stat -- src/types/generated.ts && npm run typecheck && npm test -- --run
 1 file changed, 1 insertion(+)
      Tests  1 passed (1)
$ gate numbers (from tests/parse): token F1 1.000 + exact header/footer on clean/twocol/tables/figures; scanned: headings 18/18, bbox-match 0.9375, F1 0.9665; determinism byte-identical across PYTHONHASHSEED (test 2 + reviewer check 1)
```

## M2 — Figure extraction — PASSED 2026-10-28

Design: docs/design/02-figures.md (isolated-page SVG export; lossless JPEG→PNG; phash-64 near-dup threshold 8 measured against fixture distances 0/2–6/10/12+; `figures/<slug>/` + `figures/index.json`). Review: fresh Sonnet agent — gate PASS, 1 major (off-page bbox crashed the doc instead of one figure failure) + 5 minors; all fixed failing-test-first (44 figure tests).

Commands: `uv run labor figures <project> [--force] [--doc SLUG]`.

```
$ uv run ruff check manuallabor/ tests/ && uv run mypy manuallabor/
All checks passed!
Success: no issues found in 61 source files
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest tests/figures
44 passed, 15 warnings in 192.00s (0:03:12)
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest -m "not slow"
324 passed, 2 deselected, 19 warnings in 369.87s (0:06:09)
$ uv run labor schemas export --check && uv run python -m tests.fixtures.gen.make_fixtures --check
schemas up to date
ok: 15 files match CHECKSUMS.json
$ cd frontend && npm run gen-types && git diff --stat -- src/types/generated.ts; npm run typecheck && npm test -- --run
      Tests  1 passed (1)
$ gate numbers (tests/figures/test_gate.py): figures.pdf 14/14 methods match GT (8 native, 6 vector = 100% native/vector); p6 exact dup + p7 near dup -> FIG-figures-p002-01; figures.pdf ingested twice -> all 14 copy sidecars point at ../figures/; byte-identical across PYTHONHASHSEED 1/2
```

## M3 — Scoring + faithfulness check — PASSED 2026-10-29

Design: docs/design/03-scoring.md. First review (fresh Opus) REJECTED the gate: line reorder accepted on layout evidence alone (reordered steps auto-approved), digit-masked header removal deleted numeric body lines, real-manual test loosened. All fixed failing-test-first: reorder needs an independent reader's evidence; header/footer removal only on exact match or page-templated match; real metric restored (paragraph swallowed into a figure crop fixed at the source in parse/merge.py); unit lexicon (real-manual precision 0.47 → 0.93); verifier can never raise a score. Re-review of the fix dispatched after this record; findings, if any, are folded into the next commit.

Commands: `uv run labor score <project> [--force]`; live real-manual test `MANUALLABOR_LIVE=1 uv run pytest tests/scoring -k real -s`.

```
$ uv run ruff check manuallabor/ tests/ && uv run mypy manuallabor/
All checks passed!
Success: no issues found in 76 source files
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest tests/scoring
337 passed, 1 skipped, 14 warnings in 102.23s (0:01:42)
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest -m "not slow"
665 passed, 1 skipped, 2 deselected, 19 warnings in 248.97s (0:04:08)
$ MANUALLABOR_REQUIRE_DOCLING=1 MANUALLABOR_LIVE=1 uv run pytest tests/scoring -k real -s | grep -i recall
real manual (7 GT pages, 20 GT blocks): 16 differ from GT, 16 caught below 0.85 -> recall 1.000
tests/scoring/test_real_scanned.py::test_real_manual_recall
tests/scoring/test_real_scanned.py::test_real_manual_recall
tests/scoring/test_real_scanned.py::test_real_manual_recall
$ uv run labor schemas export --check && uv run python -m tests.fixtures.gen.make_fixtures --check
schemas up to date
ok: 15 files match CHECKSUMS.json
$ cd frontend && npm run gen-types && git diff --stat -- src/types/generated.ts; npm run typecheck && npm test -- --run
      Tests  1 passed (1)
$ gate numbers (tests/scoring/test_harness.py, test_corrupting_mock.py, test_recall.py): H1-H9 corruptions all < 0.85 (H1 0.0, H2 0.5, H3 0.5, H4 0.47/0.0, H5 0.0/0.48/0.0, H6 0.0, H8a 0.0, H9 0.25); legit edits >= 0.854; CorruptingMockProvider rejected 436/436 across 4 fixtures x 4 modes; numeric-spec blocks always queued; scanned.pdf SPEC 11.2 recall 1.000; real manual (TM 5-3895-332-12) recall 16/16; 1,000 blocks 1.18 s
```

## M4 — Grouping (structure + topic views) — PASSED 2026-10-29

Design: docs/design/04-grouping.md (document-mean-centered embeddings, average-linkage agglomerative, deterministic cut/cap/dissolve rules; measured on MockProvider and Ollama nomic-embed-text). Review: fresh Opus agent — gate PASS; 1 dormant major (do-not-merge pairs re-merged by straggler placement) + minors (no subtree-select op, cap not re-applied after stragglers, untested branches); all fixed failing-test-first (106 grouping tests). Gate run was interrupted twice by a full disk (Docker auto-updater); completed on the third run.

Commands: `uv run labor group <project> [--force]`; live clustering `MANUALLABOR_LIVE=1 uv run pytest tests/grouping -k live -s`.

```
$ uv run ruff check manuallabor/ tests/ && uv run mypy manuallabor/
All checks passed!
Success: no issues found in 90 source files
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest tests/grouping
106 passed, 2 skipped, 14 warnings in 106.94s (0:01:46)
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest -m "not slow"
838 passed, 3 skipped, 2 deselected, 19 warnings in 266.84s (0:04:26)
$ MANUALLABOR_REQUIRE_DOCLING=1 MANUALLABOR_LIVE=1 uv run pytest tests/grouping -k live -s
LIVE clean: n=128 topics=11 t000=0
LIVE clean: cohesion min=0.314 max=0.557
LIVE twocol: n=85 topics=10 t000=0
LIVE twocol: cohesion min=0.266 max=0.678
2 passed, 106 deselected, 7 warnings in 4.35s
$ uv run labor schemas export --check && uv run python -m tests.fixtures.gen.make_fixtures --check
schemas up to date
ok: 15 files match CHECKSUMS.json
$ cd frontend && npm run gen-types && git diff --stat -- src/types/generated.ts; npm run typecheck && npm test -- --run
 1 file changed, 1 insertion(+), 1 deletion(-)
      Tests  1 passed (1)
$ gate (tests/grouping + reviewer checks): partition invariant exact on all 6 fixtures in both views; structure tree 0 mismatches vs GT on clean/twocol/tables/figures; coverage mapping exact + symmetric; cohesion computed for every topic in [0,1]; groups.json byte-identical across PYTHONHASHSEED/cwd/cold cache; do-not-merge 0/42 leaks; topic cap enforced after stragglers
```

## M5 — Cleanup + figure attachment — PASSED 2026-10-29

Design: docs/design/05-cleanup.md (deterministic passes first; LLM only on residual triggers, 5 output checks then full faithfulness; attach caption_ref > caption_match > proximity > human). Review: fresh Opus agent — gate passes on its own run; 3 majors (header string deletable mid-sentence, table clean text never compared to raw_text, "Figure 1 to 2 mm" read as a range) + 5 minors; all fixed failing-test-first (204 cleanup tests). Test disk footprint reduced (copy_project skips page renders; 2 GB session guard; pytest basetemp in-repo).

Commands: `uv run labor clean <project> [--force] [--llm off|residual|always]`; live Ollama test `MANUALLABOR_LIVE=1 uv run pytest tests/cleanup -k live -s` (currently skips: no chat/vision model installed in Ollama).

```
$ uv run ruff check manuallabor/ tests/ && uv run mypy manuallabor/
All checks passed!
Success: no issues found in 103 source files
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest tests/cleanup
204 passed, 1 skipped, 14 warnings in 119.08s (0:01:59)
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest   # fast suite (-m "not slow" in addopts)
1042 passed, 4 skipped, 2 deselected, 19 warnings in 301.61s (0:05:01)
$ du -sh .pytest_tmp
1.8G
$ uv run labor schemas export --check && uv run python -m tests.fixtures.gen.make_fixtures --check
schemas up to date
ok: 15 files match CHECKSUMS.json
$ cd frontend && npm run gen-types && git diff --stat -- src/types/generated.ts; npm run typecheck && npm test -- --run
      Tests  1 passed (1)
$ gate (tests/cleanup tests 16/21/23 + reviewer run): CorruptingMockProvider rejected 100% on 6 fixtures × 4 modes; 0 faithfulness violations on auto-approved blocks after clean+re-score on all fixtures (scanned: 64 auto-approved, 0 violations; 133/133 corrupt outputs rejected); attach rule recorded on every attachment; caption_ref correct for every GT reference (clean 3/3, twocol 3/3, figures 12/12, scanned 3/3, manual 2/2); clean.json byte-identical across PYTHONHASHSEED
```

## M6 — Provider layer + hardware probe — PASSED 2026-10-29

Design: docs/design/06-providers.md (one LiteLLM-backed provider for ollama/anthropic/openai-compatible; lazy import; offline env; Ollama num_ctx + digest in cache key; probe + tiered suggestion table; `labor probe --apply <tier>`). Review: fresh Opus agent — conditional pass; 3 majors (prompt-truncation guard never fired on real Ollama, truncated replies accepted+cached, verifier defaulted to the cleanup model → skipped) + 8 minors; all fixed failing-test-first (210 provider tests). Defaults are the small tier (llama3.2:1b / qwen2.5:1.5b verifier / moondream / nomic-embed-text); the orchestrator pulled those models.

Commands: `uv run labor probe [--json] [--project P] [--apply small|medium|large|api] [--force] [--keep-overrides]`; live: `MANUALLABOR_LIVE=1 uv run pytest tests/providers -m live`; API live: `MANUALLABOR_LIVE_API=1` + key.

Known live-quality note: with the 1.5B verifier, 5 of 10 verifier calls errored (validation) on the cleanup smoke; errors are omitted as a signal (never lower or raise confidence), so faithfulness is unaffected. Larger tiers via `--apply`.

```
$ uv run ruff check manuallabor/ tests/ && uv run mypy manuallabor/
All checks passed!
Success: no issues found in 108 source files
$ uv run pytest tests/providers
210 passed, 65 skipped, 10 warnings in 14.93s
$ uv run python -c "import manuallabor.providers, sys; assert \"litellm\" not in sys.modules; print(\"lazy ok\")"
lazy ok
$ MANUALLABOR_LIVE=1 uv run pytest tests/providers -m live
12 passed, 46 skipped, 217 deselected, 16 warnings in 138.90s (0:02:18)
$ uv run labor probe
Platform : Darwin arm64
CPU      : Apple M3 (8 cores)
RAM      : 16.0 GB   usable for models: ~10.6 GB
GPU      : Apple M3 (10-core GPU)
Disk free: 16.1 GB (/Users/ashwinchidambaram/dev/projects/doc-to-KB)
Ollama   : 0.40.2 at http://localhost:11434, reachable

Suggested tier: small

task        small                                 medium                                  large                              api
----------  ------------------------------------  --------------------------------------  ---------------------------------  -----------------------------
cleanup     llama3.2:1b 1.3G ~38.5t/s fast        qwen2.5:7b 4.7G ~10.6t/s ok *           qwen2.5:14b 9G NO-FIT *            anthropic:claude-haiku-4-5
grouping    llama3.2:1b 1.3G ~38.5t/s fast        qwen2.5:7b 4.7G ~10.6t/s ok *           qwen2.5:14b 9G NO-FIT *            anthropic:claude-haiku-4-5
vision      moondream 1.7G ~29.4t/s ok            gemma3:4b 3.3G ~15.2t/s ok *            llama3.2-vision:11b 7.8G NO-FIT *  anthropic:claude-haiku-4-5
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest   # fast suite
1220 passed, 69 skipped, 2 deselected, 22 warnings in 325.66s (0:05:25)
$ uv run labor schemas export --check && uv run python -m tests.fixtures.gen.make_fixtures --check
schemas up to date
ok: 15 files match CHECKSUMS.json
$ cd frontend && npm run gen-types && git diff --stat -- src/types/generated.ts; npm run typecheck && npm test -- --run
 1 file changed, 3 insertions(+), 1 deletion(-)
      Tests  1 passed (1)
$ gate: one parametrized contract suite (assertions a–m) passes for mock, ollama (replay + LIVE), anthropic (replay), openai-compatible (replay); temperature 0 asserted on every outgoing request; offline guard: only OLLAMA_HOST contacted; secrets absent from logs/cache/project.json; labor probe prints the suggestion table on this macOS machine (small tier)
```

## M8 — UI: Scope — PASSED 2026-10-29

Design: docs/design/08-ui-scope.md (react-router 6, TanStack Query over openapi-fetch, server-owned selection with optimistic update + 150 ms debounce, single hotkey map, cached mock project for e2e via scripts/e2e-project.sh). UX check: independent Sonnet agent, 14 Playwright behaviours with server-side evidence (13 pass; focus loss after t/s). Review: fresh Opus agent — gate PASS; 3 majors (pending selection lost on unmount / reload; stale refetch overwrote a save) + focus bug + CI cache key; all fixed failing-test-first; module 9's shared-shell changes landed at the same time.

Commands: `cd frontend && npm test -- --run`, `npm run e2e` (starts `labor serve --dev --mock` on the cached mock project), `npm run build`; `bash scripts/e2e-project.sh` rebuilds the mock project (~95 s cold, cached by fixture+code hash).

```
$ npm run typecheck && npm test -- --run
 Test Files  12 passed (12)
      Tests  98 passed (98)
$ npm run e2e   # scope.spec + ux-scope.spec + scope-fixes.spec against labor serve --dev --mock on the cached mock project
  29 passed (1.3m)
$ npm run build
dist/assets/index-DVWAUwrK.css   15.02 kB │ gzip:  3.64 kB
dist/assets/index-CHvh8E8o.js   308.75 kB │ gzip: 97.83 kB
✓ built in 1.03s
$ gate: E1/UX2 toggle preserves selection (server GET /api/scope/selection identical across toggle); E2/UX3 counts live (optimistic < 100 ms, equal to GET /api/scope/summary after debounce); E3/UX9 keyboard-only flow (Tab/j/k/space/t/s/g) ends on /verify with visible focus at every step; FX1-FX3 selection never lost on navigate/reload/stale refetch
```

## M7 — API + project state + jobs + learning layer — PASSED 2026-10-29

Design: docs/design/07-api-state.md (+§13 code differences). Implementers A (state/jobs/check) and B (API/serve/client types) in parallel. Review: fresh Opus agent in an isolated worktree — gate rejected as committed: concurrent selection PUTs overwrote each other (read outside the write tx), approve-after-edit discarded the human edit, `labor parse --force` bypassed the decisions guard; all fixed failing-test-first (178 tests), plus request-id reuse → 409, replays never re-enqueue jobs, real-services end-to-end API test. Reviewer-confirmed: 30 actions persisted + replay-equal; R1–R6 byte-identical; locks; learning toggle/snapshot/rollback/reset; `labor check --live` PASS (454 s).

Commands: `uv run labor serve <project> [--port 8765] [--dev] [--mock]`, `labor status`, `labor run <project> [--to STAGE] [--force STAGE]`, `labor check [--live] <project>`, `labor learning list|reset|rollback <id>`, `labor decisions export`; OpenAPI: `uv run python -m manuallabor.api.export_openapi [--check]`, `cd frontend && npm run gen-api`.

```
$ uv run ruff check manuallabor/state manuallabor/jobs manuallabor/check.py manuallabor/api manuallabor/cli.py tests/state tests/jobs tests/check tests/api && uv run mypy manuallabor/
All checks passed!
Success: no issues found in 189 source files
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest tests/state tests/jobs tests/check tests/api --basetemp=.pytest_tmp_gate
178 passed, 1 skipped, 11 warnings in 376.84s (0:06:16)
$ uv run labor check ./tests/fixtures/project-a
check                   status      ms  detail
pipeline run            PASS     24201  2 docs ingested, scored, grouped, selected, cleaned
K1 nodes fresh          PASS       152  2 docs x 7 nodes fresh
K2 artifacts validate   PASS       224  245 blocks, 17 sidecars, selection 207 blocks
K3 faithfulness         PASS        56  0 violations in 69 auto-approved cleaned blocks
K4 block accounting     PASS        23  245 blocks each in exactly one group per view
K5 figures resolve      PASS         0  33 attachments resolved; 0 unresolved caption refs (reported)
K6 idempotent rerun     PASS       773  16 stage calls, all skip; 93 files unchanged
K7 mock only            PASS         0  183 LLM calls, all mock
K8 state                PASS         0  integrity ok, 1 actions monotonic, selection == DB
K9 baseline learning    PASS         0  learning provenance = baseline
K10 export gate         PASS       567  refused with 123 queued block(s), 0 open flag(s); first b-clean-p002-04
K11 review + export     PASS      5024  123 blocks approved by a scripted reviewer; exported 20 articles
K12 zip validates       PASS        17  20 articles, 17 figures, 455799 bytes
K13 export accounting   PASS        22  245 blocks: 207 in articles, 38 unassigned
K14 round trip          PASS        54  doc | blocks | auto_approved | faith_violations(auto) | articles | figures: clean | 150 | 65 | 0 | 15 | 3; figures | 95 | 57 | 0 | 5 | 14
K15 export determinism  PASS       499  sha256 a53de0326f07949d identical on a second export
K16 figure references   PASS         0  33 figure references resolve to a file and a sidecar

labor check: all checks passed
$ uv run labor schemas export --check && uv run python -m manuallabor.api.export_openapi --check
schemas up to date
openapi up to date: /Users/ashwinchidambaram/dev/projects/doc-to-KB/frontend/src/api/openapi.json
$ gate: tests/jobs R1–R6 kill-and-resume all byte-identical to an uninterrupted run (reviewer reproduced with 3 random SIGKILLs during parse + serve-only and serve+worker kills); every HIL action persisted append-only with monotonic id + request_id dedup (reviewer: 30 actions, replay-equal statuses, cursor restored); 20 concurrent selection PUTs all applied; approve-after-edit keeps the edited text; labor check K1–K16 PASS on a temp copy with forced mocks (and --live PASS in 454 s per the reviewer). Full fast suite is run at the module 11 gate once all in-flight modules are stable.
```

## M10 — Agent pass + calibration + learning — PASSED 2026-10-29

Design: docs/design/10-agent-calibration.md. Review: fresh Opus agent — gate FAILED on a blocker (table proposals could permute cell values through count-based checks) + 4 majors (accept race, edit-then-approve outcome, extrapolating threshold suggestion, digit add/drop treated as OCR look-alike); all fixed failing-test-first (positional table check; accept inside one transaction with an `expect` guard; strict equal-length look-alikes; no suggestion below the lowest populated bucket); 492 agent/calibration/scoring tests. Focused re-review of the fixes dispatched after this record.

Live note: `llama3.2:1b` cannot follow the proposal schema (invalid JSON / missing proposal_text) — recorded as `xfail(strict=True)` in test_31b; `labor probe --apply medium` is the remedy. Faithfulness is unaffected: 0 failing proposals are ever accepted.

Commands: `uv run labor agent <project> [--mock]`; API `POST /api/agent/run`, `GET /api/agent/proposals`, `POST /api/agent/proposals/{id}/{accept|edit|reject}`, `POST /api/agent/accept-all-passing`, `GET /api/calibration`, `POST /api/calibration/apply`.

```
$ uv run ruff check manuallabor/agent manuallabor/calibration tests/agent tests/calibration && uv run mypy manuallabor/
All checks passed!
Success: no issues found in 189 source files
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest tests/agent tests/calibration --basetemp=.pytest_tmp_gate10
90 passed, 2 skipped, 14 warnings in 68.44s (0:01:08)
$ MANUALLABOR_REQUIRE_DOCLING=1 MANUALLABOR_LIVE=1 uv run pytest tests/agent -m live --basetemp=.pytest_tmp_gate10
  outcome: flag-000001 error output is not valid JSON: Expecting ',' delimiter: line 1 column 283 (char 282)
  outcome: flag-000002 error output is not valid JSON: Extra data: line 1 column 1217 (char 1216)
  outcome: error proposal_text is missing
tests/agent/test_live.py::test_31_live_pass_accepts_nothing_that_failed
tests/agent/test_live.py::test_31_live_pass_accepts_nothing_that_failed
tests/agent/test_live.py::test_31_live_pass_accepts_nothing_that_failed
tests/agent/test_live.py::test_31_live_pass_accepts_nothing_that_failed
1 passed, 63 deselected, 1 xfailed, 12 warnings in 43.54s
$ uv run labor schemas export --check && uv run python -m manuallabor.api.export_openapi --check
schemas up to date
openapi up to date: /Users/ashwinchidambaram/dev/projects/doc-to-KB/frontend/src/api/openapi.json
$ gate (tests/agent/test_pass.py, test_accept.py, tests/calibration/test_gate.py): 5 seeded flags on project-a → 5 proposals each with its category recheck list; unfaithful mock proposal displayed with failing checks, accept → 409, accept-all-passing skips it; reject → item back in queue round 2 with PriorAttempt (prior rationale never in the prompt); calibration on 400 seeded decisions suggests 0.85, project.json byte-identical until explicit apply; proposals.json byte-identical across processes; table proposals compared per (row, col); concurrent accept → one decision
```

## M9 — UI: Verify — PASSED 2026-10-29

Design: docs/design/09-ui-verify.md. UX check: independent Sonnet agent, 14 Playwright behaviours with server-side evidence (11 pass initially). Review: fresh Opus agent — 1 faithfulness major (textarea editable while the 409 conflict panel was open, so a reviewer could confirm unseen text) + rail staleness + minors; all fixed failing-test-first; a focus regression from the fix was root-caused (a late approve ack consumed the queue's focus request while the editor/dialog was open) and fixed; one failing scenario was a test race. 216 vitest, 55/55 Playwright.

Commands: `cd frontend && npm test -- --run`, `npm run e2e` (all five specs), `npm run build`.

```
$ npm run typecheck && npm test -- --run
 Test Files  21 passed (21)
      Tests  216 passed (216)
$ npm run e2e   # all specs: scope, ux-scope, scope-fixes, verify, ux-verify against labor serve --dev --mock
  55 passed (6.8m)
$ npm run build
dist/assets/index-Dtm-8Tu0.css   20.01 kB │ gzip:   4.71 kB
dist/assets/index-jtyAfxb4.js   393.06 kB │ gzip: 124.17 kB
✓ built in 896ms
$ gate: VE1 + UX-T6 — 20 queued blocks processed keyboard-only (A/E/F/J/K incl. a 409-then-confirm edit and digit-keyed flags), server-side decision counts asserted; VE2 + UX-T5 — diff view matches the 12-row DiffOp rendering table; VE3 + UX-T10 + VE12 — figure re-attach via keyboard picker persists across reload with rule human, detach, rail refresh after job; slider = view filter; numeric approve sets numbers_verified; reload resumes at the cursor; late acks never steal focus from the editor/dialog
```

## M11 — Assemble + export + acceptance — PASSED 2026-10-29

Design: docs/design/11-export.md. Review: fresh Opus agent (git worktree) — gate held back on 3 majors (override cutoff read from a loose state file instead of the action log; a selected block placed in no topic was labelled `not_selected`; API/job exports wrote no `export_run`) plus validator/acceptance gaps; all fixed failing-test-first (11 tests) in M11.4. Confirmed by the reviewer: byte-derivation of every article from its blocks (0 diffs), Z1–Z8 each caught by a seeded corruption, export determinism, offline guard blocks TCP (UDP/raw added in the fix). `render.alt_text` escaping set recorded in design 11 §3.3.

Commands: `uv run labor assemble <project>`, `uv run labor export <project>` (exit 2 when the gate refuses), `uv run labor validate-export <zip>`, `bash scripts/acceptance.sh [--live]` (env `ACCEPT_ONLY/SKIP/KEEP/PYTEST_FLAGS`; renders docs/ACCEPTANCE.md via `scripts/render_acceptance.py`; INCOMPLETE exits 1).

```
$ MANUALLABOR_REQUIRE_DOCLING=1 bash scripts/acceptance.sh --live     # full run, 5735 s wall
== 1-1: uv run labor check --keep '…/labor-acceptance.sUizMT/project-all'   rc=0 (629 s)
K10 export gate         PASS      4518  refused with 329 queued block(s), 0 open flag(s); first b-clean-p002-04
K11 review + export     PASS    118078  329 blocks approved by a scripted reviewer; exported 52 articles
K12 zip validates       PASS       291  52 articles, 25 figures, 611728 bytes
K13 export accounting   PASS       265  621 blocks: 537 in articles, 84 unassigned
K14 round trip          PASS      1190  doc | blocks | auto_approved | faith_violations(auto) | articles | figures: clean | 150 | 65 | 0 | 15 | 3; figures | 95 | 57 | 0 | 5 | 14; manual | 13 | 7 | 0 | 3 | 2; scanned | 179 | 86 | 0 | 11 | 3; tables | 87 | 33 | 0 | 10 | 0; twocol | 97 | 44 | 0 | 8 | 3
K15 export determinism  PASS      5565  sha256 12a04817641542c5 identical on a second export
K16 figure references   PASS       102  48 figure references resolve to a file and a sidecar
labor check: all checks passed
== 7-1: uv run pytest tests/export -q                                  rc=0 (174 s)   124 passed, 1 skipped
== 7-2: uv run labor validate-export '…/project-all/export/project-a-kb.zip'
OK: 52 articles, 25 figures                                            # Z1–Z8 incl. Z8 README present and consistent
== 7-3: shasum -a 256 …/project-a-kb.zip
12a04817641542c5e08cd13bbdd259dd1f528fd4b0ed0e4f56d6dc4833bf3086
== 8-2: MANUALLABOR_OFFLINE=1 … uv run labor check --live --keep …      rc=0 (1314 s)
0 network violations; ollama=464 other=0; negative control: 1.1.1.1:443 blocked and logged
$ MANUALLABOR_REQUIRE_DOCLING=1 ACCEPT_ONLY=0 ACCEPT_KEEP=1 bash scripts/acceptance.sh --live   # AC0 re-run alone
== 0-1: env -u ACCEPT_ONLY -u ACCEPT_SKIP -u ACCEPT_KEEP -u ACCEPT_DRY_RUN uv run pytest -q   rc=0 (811 s)   1631 passed, 73 skipped
== 0-2: uv run ruff check manuallabor tests   rc=0
== 0-3: uv run mypy manuallabor               rc=0 (4 s)
== 0-4: uv run labor schemas export --check   rc=0
== 0-5: uv run labor openapi export --check   rc=0
$ docs/ACCEPTANCE.md
status: COMPLETE   generated: 2026-10-29T22:59:43Z   mode: live (local models)   host: Darwin 25.5.0 arm64, 16.0 GiB RAM   uv.lock sha256 918bc414…
| 0 | Machine checks | VERIFIED | 1 | VERIFIED | 2 | VERIFIED | 3 | VERIFIED | 4 | VERIFIED | 5 | VERIFIED | 6 | VERIFIED | 7 | VERIFIED | 8 | VERIFIED |
```

Notes: the first full run's AC0 failed only on `test_three_thousand_blocks_under_five_seconds` (5.83 s under load average 7; 1.37 s isolated, budget 5 s). The AC0 re-run then exposed that `tests/export/test_acceptance_script.py` inherited the outer `ACCEPT_ONLY`; fixed by scrubbing `ACCEPT_*` in the test helper and in the script's pytest step. Known limits carried from M10: the 1B agent model cannot follow the proposal schema (`labor probe --apply medium`); agent table fixes never fully pass `table_consistency` (fail-safe).

## M12 — Onboarding, tooltips, trust evidence, Agent + Export screens — PASSED 2026-10-30

Design: docs/design/12-onboarding.md (Opus; §11 resolutions). The user asked for a guide and tooltips, then for first-time-user clarity and visible trust evidence; the design also found that the Agent and Export screens were missing from the UI and added them. Backend: `GET/PUT /api/ui/guide` (per-project, version-aware, never an action). Review 1 (fresh Opus, worktree): HOLD on a blocker in the faithfulness path (oversize/rewrite early exits skipped the numeric comparison, so the UI could show "Numbers preserved: Passed" beside a failed check) + 5 majors (invented Agree/Differ verdicts, reconciliation by subtraction, Help tabs not keyboard-scrollable, over-claiming faithfulness copy, blanket export override). UX check (Sonnet, first-time user, 10 Playwright scenarios with server-side evidence): bare scores, tooltip Esc discarding an edit. All fixed failing-test-first (backend: `_numeric_violations` on every path, independent `queued`/`rejected` counts). Review 2 (fresh Opus): HOLD on 2 majors (the figure-flag fix let `a` approve the just-flagged block; a flag raised after a target override was still covered) → fixed: queue advances at once and resolves the figure target inside the queued write; `gate.py` covers only flags that existed when the override was recorded (+ store `flag_created_actions`). Test fixes: Scope E2 held its PUT on an 800 ms wall clock (now released after the assertion); UX7 copy assertion; temp-footprint guard cap 2 → 3 GiB.

Commands: `cd frontend && npm run gen-guide` (docs/USER_GUIDE.md from guide text + hint registry + hotkeys.ts; vitest drift check), `npm run e2e -- ux-onboarding` (first-time-user scenarios UX1–UX10), `npm run e2e -- onboarding` (OB1–OB10).

```
$ cd frontend && npm run typecheck && npm test -- --run && npm run gen-guide && npm run build
 Test Files  34 passed (34)
      Tests  305 passed (305)
✓ built in 1.34s            (docs/USER_GUIDE.md: no drift)
$ npm run e2e                 # all specs incl. onboarding + ux-onboarding, after the E2 and UX7 test fixes
  75 passed (5.3m)            (UX7 re-run after its copy assertion was updated: 1 passed)
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest --basetemp=.pytest_tmp_gate12d -o addopts="-m 'not slow'" -q
1666 passed, 73 skipped, 3 deselected, 28 warnings in 1132.48s (0:18:52)
$ uv run ruff check manuallabor tests && uv run mypy manuallabor && uv run labor schemas export --check && uv run python -m manuallabor.api.export_openapi --check
All checks passed! / Success: no issues found in 191 source files / schemas up to date / openapi up to date
$ MANUALLABOR_REQUIRE_DOCLING=1 uv run labor check ./tests/fixtures/project-a
K16 figure references   PASS         9  33 figure references resolve to a file and a sidecar
labor check: all checks passed
$ gate: guide shows once per project and reopens with ?; never steals focus mid-edit (OB/UX4); tooltips on keyboard focus with Esc isolated from the editor (UX5); every check verdict traces to faithfulness.passed / violation kinds, measured signals shown as values not verdicts; Verify line reconciles from independent server counts; export lock mirrors the server and overrides are per blocker; 5 blocks processed by a first-time user from on-screen text alone (UX2); 20 queued figure flags cannot be approved by a stray key (trust.test.tsx)
```

## M13 — Friendly, guided UI craft (Impeccable redesign) — PASSED 2026-10-30

Design: docs/design/13-ui-craft.md (Impeccable audit 11/20 with eight P1 findings, shape brief, two direction mocks; owner decisions D1–D8 and D1a: B "Calm guide" with A's warmth, A's segmented Verify progress bar, server card fields, Atkinson Hyperlegible bundled, full welcome band; §8 build notes and §8.1 fix round). PRODUCT.md principles 6–8 (guide, don't lecture; trust by showing; jargon translated at point of use). Brand tokens in DESIGN.md.

What changed: a step rail with a state-driven "Your next step" card replaces the guide column; a first-run welcome band names the manuals and counts blocks by type; Verify shows the magnified page strip directly above the extracted text, human queue cards (section title, first line, the uncertain word named), labelled OCR readings with the differences marked, a passed check in sage with "Passed" and red only for a failed cleanup check; Agent and Export have designed empty states and place titles for flagged blocks; everything folds to one line each at 720x450 (200 percent zoom). Server (ee6c9ed): `QueueItem.section_title/excerpt/weakest_word`, deterministic, no model. Two backend races found by the e2e runs and fixed at the cause with failing-first tests (edd799c, ff54fa9): concurrent page renders shared one temp file, and the job executor's start-up cleaner deleted a render's temp file written outside the worker lock. The frontend race behind every earlier "approve did not advance" flake (a queue refetch that left before an approve was processed, applied after it) is fixed: a snapshot older than the last settled write is refetched, never applied.

Reviews: independent Opus review in a worktree (3 P1, 8 P2, 10 P3, all fixed) and an Opus first-time-user UX check (`frontend/e2e/ux-craft.spec.ts` UC1–UC8 with server evidence, plus a reader's pass; 17 findings, all fixed except per-section blocker counts, a recorded server follow-up). Test assertions changed only where design 13 §5 or §8.1 names them; T3 and T5 untouched.

```
$ cd frontend && npx tsc -b --noEmit && npm test -- --run && npm run gen-guide && npm run build
tsc clean
 Test Files  44 passed (44)
      Tests  369 passed (369)
docs/USER_GUIDE.md regenerated (vitest drift test green)
dist/assets/index-BvG27NIT.js   512.26 kB │ gzip: 160.60 kB     ✓ built in 1.26s
$ npx playwright test            # every spec incl. ux-craft and zoom (720x450)
  1 skipped (UCR, opt-in reader's pass)
  85 passed (6.0m)
$ uv run pytest -o addopts="-m 'not slow' --basetemp=.pytest_tmp_gate13" -q
1669 passed, 73 skipped, 3 deselected, 28 warnings in 871.28s (0:14:31)
$ uv run ruff check manuallabor/ tests/ && uv run ruff format --check manuallabor/ tests/ && uv run mypy manuallabor/
All checks passed! / 376 files already formatted / Success: no issues found in 191 source files
$ uv run labor schemas export --check && uv run python -m manuallabor.api.export_openapi --check
schemas up to date / openapi up to date
$ uv run labor check ./tests/fixtures/project-a
K16 figure references   PASS         8  33 figure references resolve to a file and a sidecar
labor check: all checks passed
$ uv run labor check --live ./tests/fixtures/project-a
labor check: all checks passed
```

Follow-ups (additive server fields, not started): per-section blocker counts on `/api/export/status`; per-document queued counts in `/api/verify/queue` `docs[]` for quiet milestones. The server-ack latency while a re-parse job runs sits at 450–540 ms against T13's soft 500 ms budget under external load; not changed.
