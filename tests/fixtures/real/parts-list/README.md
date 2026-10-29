# Real scanned repair parts list (live-only fixture, table-heavy)

Tests that use this fixture skip when `parts-list.pdf` is absent. Nothing here except `fetch.py`, `.gitignore`,
this README and `ground_truth_sample.json` is committed.

- Title: TM 5-4110-231-24P, Organizational, Direct and General Support Maintenance Repair Parts and Special Tools
  List (Including Depot Maintenance Repair Parts and Special Tools) for Refrigeration Unit, Electric Motor Driven,
  9,000 BTU, Model CH609-31, NSN 4110-01-014-4646 (contains Changes 1 and 2). Headquarters, Department of the Army,
  Washington, DC, 6 July 1979.
- Publisher: US Government Printing Office / Readex Microprint (archive.org metadata); creator "United States.
  Department of the Army"; catalog number D 101.11:5-4110-231-24 P.
- archive.org identifier: `micro_IA41152645_0202` (https://archive.org/details/micro_IA41152645_0202). Source PDF:
  https://archive.org/download/micro_IA41152645_0202/micro_IA41152645_0202.pdf
- Provenance: GPO/Readex microfiche collection (`us-government-printing-office`, `microfiche`, `us-gpo`); scanned from
  microfiche at 400 ppi (`ppi` field); archive.org notes `pdf_degraded: invalid-jp2-headers`.
- Rights: the item page and `/metadata` show **no** rights, license or "possible copyright status" field. Basis for
  public domain is that it is a US federal government work (Department of the Army technical manual, 17 U.S.C. 105).
  No quoted rights text exists.
- Source: 61 pages, 9,068,386 bytes (8.6 MiB), pages about 564-569 x 733-760 pt; every page is an image (about
  2350 x 3050-3160 px in the first-8-page sample, about 300-400 DPI) plus archive.org's hidden Tesseract OCR layer.
- Built output `parts-list.pdf`: 61 pages, image-only (0 text chars), grayscale JPEG q80 at min(source DPI, 300) = 300 DPI,
  23,508,938 bytes (22.4 MiB).
- Content: p1 cover, p2-4 change pages, p5 title page and table of contents, p6-p9 introduction (SMR / maintenance
  code tables), p10-p44 exploded-view figures (Figure 1 on p10, Figure 2 on p12, ... Figure 13) alternating with
  facing parts tables with 9 columns (fig no., item no., SMR code, NSN, part number, FSCM, indented description with
  dot leaders, U/M, qty), p45-p50 Section IV national stock number / part number index, p51-p59 authentication and DA 2028
  forms, p60 conversion table, p61 blank.
- Why useful: dense multi-column part-number tables (hundreds of digit-heavy tokens such as `5305-00-068-0504`,
  `MS35206-227`), dot leaders, indenture dots in descriptions, figure/table facing pages, and strongly varying scan
  quality (dot-matrix print on p11 is nearly unreadable; p13 is clean; pages carry dark microfiche borders and
  slight skew).

## Reproduce

    uv run python tests/fixtures/real/parts-list/fetch.py

Downloads into `source/`, verifies sha256, builds `parts-list.pdf`, prints the output sha256. Idempotent.

- source sha256: `8a784f4c36b68d8e8273ea8c7a41b6c5f54342168a8f1ffd01203addb9a3dd41`
- output sha256: `571be450bdd23b8302167a920f2740598647c7f6c7de9020e217d6ece7a4cfa1`
  (deterministic for the same PyMuPDF/Pillow versions; a different JPEG/MuPDF build may change it).

## Ground truth

`ground_truth_sample.json`: 20 blocks on pages 5, 7, 10, 12, 13 (titles, headings, TOC rows, code-table row, note,
paragraph, figure captions, 7 parts-table rows). Approximate bboxes are flagged (OCR line boxes for pages 5-12, row-pitch
estimate for page 13 rows). It was transcribed from page images by a model and should be spot-checked by a human
before it is relied on; only rows whose digits were legible at 200 DPI were included. Page numbers are 1-based PDF page indices.
