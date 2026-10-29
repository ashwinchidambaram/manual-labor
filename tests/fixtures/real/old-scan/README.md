# Real old (1944) scanned manual (live-only fixture, poor quality)

Tests that use this fixture skip when `old-scan.pdf` is absent. Nothing here except `fetch.py`, `.gitignore`, this
README and `ground_truth_sample.json` is committed.

- Title: TM 11-427, Barometers ML-102-B, ML-102-D, ML-102-E, ML-102-F, and ML-316/TM (War Department Technical Manual,
  November 1944; the reprint includes Changes 2 and 3, and the item also contains later changes dated 1952 for Barometer
  ML-102-G, e.g. "C 1, 17 Jun 52" on PDF page 5). Publisher: War Department (US Army Signal Corps equipment); archive.org lists
  creator "United States. Department of Defense. Department of the Army" and publisher "United States Government Printing Office; Readex
  Microprint Corporation". Catalog number D 101.11:11-427. Year: 1944.
- archive.org identifier: `micro_IA41152616_0619` (https://archive.org/details/micro_IA41152616_0619). Source PDF:
  https://archive.org/download/micro_IA41152616_0619/micro_IA41152616_0619.pdf
- Provenance: GPO/Readex microfiche collection (`us-gpo`); scanned from microfiche at 400 ppi (`ppi` field).
- Rights: no `rights`, `licenseurl` or `possible-copyright-status` field on the item or in `/metadata`. Basis for public domain: a
  US federal government work (War Department technical manual, 17 U.S.C. 105). No quoted rights text exists.
- Source: 57 pages, 8,270,472 bytes (7.9 MiB), pages about 569-583 x 733-742 pt; every page is a 3212 x 4072 px image (about 400 DPI)
  plus archive.org's hidden Tesseract OCR layer (52 of 57 pages have more than 200 characters of OCR text, much of it garbled).
- Built output `old-scan.pdf`: 57 pages, image-only (0 text chars), grayscale JPEG q80 at min(source DPI, 300) = 300 DPI,
  22,342,249 bytes (21.3 MiB).
- Visible quality problems (viewed at 80-170 DPI on pages 1, 5, 10, 20): low-contrast, faded gray type on a gray background
  with blur; heavy black microfiche borders and uneven background; the live area is off-center and pages differ in size and
  crop; binder-hole shadows on the edges; show-through and near-blank pages (PDF page 20 is almost empty); a pasted
  "Readex best copy available" label and handwritten catalog marks (`11-427`, `D 101.11:`) on the cover; thin small-print footnotes
  ("Note. Barometer ML-102-B and -F do not have correction chart.") that are barely legible; a calibration-curve chart page (p5) whose
  gridlines OCR as noise; hyphenated line ends in narrow table columns; OCR garbles the cover (`MI_-102-B`, `TECHRICAL`).
  It is typeset (not typewritten or mimeographed); the 1952 change pages are typewriter-style.
- Why useful: worst-case low-contrast scan for OCR routing, border/deskew handling, near-blank page detection, narrow multi-column
  maintenance-chart tables, and old-style numbering (`19.7`, `Par. 19.8`).

## Reproduce

    uv run python tests/fixtures/real/old-scan/fetch.py

Downloads into `source/`, verifies sha256, builds `old-scan.pdf`, prints the output sha256. Idempotent.

- source sha256: `c4bf2b2d5fa2b7904c7ce97ec78501b1a4e461f0952b28b557f2357026fb2837`
- output sha256: `fd4b708e9615be141868727a2550e0822141e7285ce09b9adcc9f85a5439b3d5`
  (deterministic for the same PyMuPDF/Pillow versions; a different JPEG/MuPDF build may change it).

## Ground truth

`ground_truth_sample.json`: a reduced sample of 8 blocks on pages 1 and 10 (cover title lines, notes, a heading, a table row and a table
cell with numeric specs). Bboxes come from the archive.org OCR line boxes, adjusted by eye, and are flagged approximate. It was
transcribed from page images by a model and should be spot-checked by a human before it is relied on. Page numbers are 1-based PDF page indices.
