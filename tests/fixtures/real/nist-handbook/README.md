# NIST Handbook 44 (2026), Section 2.20 Scales (live-only fixture, born-digital, table-heavy)

Tests that use this fixture skip when `nist-handbook.pdf` is absent. Nothing here except `fetch.py`, `.gitignore`,
this README and `ground_truth_sample.json` is committed.

- Title: NIST Handbook 44 - 2026, "Specifications, Tolerances, and Other Technical Requirements for Weighing and
  Measuring Devices", Section 2.20. Scales (the PDF's own title is "Section 2.20. Scales"). Publisher: National
  Institute of Standards and Technology (NIST), Office of Weights and Measures (adopted by the NCWM). Edition year 2026
  (PDF dated 2025-12-22, Microsoft Word for Microsoft 365). DOI 10.6028/NIST.HB.44-2026 (printed in the page margin).
- URL: https://www.nist.gov/document/2026-nist-handbook-44-section-220 (serves the PDF directly; index page
  https://www.nist.gov/pml/owm/nist-handbook-44-current-edition). archive.org identifier: none.
- Public-domain basis: US federal government work (NIST; 17 U.S.C. 105). Each page carries the margin text
  "This publication is available free of charge from https://doi.org/10.6028/NIST.HB.44-2026"; no explicit rights field
  in the PDF metadata. (NIST publications may embed third-party material; this section is NIST/NCWM-authored requirements text.)
- Why this one: `nvlpubs.nist.gov/.../nistspecialpublication811e2008.pdf` (SP 811, the first candidate) now returns 404, and the
  1991/1995 legacy copies of SP 811 are Acrobat-OCRed scans, not born-digital. Handbook 44 is split by NIST into per-section PDFs.
- Size and structure: 64 pages (612 x 792 pt), 1,695,062 bytes (1.6 MiB), born-digital: all pages have a text layer
  (192,519 chars), 0 embedded raster images, vector drawings on 33 pages (table borders). Single-column body text (tables up to two side by side), running
  header and footer page numbers `2-N`, and a rotated left-margin watermark line ("This publication is available...")
  that is extracted as text.
- Text-layer quirks (verified with PyMuPDF): Word export splits list labels from their text (`2.20. \nScales`);
  table captions come out before and detached from table bodies; cell order within rows is not row-major in places;
  "less than or equal" is an underlined `<` that extracts as plain `<`; symbol-font glyphs extract as private-use
  characters (U+F0xx); mathematical italic letters (U+1D4xx) appear in formulas; digit groups use spaces (`50 000`);
  the rotated margin watermark is extracted as an extra text line at the end of each page. No ligature glyph problems were found (no U+FB01/FB02).
- Why useful: dense numeric tolerance tables (Tables 1M/1 side by side, Table 6 maintenance tolerances, Tables 7a/7b, 8, S.6.3.a/b),
  hierarchical paragraph numbering (S.1.5.2., T.N.3.2., UR.3.1.), amendment-history lines "(Amended 1986 and 2024)",
  non-US-style digit grouping, units in text, and table footnotes.
- Built output `nist-handbook.pdf`: byte copy of the source (no re-encoding).

## Reproduce

    uv run python tests/fixtures/real/nist-handbook/fetch.py

Downloads into `source/`, verifies sha256, copies to `nist-handbook.pdf`, prints the output sha256. Idempotent.
NIST replaces Handbook 44 each year at this URL: a sha256 mismatch means the 2026 edition was superseded and the pinned hash
and ground truth need updating.

- source sha256: `6bfca74e62c7b324d640f1fc2ff916313944b40f4b5b91ea82d8f4448a60aaa9`
- output sha256: `6bfca74e62c7b324d640f1fc2ff916313944b40f4b5b91ea82d8f4448a60aaa9` (identical copy).

## Ground truth

`ground_truth_sample.json`: 20 blocks on pages 11, 44, 54 (headings, numeric-spec paragraphs, table captions, table rows, one table
footnote) with approximate bboxes (flagged) and numeric tokens. It was transcribed from page images by a model (and then
word-checked against the text layer) and should be spot-checked by a human before it is relied on. Page numbers are 1-based PDF
page indices (PDF page N is printed page 2-N).
