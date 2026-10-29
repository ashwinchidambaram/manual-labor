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
