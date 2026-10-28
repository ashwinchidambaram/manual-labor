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
