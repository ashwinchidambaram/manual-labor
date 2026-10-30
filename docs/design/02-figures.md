# Module 2 design: figure extraction

Inputs: SPEC §3, §4.3, §5.1, §6.1, §6.3, §6.4; `00-contracts.md` §4.3, §4.10, §10.5; `01-parse.md` §2–4, §8, §10; the module 1 code as it is now.
Output: one PNG per figure (plus an SVG for vector figures), a §6.3 sidecar per figure, a per-doc extraction report, and a project-wide dedupe index. Module 2 never modifies `blocks.json`.

## 0. Measured on this machine (2026-10-28, PyMuPDF 2.0 / MuPDF 1.28.5, Pillow 13.0, imagehash 4.3.2)

I parsed all six fixtures plus `figures-copy.pdf` (a byte copy of figures.pdf) in a scratch project and checked these against the real `blocks.json` and `parse/figures.json` files.

| Probe | Result | Used in |
|---|---|---|
| `parse/figures.json` candidates | figures: 14 (8 with exactly one xref and `has_drawings=False`, 6 with no xref and `has_drawings=True`). twocol p4: xref 10 and `has_drawings=True`. clean: 3 with one xref each. scanned: 3, `sources=["docling"]`, no xrefs, bbox loose by about 0.5 pt (Docling quantization). manual: 2, `bbox=None`, `docx_image_rid` rId9/rId10. tables: 0. | §2, §11 |
| Figure blocks | `raw_text == ""` on all of them. Labels inside a region are absorbed into `raw_text_by_parser` (the twocol composite has `pymupdf: "A B C"`). Caption blocks follow their figure in reading order, 0.8–4.4 pt below it. | §7 |
| Module 1 defect | `b-scanned-p006-08` (type caption) = `"Figure 2. Idler pulley mounting positions.\nKeep th…"`: the caption got fused with the next paragraph. | §7 trim rule |
| Region content (`get_image_info`, `get_drawings`, words) | 8 natives: 1 placement, coverage 1.000, 0 drawings, 0 words. 6 vectors: 0 images, 9–13 stroke paths all inside the bbox, a full-bbox frame rect, 0 words. twocol composite: 1 image + 5 paths + 3 words (A/B/C). | §2 |
| Native pixels | Every native fixture image is DeviceRGB, 8 bpc, no smask, Flate. `Pixmap(doc, xref)` → `Image.frombytes` → `save(PNG, optimize=False)` gave **exactly** the GT `source_image.sha256` (14/14 fixture images incl. twocol/clean) while the GT held PNG-file hashes; the GT now holds pixel hashes (see the fixture comparison note in §3). `extract_image()["image"]` bytes do **not** match: MuPDF rebuilds the PNG. | §3, test 3 |
| DOCX blobs | `document.part.related_parts[rid].blob` is image/png, 900×600, extent 3 in → 300 dpi; its decoded pixels match GT `source_image.sha256` (a pixel hash). | §8 |
| Render-agreement check (§3.3) | native: MAD 0.40–0.83, p99 ≤ 5. twocol composite: MAD 2.58, **p99 63.5**. Image clipped by a clip path (synthetic): MAD 12.4, p99 168. | thresholds |
| Whole-page `get_svg_image()` with a cropbox | 190 KB per figure, containing every glyph on the page and the *other* figure's raster as base64. **Rejected.** | §4 |
| Isolate-by-redaction, then `get_svg_image()` | 2.6–3.3 KB, 0 `<image>`, 11–13 paths, byte-identical across calls, 3–12 ms. Rendered back through `pymupdf.open("svg")`, it matches the page render (differences are sub-pixel edge shifts only). | §4 |
| 8×8 phash distances (all 25 fixture figures) | exact copies 0; 50% downscale (figures p7) **0**; scanned crop vs the clean native of the same image **2, 4, 6**; twocol composite vs its plain base image **10**; unrelated pairs **≥ 12** (min 12). 16×16 hash: composite 36, unrelated min 36 (no separation). Re-measured after the fixture line art moved to integer rasterisation (`wide_line`): exact 0, p7 0, scan vs native 2, 4, 6, composite vs base 10, unrelated min **10** (clean p6-01 vs manual image1). | §6 |

## 1. Package layout (`manuallabor/figures/`)

| File | Contents |
|---|---|
| `types.py` | Internal models (`ParseModel`, extra=forbid): `Placement`, `PageContent`, `Decision`, `FigureExtraction`, `FigureFailure`, `FigureReport`, `DedupeEntry`, `FigureIndex`, plus every threshold constant in this doc. `FIGURES_ALGO_VERSION = "1"`. |
| `page_content.py` | `load_page_content(page) -> PageContent`, cached per page: placements (`get_image_info(xrefs=True)`), drawings (`get_drawings()` reduced to rect/fill/stroke/items-kind), visible text spans (`get_texttrace()` with `type != 3`), page rect, has_text_layer |
| `decide.py` | `decide(region: BBox, pc: PageContent) -> Decision`. Pure: it reads only `PageContent`. (§2) |
| `isolate.py` | `isolated_page(src, pno, outer: Rect, keep_images: bool)`: a context manager that yields a temporary in-memory one-page doc with everything outside `outer` redacted (§4) |
| `native.py` | `extract_native(doc, placement) -> Raster`, `render_agreement(page, rect, img) -> (mad, p99)`, orientation search (§3) |
| `vector.py` | `export_vector(src, pno, bbox) -> (svg_bytes, Image)` (§4) |
| `crop.py` | `crop_region(src, pno, bbox, pc) -> (Image, crop_source, dpi)` (§5) |
| `encode.py` | `encode_png(img) -> bytes`, `composite_on_white(img)`, `sha256_bytes` (§10) |
| `docx_images.py` | `extract_docx_image(path, rid) -> Raster` (§8) |
| `captions.py` | `find_captions(blocks) -> dict[FigureId, CaptionMatch]`, pure (§7) |
| `dedupe.py` | `phash_hex(img) -> str`, `dedupe(items) -> list[DedupeEntry]`, pure (§6) |
| `sidecar.py` | `build_record(ext, doc, entry, existing: FigureRecord \| None) -> FigureRecord` (§9) |
| `pipeline.py` | `run_figures(paths, only=None, force=False, emit=stdout_emit) -> list[str]` (failed slugs) |

- **CLI:** `labor figures <project> [--force] [--doc SLUG]` (in `cli.py`; exit code 1 if any doc failed). Module 7 and `labor check` call `run_figures` right after `parse_project`.
- **Reuse:** `parse/geometry.py` (`iou`, `contain`, `area`, `qbox`) and `parse/pipeline.stdout_emit`.
- **Paths (`project.py`, the only place paths are built):**
  - `ProjectPaths.figures_root = root/"figures"`
  - `figure_dir(slug) = figures_root/slug`
  - `figure_file(slug, fid, ext) = figure_dir(slug)/f"{fid}.{ext}"`
  - `figures_index = figures_root/"index.json"`
  - `DocPaths.figure_report = root/"figures_report.json"`. The existing `DocPaths.figures` is module 1's `parse/figures.json` and keeps that name.

## 2. Method decision (`decide.py`)

**Definitions.** `R` = block bbox. `A(x)` = area. `cover(p) = A(p∩R)/A(R)`. `inside(p) = A(p∩R)/A(p)`.
- **Relevant placement:** an image placement `p` with `A(p∩R) ≥ 0.05·A(R)` or `inside(p) ≥ 0.5`. Neighbours that only graze R are ignored.
- **Ink drawing:** a drawing whose rect intersects `R` shrunk by 1 pt, except:
  - (i) **frame:** stroke only, rect ≥ 0.9·A(target) and within 2 pt of the target's edges, items all `re`, or ≤ 4 `l`;
  - (ii) **background:** fill only, with fill ≥ (0.98, 0.98, 0.98), whose rect contains R;
  - (iii) any drawing with `A ≥ 0.5·page area` (page backgrounds and borders).
- **Visible text:** a texttrace span with `type != 3` whose bbox overlaps `R` shrunk by 1 pt by ≥ 50% of the span's area.

Rules are evaluated in order; the first hit wins. Each records a `reason` (a `Literal`):

| # | Condition | Method | reason |
|---|---|---|---|
| 1 | `bbox is None` (DOCX) | native | `docx_image` |
| 2 | page has no text layer (`Document.pages_without_text_layer`) | crop | `scanned_page` |
| 3 | 0 relevant placements, ≥ 1 ink drawing, and every ink drawing ⊆ `R` expanded by `VECTOR_MARGIN_PT` (2 pt) | vector | `vector_only` |
| 4 | 0 placements, ink drawing crosses `R + 2 pt` | crop | `vector_crossing_paths` |
| 5 | 0 placements, 0 ink drawings | crop | `no_content` (e.g. a Docling picture made of text) |
| 6 | ≥ 2 relevant placements (counted as placements, not xrefs, so the same xref drawn twice counts as 2) | crop | `multiple_images` |
| 7 | the 1 placement has `cover < NATIVE_COVER` (**X = 0.90**) or `inside < 0.98` | crop | `image_partial_cover` |
| 8 | ink drawings intersect the placement | crop | `image_with_drawings` |
| 9 | visible text intersects the placement | crop | `image_with_text` |
| 10 | transform not axis-aligned (`|b|,|c| > 1e-6` and `|a|,|d| > 1e-6`), or the image is a stencil `/ImageMask` | crop | `image_transform` / `stencil_mask` |
| 11 | smask present with dimensions ≠ image dimensions | crop | `smask_size` |
| 12 | otherwise: extract (§3) and run the render-agreement check. Fail → crop | native / crop | `single_image` / `render_disagreement` |

Fixtures:
- **figures.pdf, natives (8):** rule 12 (cover 1.0, 0 ink, MAD ≤ 0.83).
- **figures.pdf, vectors (6):** rule 3 (the frame rect is ink, which is fine for vector; all paths are inside).
- **twocol composite:** rule 8 (5 arrow/label paths over the image), so crop. It would also fail rules 9 and 12.
- **scanned:** rule 2.
- **manual:** rule 1.

Module 1's `image_xrefs`/`has_drawings` are **hints only**: its drawing clusters skip anything < 24 pt (a small callout arrow over a photo would be missed). Module 2 recomputes everything from `PageContent`. The candidate's xrefs are logged in the report for debugging.

## 3. Native (`native.py`)

1. **Pixels:** `pix = Pixmap(doc, xref)`. Don't use `extract_image` bytes (measured: MuPDF re-synthesises them).
   - Colorspace: if `pix.colorspace.n` ∉ {1, 3} (CMYK, Lab, …), convert with `Pixmap(csRGB, pix)`. Indexed images come back expanded by MuPDF.
   - Mode: n=1 → `"L"`, n=3 → `"RGB"`. 16-bit sources come back as 8-bit from MuPDF; record `bpc` in the report.
2. **Soft mask:** if `extract_image(xref)["smask"]` is set, build `Image("L")` from `Pixmap(doc, smask)` and `putalpha` it, giving LA/RGBA. Don't use `Pixmap(pix, mask)`, because MuPDF samples with alpha are premultiplied.
3. **Render agreement** (an independent check: the page renderer against our decoding):
   - Render `R` from the original page at 72 dpi with `alpha=False`, then convert to L.
   - Composite our image on white, convert to L.
   - Resize both to 64 px on the long side with LANCZOS.
   - Pass iff `MAD ≤ 3.0` and `p99(|diff|) ≤ 24` (measured: natives 0.83/5, composite 2.58/63.5, clipped 12.4/168).
   - This catches clip paths, colour-key masks, decode arrays and overlays that rules 6–11 miss.
4. **Orientation:**
   - Upright = `a > 0, d > 0, b = c = 0` (PyMuPDF top-left space; measured `(240, 0, -0, 160, …)`).
   - For any other axis-aligned transform, try the 7 Pillow `Transpose` ops in enum order and keep the first with minimal MAD that passes step 3. None passes → crop (`render_disagreement`).
5. **Encoding:** always PNG via `encode_png`.
   - **JPEG / JPX / JBIG2 → PNG, losslessly from the decoded pixels.** The contract allows only `.png|.svg` (code: `figure.py` `_DEDUP_RE`/`parse_figure_file`). The report records `source_format` (`extract_image()["ext"]`), `source_xref`, `bpc`, and `source_sha256` (of the raw `extract_image` bytes, for provenance). The original JPEG is not stored (disk).
6. **Size and resolution:** `width, height` = pixel dims after orientation. `effective_dpi = min(w / (R.w/72), h / (R.h/72))`, rounded to 0.1.

**Fixture comparison:** GT `source_image.sha256` is a pixel hash (`tests/fixtures/gen/ground_truth.pixel_sha256`: RGB pixels plus size), not a PNG-file hash. PNG bytes are not portable: Pillow's bundled zlib-ng encodes the same pixels differently on macOS arm64 and Linux x86-64, which broke the fixture byte-identity gate (F2) on CI. Test 3 decodes each native output PNG and asserts its pixel hash equals the GT, which is the property that matters (lossless extraction).

## 4. Vector (`vector.py`): isolate by redaction, then MuPDF's own SVG/PNG

Options weighed:
- **(a) Whole-page SVG with a viewBox clip.** Rejected: it ships every glyph on the page and other figures' rasters (190 KB measured, and it leaks hidden content).
- **(b) Rebuilding the SVG from `get_drawings()`.** Rejected: it loses text labels, clip paths, shadings, dashes and blend modes, and we would own an SVG writer.
- **(c) Isolate, then `get_svg_image()`.** Chosen: full MuPDF fidelity (labels as glyph paths, clips, shadings), tiny output, deterministic, about 20 lines of code.

`isolated_page(src, pno, outer, keep_images)` works like this:
1. Create a new in-memory doc with `insert_pdf(src, from_page=pno, to_page=pno, annots=False, links=False, widgets=False)`. The source PDF is never modified.
2. `outer = (R + margin) ∩ page.rect`.
3. Add redact annots for the four strips outside `outer` (skip any that are empty).
4. Call `apply_redactions(images=PDF_REDACT_IMAGE_REMOVE if not keep_images else PDF_REDACT_IMAGE_NONE, graphics=PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED, text=PDF_REDACT_TEXT_REMOVE)`.
5. `set_cropbox(outer)`.

Text that overlaps a strip goes too: the caption 0.8 pt below the figure is removed, which is what we want.

Vector output:
- **SVG:** `page.get_svg_image(text_as_path=True)` (no fonts needed by the consumer).
- **PNG:** `page.get_pixmap(clip=outer, dpi=300, alpha=False, annots=False)` from the **same isolated page**, so the PNG and SVG show identical content and the PNG holds nothing outside the figure.
- **Margins:** `VECTOR_MARGIN_PT = 2.0` for both (a 0.5 pt frame stroke sits 0.25 pt outside R; measured caption gaps are ≥ 0.83 pt beyond the margin once redacted).
- **Size and resolution:** `width, height` = PNG pixel dims (for example 1101×684 for 260×160 pt). `effective_dpi = 300`.

## 5. Crop (`crop.py`)

`CROP_MARGIN_PT = 2.0` (not 4). Captions sit 0.8 pt below born-digital figures and 3.6 pt below scanned ones. A 4 pt margin would put caption ascenders into scanned crops, where text cannot be redacted out of the pixels. Two sources are possible, chosen in this order:

| crop_source | When | How | effective_dpi |
|---|---|---|---|
| `raster` | exactly one relevant placement with `cover ≥ 0.99`, an upright transform, no ink drawings and no visible text in R. This covers scanned pages and native images that are clipped or larger than the region. | Map `R + 2pt` through the inverse placement transform to source pixel coordinates, round outward, clamp, and `Image.crop` from the decoded `Pixmap` (no resampling) | the raster's own dpi (scanned fixture: 2550 px / 612 pt → 300) |
| `render` | otherwise (composites, multiple images, text overlays) | Use `isolated_page(..., keep_images=True)` and call `get_pixmap(clip=outer, dpi=300, alpha=False, annots=False)` | `min(300, min dpi of the rasters in R)`, or 300 if there is none |

The cached `pages/pNNN.png` is **not** used:
- it contains un-redacted captions and body text inside the margin;
- its pixel grid is page-aligned, so it would add a second resampling path;
- a clip render costs about 10 ms.

## 6. Phash and dedupe (`dedupe.py`)

- **Hash:** `phash_hex(img) = str(imagehash.phash(composite_on_white(img).convert("L")))`, the default `hash_size=8`.
  - The contract's `PHash` is `^[0-9a-f]{16}$` (64 bits), so `hash_size=16` would violate it.
  - It also measured worse: at 16×16 the composite's distance is 36 and the nearest unrelated pair is also 36, so there is no gap.
- **Hash input:** always the figure's PNG (native pixels, vector 300-dpi render, or crop).
- **Exact duplicate:** equal `png_sha256`. Encoding is deterministic, so equal pixels give equal bytes. Vector pairs also have identical SVGs.
- **Near duplicate:** all of the following:
  - `hamming ≤ NEAR_DUP_MAX_DIST = 8`;
  - aspect ratios within 5%;
  - both images non-blank (the 64×64 L stddev ≥ 3).

  **Why 8:** the largest measured same-diagram distance is 6 (scan vs native) and the smallest different-content distance is 10 (annotated composite vs its base). Unrelated pairs are ≥ 10 (≥ 12 before the fixture line art was re-rasterised in integer arithmetic). 8 is the midpoint, with a margin of 2 on each side. The fixture's 50% downscale (p7) has distance 0.
- **Compatibility:**
  - A `vector` figure may only duplicate a `vector` canonical. Otherwise the `svg` path would point at a figure with no SVG, which the FigureRecord validator rejects.
  - native/crop may duplicate any canonical (they point at its PNG).
- **Canonical order:** `key = (method_rank{native:0, vector:1, crop:2}, -(width*height), slug, page, n)`, across the whole project.
  - Iterate figures in key order. Each one is compared only against canonicals so far: an exact match first, else the near match with the smallest distance (ties go to the earlier canonical).
  - A match makes it `duplicate_of` that canonical; no match makes it a new canonical.
  - **No chaining:** a duplicate's distance is always measured to its canonical, so contract (f) holds.
- **Why method/size first** (the brief said doc order first): with the order above, a scanned crop dedupes onto the clean native, never the reverse. Among equals, the earliest `(slug, page, n)` wins.
- **Doc order is slug order:** ingest order is not persisted anywhere, and `list_slugs()` is sorted.
- **Gate case:** `figures` and `figures-copy` are identical (same method and size), and `figures` < `figures-copy`. So every copy figure points at `figures`, and copy p6/p7 point at `FIG-figures-p002-01`.
- **Persistence:** `figures/index.json` = `FigureIndex{algo_version, near_max_dist, entries: list[DedupeEntry{figure_id, source_doc, duplicate_of: FigureId|None, kind: "exact"|"near"|None, distance: int|None}]}`, sorted by `block_sort_key`.
  - Module 11 builds `ManifestFigure.duplicate_of` from it.
  - Sidecar `file` = `../<canon-slug>/<canon-id>.png`; for vector, `svg` = `../<canon-slug>/<canon-id>.svg`. This holds even when the canonical is in the same doc (the path is still `../<slug>/…`, which `parse_figure_file` accepts).
- **Storage:** every figure keeps its own PNG/SVG in the project; there is **one file per canonical in the export** (module 11 copies only the files that sidecars resolve to).
  - Dedupe is a pointer, so adding a better copy later only rewrites sidecars and never re-extracts.
  - The UI can always show the figure's own crop.
- **Near duplicates are reported:** module 3 should queue `kind == "near"` figures for review (a wrong file is a silent content error). The `figure_method` signal detail carries `near-duplicate of <id> (d=N)`.

## 7. Captions (`captions.py`, pure over one doc's `blocks.json` in reading order)

- **Neighbours:** for figure block `F`, `next` and `prev` = the nearest blocks in `reading_order`, skipping `header`/`footer`.
- **Candidate test:** the neighbour is `type == caption` and on the same page, and for PDFs:
  - the vertical gap is ≤ 48 pt (`cap.y0 − F.y1` below, `F.y0 − cap.y1` above; module 1's caption rule uses the same 48 pt);
  - the x-ranges overlap.
  - DOCX: adjacency only (bbox None).
- **Two passes over figures in reading order:**
  1. Each figure claims a candidate `next` caption.
  2. Unmatched figures claim an unclaimed candidate `prev` caption.

  A caption is claimed at most once. On figures.pdf p1, `F(p1-06)` takes `p1-07`, not `p1-05`; p3-01 gets None (its next block is a figure).
- **Text:**
  - Take the caption's `raw_text` lines.
  - Keep lines up to and including the first line that ends in `.` and is followed by a line starting with an uppercase letter; otherwise keep all lines.
  - Join with `" "` after stripping each line (whitespace normalisation only; no dehyphenation).
  - Record `caption_trimmed: bool`. This repairs the scanned p6 fused caption to `"Figure 2. Idler pulley mounting positions."`.
- **No match:** `caption_original = None`.
- **Outputs:** `caption_block_id` goes into the report (module 5's `caption_match` rule needs it). `description_generated = None` and `tags = []` until module 5's VLM.

## 8. DOCX (`docx_images.py`)

- **Image bytes:** `docx.Document(path).part.related_parts[rid]` → `.blob`, `.content_type`. Open the document once per doc.
- **Formats:**
  - `image/png` → keep the original bytes verbatim (they *are* the original; GT sha matches). Validate by decoding them with Pillow.
  - JPEG/GIF/BMP/TIFF → decode the first frame and `encode_png`; record `source_format`.
  - EMF/WMF/SVG/unknown → `FigureFailure(reason="unsupported_format:<ct>")`.
- **Method and position:** `native`, `bbox = None`, `page` = the block's virtual page (00 §5).
- **Resolution:** `effective_dpi = px_w / (inline.width_emu / 914400)`, using the first `doc.inline_shapes` whose blip embed equals the rid. If there is none (floating anchor), the value is None.
- **No rid:** a figure with `docx_image_rid is None` (Docling-only, unmatched) becomes `FigureFailure(reason="no_image_part")`.

## 9. Sidecars, report, signals (`sidecar.py`, `pipeline.py`)

**Layout:** `<project>/figures/<slug>/<FIG-id>.png|.svg|.json`, the exact mirror of export `images/<slug>/`, so the relative `../<slug>/` dedupe paths resolve inside the project too. Module 11 copies `FIG-*` files only (never `index.json`).

**Per-doc report** `docs/<slug>/figures_report.json` = `FigureReport{doc_id, fingerprint, algo_version, figures: list[FigureExtraction], failures: list[FigureFailure]}`.
- `FigureExtraction` holds:
  - `figure_id, block_id, page, bbox`
  - `method, reason, crop_source|None`
  - `source_format|None, source_xref|None, source_sha256|None, bpc|None`
  - `render_rect: BBox|None` (R + margin)
  - `png_sha256, svg_sha256|None`
  - `width, height, phash`
  - `effective_dpi|None, render_mad|None, render_p99|None, bbox_area_frac|None`
  - `caption_block_id|None, caption_original|None, caption_trimmed`
  - `hint_xrefs, hint_has_drawings` (from module 1)
- `FigureFailure` holds `{figure_id, block_id, page, reason}`.

**Sidecar fields:**

| Field | Value at module 2 | Owner afterwards |
|---|---|---|
| id, source_doc, page, bbox | from the block | — |
| file / svg | own `<id>.png` (`<id>.svg` iff vector), or dedupe path (§6) | module 2 |
| product_model | `Document.product_model` | — |
| extraction, width, height, phash | from extraction | — |
| caption_original | §7 | module 5 may not change it |
| description_generated, tags | None, [] | module 5 |
| articles, attach_rule | [], `none` | module 5 / 11 |
| confidence | provisional = `figure_method` value (below) | module 3 overwrites |
| review | `queued` | modules 3, 9 |

- **Downstream fields:** on rewrite, module 2 preserves `description_generated, tags, articles, attach_rule, confidence, review` from an existing valid sidecar with the same id.
- **Write rule:** sidecars are written with `write_json` only when the bytes differ.

**Signal inputs for module 3** (it owns the formula; these are the proposed values):

| Signal | Value | Critical |
|---|---|---|
| `figure_method` | native 1.0, vector 0.95, crop 0.70. A failure entry gives 0.0 (critical, so the block is always queued). Detail: `reason` + near-dup note. | failure only |
| `figure_resolution` (**new `SignalName` value**; module 2 adds it to `enums.py`, regenerates schemas/TS types and updates 00 §3) | `clamp(effective_dpi / 150, 0, 1)`; None dpi → signal omitted. Native 600 px over 240 pt = 180 dpi → 1.0; a 72-dpi web image → 0.48 | no |
| size sanity (detail only) | `bbox_area_frac = A(R)/A(page)`. Module 3 is advised to cap `figure_method` at 0.5 when `min(R.w, R.h) < 36 pt` or `bbox_area_frac < 0.002` (likely an icon or logo) | no |

## 10. Determinism

| Source | Handling |
|---|---|
| PNG encoder | One function: `img.save(buf, "PNG", optimize=False, compress_level=6)`. No `pnginfo` and no `dpi`, so no tEXt/pHYs chunks. Pillow is pinned by `uv.lock`. |
| MuPDF rendering | `pymupdf.TOOLS.set_aa_level(8)` set at stage start (it is global, so it doesn't inherit whatever another stage set); `alpha=False`; `annots=False`; single-threaded; fixed dpi 300 / 72. |
| SVG | MuPDF output measured byte-identical across calls. The temp doc is built the same way every time (same page, same redaction rects in fixed order top, bottom, left, right). Test 13 checks this across processes. |
| Redaction rects | Computed from `q()`-rounded bbox + constant margin. |
| Iteration | docs by slug; figures by `block_sort_key`; dedupe in canonical-key order; orientation candidates in enum order; JSON via `write_json` (sorted lists, no sets iterated). |
| phash | Deterministic DCT on fixed-size input; composite on white first, so alpha never feeds the hash. |
| Float noise | dpi, MAD and p99 rounded to 3 dp before thresholding and storage. |
| Time / paths | No timestamps or absolute paths in any file; elapsed time goes only to stdout. |
| Partial writes | Files are written atomically (temp + `os.replace`). Per doc, the report is written **last** and is the completion marker. Then `index.json`, then sidecars. |

**Idempotency:**
- `fingerprint = sha256(canonical_json({algo, pymupdf, pillow, imagehash, python_docx versions, doc sha256, parser_versions, sha256(parse/figures.json), sha256(blocks.json)}))`.
- **Skip a doc** when the report's fingerprint matches and every listed file exists with its recorded sha. Emit `{"stage":"figures","doc":…, "status":"skip"}` and touch no file.
- **Dedupe and sidecar phases** always run; they are cheap and rewrite only changed bytes.
- **`--force`** re-extracts.
- **Stale files:** `FIG-*` files in `figures/<slug>/` that are not in the current figure set (IDs changed after a re-parse) are deleted and listed in the progress `detail`.

**Progress lines:** `{"doc","stage":"figures","status","figures","by_method":{native,vector,crop},"failures","elapsed_ms","detail"}`, then a final `{"stage":"figures_dedupe","status":"done","exact":n,"near":m}`.

## 11. Invariants the stage asserts (raises `FiguresError`; the doc fails, other docs continue)

- The set of `figure_id`s on figure blocks in `blocks.json` == the set in `parse/figures.json`.
- Every figure block ends in exactly one of {sidecar, `FigureFailure`}. There are no sidecars for unknown ids.
- Every sidecar validates as `FigureRecord`, and its `file`/`svg` targets exist on disk.

## 12. Test list (`tests/figures/`)

**Fixtures:**
- Move module 1's session `parsed` fixture from `tests/parse/conftest.py` to `tests/conftest.py` (unchanged).
- `figproj` (session): copy that parsed project, run `run_figures`.
- `twin` (session): copy, ingest `figures-copy.pdf` (a byte copy of figures.pdf), `parse_project(only="figures-copy")`, run `run_figures`.
- Unit tests build synthetic PDFs in-test with reportlab/PyMuPDF.

| # | Fixture | Assertion |
|---|---|---|
| 1 | figures | 14 sidecars; `extraction` == GT `expected_extraction` for **every** figure (8 native, 6 vector), so 14/14 ≥ 95% (the gate); reasons `single_image` / `vector_only` |
| 2 | twocol | p4-01 → `crop`, reason `image_with_drawings`, `crop_source == "render"`; p2-01, p2-02 → native |
| 3 | figures, twocol, clean | for every GT figure with `source_image` and method native: pixel hash of the own PNG == GT `source_image.sha256` (a pixel hash), (width, height) == GT |
| 4 | figures | each vector: the SVG parses with `xml.etree`, has ≥ 1 `<path>` and 0 `<image>`; PNG ≥ 1000 px wide, and the fraction of non-white pixels is between 0.5% and 60%; the SVG rendered via `pymupdf.open("svg")` at 72 dpi agrees with the PNG downscaled (MAD ≤ 6) |
| 5 | figures | p6-01: `duplicate_of = FIG-figures-p002-01`, kind exact, `file == "../figures/FIG-figures-p002-01.png"`; p7-01: kind near, distance ≤ 8, same file target; no other figure in the doc is a duplicate; the exported file set (sidecar targets) has 12 distinct PNGs |
| 6 | twin (gate) | every `figures-copy` sidecar has `file` (and `svg` for vectors) under `../figures/`, kind exact; copy p2-01, p6-01 → `FIG-figures-p002-01`; p7-01 → same; a manifest built from `index.json` (`ManifestFigure`) validates contract (f) |
| 7 | figproj (all fixtures) | twocol p2-01 → clean p6-01 (exact), twocol p2-02 → clean p6-02 (exact); scanned p5-01, p6-01, p6-02 → near dups of the clean natives; twocol p4-01 composite is **not** a duplicate (d = 10 > 8); manual and figures images are not duplicates of anything outside their docs |
| 8 | all | every sidecar validates as `FigureRecord`; its `file`/`svg` resolve to existing files relative to `figures/<slug>/` |
| 9 | all | figure blocks ↔ sidecars ∪ failures is a bijection (no silent drops); fixtures have 0 failures; tables.pdf has 0 figure blocks and 0 sidecars |
| 10 | clean | 3 native, pixel hash == GT |
| 11 | scanned | 3 crop, reason `scanned_page`, `crop_source == "raster"`, `effective_dpi == 300`; each PNG has an IoU ≥ 0.9 between its render_rect and the GT bbox + 2 pt; the bottom 3 % of rows has < 1% dark pixels (no caption ink) |
| 12 | manual | 2 native, bbox None, page 1/2, PNG bytes == the DOCX blob (sha256 of the bytes in the set of part blobs), pixel hash == GT, `effective_dpi == 300` |
| 13 | figures | determinism: run in a subprocess with `PYTHONHASHSEED=123` on a fresh copy, so all `figures/**` and reports are byte-identical |
| 14 | figproj | idempotent: a second `run_figures` emits `skip` for every doc; PNG/SVG/JSON mtimes are unchanged; `--force` reproduces identical bytes |
| 15 | figproj | captions: `caption_original` == GT caption for every GT figure (figures 13 + p3-01 None, twocol 3, clean 3, scanned 3 incl. the trimmed fused p6-02, manual 2) |
| 16 | unit | captions: below beats above; one caption is never claimed twice; > 48 pt gap → None; no x-overlap → None; header/footer skipped |
| 17 | unit (synthetic) | decide: image + text overlay → crop `image_with_text`; two images in R → `multiple_images`; image clipped by a clip path → `render_disagreement`; image 50% outside R → `image_partial_cover`; vector + a 1 pt frame rect around an image → native (frame exemption); a white page background fill does not block native; text-only region → `no_content`; a path crossing R+2 → `vector_crossing_paths` |
| 18 | unit (synthetic) | native colour: a CMYK JPEG → RGB PNG, `source_format == "jpeg"`, agreement passes; an RGBA (smask) image → RGBA PNG whose alpha == the source alpha; a gray image → mode L; a horizontally flipped placement → the output equals the flipped source |
| 19 | unit | dedupe: chain A~B (d 6), B~C (d 6), A–C (d 12) → C is not attached via B; a vector never dups to a native; blank images are never near dups; canonical order prefers native over crop and larger over smaller |
| 20 | unit | `encode_png` of the same image twice gives the same bytes and no tEXt/pHYs chunks; `phash_hex` returns 16 lowercase hex chars |
| 21 | unit | sidecar rewrite preserves `description_generated, tags, articles, attach_rule, confidence, review` |
| 22 | cli | `labor figures <proj> --doc figures` exit 0, one JSON line per doc plus the dedupe line; a corrupted `parse/figures.json` (missing id) → `status:error`, exit 1, other docs still processed |

**Gate commands (M2):** `MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest tests/figures -q` (tests 1, 5, 6 are the gate) and `uv run ruff check && uv run mypy manuallabor/`.

## 13. Open issues (resolved with a choice)

1. **JPEG in a PDF.** Choice: decode → lossless PNG (contract `.png|.svg`); original format and sha go in the report. Note `00-contracts.md` §4.3 prose still says `png|jpg` and "`svg == <id>.svg`", while the code allows `png|svg` and dedupe paths. The code is right; fix the prose in this module's commit.
2. **Phash size.** Choice: 8×8 (contract `PHash` = 16 hex). The 16×16 option measured worse and would need a contract change.
3. **Near-dup threshold.** Choice: ≤ 8 (midpoint between 6 and 10), plus an aspect and non-blank guard. Near dups are flagged for review (§6). Revisit with real manuals in module 10 calibration.
4. **Canonical order.** Choice: quality first (method, pixel area), then slug/page/n. Ingest order is not persisted. If it must be, add `Document.ingest_index` (contract change), but slug order is deterministic and already satisfies the gate.
5. **Vector SVG strategy.** Choice: isolate by redaction + MuPDF SVG (§4). Risk: `LINE_ART_REMOVE_IF_TOUCHED` drops (not clips) paths that cross the margin, so rule 4 sends those regions to crop instead.
6. **Unextractable figures** (DOCX without an image part, EMF/WMF). Choice: a `FigureFailure` entry, no sidecar, and `figure_method = 0` critical in module 3, so a human sees it (and can flag `missing_figure`). There are no placeholder images.
7. **`figure_resolution`** is not in `SignalName`. Choice: module 2 appends it (enum, schema export, TS types, 00 §3, the C-test that lists enum values).
8. **Rotated pages (`page.rotation != 0`)** are not in any fixture. Choice: decide and render in the unrotated page space that module 1's bboxes use. Add a rotated-page fixture before module 11's acceptance run.
9. **Page renders** (`pages/pNNN.png`) are not reused (§5). The raster `crop_source` gives scanned figures their native pixels with no resampling instead.
10. **Duplicates keep their own project files.** "One file" holds in the export, not on disk; the cost is about 1 MB per fixture project, and it keeps dedupe a pure pointer that can be recomputed.
11. **Module 1 follow-up** (not blocking): the scanned p6 caption block fuses a paragraph (`b-scanned-p006-08`). Module 2 trims for `caption_original`, but the block itself is still wrong for grouping/cleanup. Log it in module 1's issues for the module 3 or 4 pass.

## 14. Post-review notes (2026-10-28)
- The sidecar `confidence` written here is the method-derived base (native 1.0 / vector 0.95 / crop 0.70) and is recomputed on every figures run. Module 3 overwrites it with the combined figure confidence; therefore module 7's stage graph must mark scoring stale whenever `labor figures --force` re-runs (same rule as parse → figures).
- Duplicate figures keep their own project-internal PNG (design §13.10); export (module 11) emits one file per canonical figure and rewrites references.
