# Test fixtures

Generated, not hand-edited. Regenerate from the repo root:

    uv run python -m tests.fixtures.gen.make_fixtures --out tests/fixtures
    uv run python -m tests.fixtures.gen.make_fixtures --check   # compare with CHECKSUMS.json

Layout: `clean.pdf`, `twocol.pdf`, `tables.pdf`, `figures.pdf`, `scanned.pdf` (image-only, derived
from `clean.pdf`), `manual.docx`, `ground_truth/<stem>.json` (coordinates are recorded while
drawing), `project-a/` (mock-provider `project.json` plus byte copies of `clean.pdf` and
`figures.pdf` under `sources/`), and `CHECKSUMS.json` (sha256 of every generated file).

Notes
- In `clean.pdf` the figures are numbered 1-3 but Figure 3 sits on the page before Figures 1 and 2
  (the design asks for this so caption-reference attachment is not order-dependent).
- GT `text` for tables joins non-empty cells with ` | ` and rows with `\n`; `raw_lines` has one
  space-joined line per row. List `text` omits the bullet glyph; `raw_lines` keep it.
- `scanned.pdf` GT is copied from `clean.pdf`: bboxes are approximate (about 6 pt, because of the
  0.5 degree rotation), figures expect `crop`, and `text_is_reference` is true.
- DOCX figures are numbered per virtual page; DOCX GT has no bboxes.

Checksum policy: outputs are byte-deterministic for a given `uv.lock`. If a dependency bump
changes a checksum, regenerate, review the diff (render a few pages), and commit the new files
together with `CHECKSUMS.json`. Never edit CHECKSUMS.json by hand. The determinism gate is test F2.
