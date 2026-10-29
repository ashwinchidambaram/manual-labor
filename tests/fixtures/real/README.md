# Real scanned manual (live-only fixture)

Tests that use this fixture skip when `real-manual.pdf` is absent. Nothing here except
`fetch.py`, `.gitignore`, this README and `ground_truth_sample.json` is committed.

- Title: TM 5-3895-332-12, Operator and Organizational Maintenance Manual: Hammer, Pile Driver,
  Self-Powered, Diesel (Koehring Model DA35), FSN 3895-443-4696. Headquarters, Department of the Army,
  29 January 1970.
- archive.org identifier: `micro_IA41152616_0581`
  (https://archive.org/details/micro_IA41152616_0581). Source PDF:
  https://archive.org/download/micro_IA41152616_0581/micro_IA41152616_0581.pdf
- Provenance: GPO/Readex microfiche collection (`us-government-printing-office`, `us-gpo`, `microfiche`);
  creator "United States. Department of Defense. Department of the Army"; scanned from microfiche at 400 ppi.
- Rights: the item page shows **no** rights, license or "possible copyright status" statement (verified on the
  details page and in `/metadata`: no `rights`/`licenseurl` field). Basis for public domain is that it is a
  US federal government work (Department of the Army technical manual, 17 U.S.C. 105). No quoted rights text exists.
- Source: 64 pages, 10,842,013 bytes (10.3 MiB), pages ~583 x 739 pt (some ~579 x 757), every page is an image
  (JPX, 3241 x 4108 px on page 5, about 400 DPI) plus archive.org's hidden OCR text layer (Tesseract; page 5 has about 2,100 chars).
- Built output `real-manual.pdf`: 64 pages, image-only (0 text chars), grayscale JPEG q80 at 300 DPI
  (min(source DPI, 300)), 27,037,885 bytes (25.8 MiB).
- Content: numbered chapters/sections and paragraphs (1-1 .. 5-2), two-column pages, numeric spec and torque lists
  (page 8), about 28 figures (list of illustrations on page 6; exploded views, a curve chart, photos), several tables
  (Tables 2-1, 3-1, 4-1 captioned; MAC and BII tables in appendices B/C; troubleshooting tables).

## Reproduce

    uv run python tests/fixtures/real/fetch.py

Downloads into `source/`, verifies sha256, builds `real-manual.pdf`, prints the output sha256. Idempotent.

- source sha256: `547d8d99f75abaff42eb1c937d6aab425b5c88270ba39bc40901d147c4bf10e1`
- output sha256: `7f803e1b30d7293fc077a632081a0edc853527618b9bf6e8b119c96a6b2c6704`
  (deterministic for the same PyMuPDF/Pillow versions; a different JPEG/MuPDF build may change it).

## Ground truth

`ground_truth_sample.json`: 20 blocks on pages 5, 6, 8, 9, 16, 25, 30 (headings, spec paragraphs and lists,
torque table, table rows, figure captions) with approximate bboxes and numeric tokens. It was transcribed from
page images by a model and should be spot-checked by a human before it is relied on. Page numbers are 1-based PDF page indices.
