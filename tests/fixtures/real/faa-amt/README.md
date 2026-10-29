# FAA AMT Handbook, General, Chapter 7 (live-only fixture, born-digital)

Tests that use this fixture skip when `faa-amt.pdf` is absent. Nothing here except `fetch.py`,
`.gitignore`, this README and `ground_truth_sample.json` is committed.

- Title: Aviation Maintenance Technician Handbook - General (FAA-H-8083-30B), Chapter 7 "Aircraft Materials,
  Hardware, & Processes". Publisher: Federal Aviation Administration, Flight Standards Service. Year: 2023
  (PDF dated 2023-07-21; InDesign 18.3 / Adobe PDF Library 17.0).
- URL: https://www.faa.gov/regulations_policies/handbooks_manuals/aviation/amtg_handbook.pdf
  (landing page https://www.faa.gov/regulations_policies/handbooks_manuals/aviation). archive.org identifier: none.
- Public-domain basis: US federal government work (FAA, 17 U.S.C. 105). No rights field is present in the PDF
  metadata or the download; the page offers no license text to quote.
- Deviation from "just copy the original": faa.gov now publishes only the whole handbook (677 pages, 92,539,602
  bytes = 88.3 MiB), no per-chapter PDFs. `fetch.py` downloads the original, verifies it, and cuts pages 245-324 (Chapter 7)
  with `insert_pdf` into a new file. Page content streams, fonts and images are copied unchanged (no re-render,
  no re-encoding). `Document.select()` was not used because it keeps all shared resources (~90 MB).
- Built output `faa-amt.pdf`: 80 pages (594 x 774 pt, fixture page N = printed page 7-N), 6,885,692 bytes (6.6 MiB).
  Born-digital: all 80 pages have a text layer (302,181 chars); 233 image placements (217 distinct image
  objects) on 38 of the 80 pages (up to 32 per page), plus vector drawings; tables are vector art with live text.
- Layout: two-column body text (columns start at x about 60 and 300 pt) on prose pages; full-width figure and table pages
  (torque table p53, bolt identification p40, rivet code charts p63); heading hierarchy (chapter title, red
  section heads, bold subheads, bold-italic run-in heads).
- Why useful: figure-heavy born-digital with a real text layer; captions are "Figure 7-N." even for tables (torque table
  is "Figure 7-34"); multi-column numeric tables with printed typos (`22,00-3,000`); fraction glyphs (`1¼`, stacked
  `3/32`); em-dash lists of part numbers (AN426, MS20426); figure/caption attach and figure-ref resolution.

## Reproduce

    uv run python tests/fixtures/real/faa-amt/fetch.py

Downloads into `source/`, verifies sha256, builds `faa-amt.pdf`, prints the output sha256. Idempotent.

- source sha256: `0a39c01bbc454e77a49813cf27e2ef291756fa7111d9308bc290cd0eb71616fd`
- output sha256: `d9b73048538dec7b3483ddfa495ce36224ff9dbf839480c5b3cb7cff14fad620`
  (deterministic for the same PyMuPDF build; another MuPDF version may change it).

## Ground truth

`ground_truth_sample.json`: 20 blocks on fixture pages 1, 40, 53, 56, 63 (titles, headings, torque-table rows,
paragraphs with numeric specs, lists, small tables, figure captions) with approximate bboxes (flagged) and numeric
tokens. It was transcribed from page images by a model and should be spot-checked by a human before it is relied
on. Page numbers are 1-based indices into `faa-amt.pdf`.
