# Module 1 design: ingest + dual parse + block model

Status: draft for approval · Inputs: SPEC §3, §4.1, §4.2, §5.1, §6.1, §9 · CLAUDE.md · `docs/design/00-contracts.md` · `manuallabor/contracts/{document,block}.py`, `manuallabor/ids.py` (binding as implemented)
Gate (CLAUDE.md): both parsers run on every fixture; blocks have stable IDs across re-runs; headers/footers detected on ≥2 fixtures.
Implementers: **A** (ingest, PDF adapters, layout, headers, merge, IDs, persistence, CLI) and **B** (OCR, DOCX, tables, OCR attachment, text alignment), in parallel. Neither may change this design. Report what you cannot satisfy instead.

## 0. Measured on this machine (2026-10-28, M-series, 8 cores, 16 GB)

| Fact | Value | Consequence |
|---|---|---|
| Docling 2.144.0, warm converter, OCR off | 0.25 s/page (clean 3.1 s, twocol 1.5 s, figures 2.0 s); `initialize_pipeline` 5 s; first-ever import ~60 s | 200 pages ≈ 55 s. Converter is built once per process. |
| Docling models | `~/.cache/huggingface/hub/models--docling-project--docling-layout-heron` and `...--docling-models` present; runs with `HF_HUB_OFFLINE=1` | Offline is possible. See §4.3. |
| Docling on `scanned.pdf`, OCR off | 0 texts and exactly the 3 GT pictures (p5, p6, p6) | Docling supplies figure regions on scanned pages. |
| Docling labels | `section_header`, `text`, `list_item` (one per item, grouped under a list group), `caption`, `page_header`, `page_footer`, `picture`, `table`. Prov bbox is BOTTOMLEFT. Table cells are TOPLEFT. | §4.2 mapping. |
| Tesseract 5.5.2 CLI (no pytesseract), 300 DPI, `--psm 3`, scanned pages | token F1 vs GT 0.97 to 0.997 (title page 0.89), 1.5 s/page, native word conf + bbox | Best OCR reader here. |
| `rapidocr` 3.10.0 (PP-OCRv6, models bundled in site-packages) | token F1 0.885 to 0.98, 1.8 s/page, word fragments with conf (fragment concat == line text with spaces removed: 172/172 lines) | Good independent second reader. |
| `rapidocr_onnxruntime` 1.4.4 (the declared dep) | drops spaces ("AcmeX200ServiceManual"); char-gap space reconstruction F1 ≈ 0.7 | **Not used.** |
| PyMuPDF 2.0 `get_text("dict")` blocks vs GT | IoU ≥ 0.5 for 148/150 (clean), 97/97 (twocol); misses are tables (cells split) and figures | §4.1 rules, plus a split at font changes (fixes the clean p11 heading+list merge). |
| `find_tables(strategy="lines")` on tables.pdf | 6/6 tables, shape and bbox exact, including the borderless one | The primary table structure. |
| `page.cluster_drawings()` on figures.pdf | exactly the 6 vector-figure rects | Vector figure regions. |
| Render 300 DPI | 0.6 s/page, 2550×3300 | — |

## 1. Package layout and ownership

```
manuallabor/
  project.py           A  ProjectPaths (all paths below), load/save project config, list docs
  ingest.py            A  ingest_files(), detect_kind(), sha256
  parse/
    __init__.py        A  re-exports parse_project, parse_document, ingest-side helpers
    types.py           A  internal (not exported) pydantic models of §2. Written FIRST, verbatim from §2
    geometry.py        A  q, area, iou, contain, union, center, expand
    text.py            A  TOKEN_RE, NUMERIC_TOKEN_RE, numeric_tokens, hf_key, SECTION_RE, CAPTION_RE, BULLETS
    pdf_pymupdf.py     A  PyMuPDF adapter (§4.1)
    pdf_docling.py     A  Docling PDF adapter (§4.2)
    render.py          A  page renders + process pool (§11)
    layout.py          A  detect_columns, order_page, group_lines_into_blocks (§5)
    headers.py         A  header/footer detection (§6)
    classify.py        A  type resolution, heading level/section number (§4.4)
    merge.py           A  candidate → block reconciliation, dispositions (§3)
    metadata.py        A  title/product_model heuristics + LLM fallback (§8.3)
    pipeline.py        A  stages, idempotency, progress lines, write (§10)
    tables.py          B  TableCandidate from PyMuPDF/Docling, spans, markdown, raw text (§9)
    ocr.py             B  OcrEngineAdapter: tesseract (CLI), rapidocr v3; OcrPage → PageParse (§7)
    ocr_attach.py      B  assign background-OCR words to born-digital blocks (§7.4)
    textalign.py       B  split_text_by_alignment (§3 step 5, §8.2)
    docx.py            B  python-docx adapter, virtual pages, Docling-DOCX second parser, DOCX merge (§8)
  cli.py               A  `labor ingest`, `labor parse`
```
`pyproject.toml` (A edits it on day 0, covering B's needs too): add `rapidocr>=3.10` (already installed transitively) and keep `rapidocr-onnxruntime` until module 6 (unused). Add `"rapidocr"` and `"pymupdf"` to the mypy ignore list. Add pytest marker `slow` and `addopts = "-q -m 'not slow'"`. Add mock default `DEFAULT_MOCK_RESPONSES[Task.metadata] = '{"title": null, "product_model": null}'` in `providers/mock.py` (registration, which 00 §10.16 allows).

## 2. Internal types (`parse/types.py`, `ParseModel(BaseModel, extra="forbid")`, using contract scalars BBox/Coord/Unit/TableCell/OcrWord)

| Model | Fields |
|---|---|
| `Line` | `text: str`, `bbox: BBox`, `size: Coord \| None` (font pt, or OCR median word height in pt), `bold: bool = False`, `words: list[OcrWord] = []` (OCR only), `native_id: str` (`"b3.l2"` PyMuPDF, `"t1.2.3"` tesseract block.par.line, `"r17"` rapidocr) |
| `TableCandidate` | `n_rows: int ≥1`, `n_cols: int ≥1`, `cells: list[TableCell]` (sorted (row,col), one per non-covered grid origin, empty text allowed), `header_rows: int ≥0` |
| `RawBlock` | `parser: str`, `page: int ≥1`, `order: int ≥0` (parser-native 0-based per-page order), `bbox: BBox \| None`, `kind: BlockType`, `text: str`, `lines: list[Line] = []`, `size: Coord \| None`, `bold: bool = False`, `heading_level: int \| None`, `section_number: str \| None`, `hint: str \| None` (native label, e.g. docling `page_header`, docx style name), `table: TableCandidate \| None`, `image_xrefs: list[int] = []`, `has_drawings: bool = False`, `docx_image_rid: str \| None`, `layout_only: bool = False` |
| `Skipped` | `page: int`, `order: int`, `bbox: BBox \| None`, `reason: Literal["empty_text","scan_background","tiny_drawing","table_rule","empty_paragraph"]`, `text: str = ""` |
| `PageParse` | `page: int`, `width: Coord`, `height: Coord`, `has_text_layer: bool`, `blocks: list[RawBlock]`, `skipped: list[Skipped] = []` |
| `ParserOutput` | `parser: str`, `version: str`, `source_sha256: Sha256Hex`, `pages: list[PageParse]` |
| `OcrPage` | `page: int`, `engine: OcrEngine`, `dpi: int`, `width: Coord`, `height: Coord`, `lines: list[Line]` (words with confidence, PDF points) |
| `OcrOutput` | `role: Literal["ocr","ocr_alt"]`, `engine: OcrEngine`, `version: str`, `source_sha256`, `pages: list[OcrPage]` |
| `Disposition` | `parser`, `page`, `order`, `outcome: Literal["primary","matched","split","aligned","absorbed","alone","skipped"]`, `block_id: BlockId \| None`, `detail: str \| None` |
| `MergeReport` | `doc_id: DocSlug`, `dispositions: list[Disposition]` (sorted by page, parser, order) |
| `Band` / `Overlap` / `PageLayout` | `Band{y0,y1, columns: list[list[Coord]]}`; `Overlap{a: BlockId, b: BlockId, iou: Unit}`; `PageLayout{page, source: Literal["textlayer","ocr","docx"], n_columns: int, bands: list[Band], block_columns: dict[BlockId,int], overlaps: list[Overlap]}` |
| `FigureCandidate` | `figure_id: FigureId`, `block_id: BlockId`, `page`, `bbox: BBox \| None`, `sources: list[str]`, `image_xrefs: list[int]`, `has_drawings: bool`, `docx_image_rid: str \| None` (this is module 2's input) |
| `ParseState` | `sha256`, `parser_versions: dict[str,str]`, `config_fingerprint: Sha256Hex`, `stages_done: list[str]`, `complete: bool` |

Parser role keys are used everywhere (file names, `raw_text_by_parser`, `order_by_parser`, `parser_versions`): `pymupdf`, `docling`, `ocr` (primary OCR engine), `ocr_alt` (secondary OCR engine), `docx`. The contract's example key `textlayer` is not used, because on born-digital pages `pymupdf` *is* the text layer.

## 3. Adapters and merge

```python
class PdfParserAdapter(Protocol):
    name: str                                    # "pymupdf" | "docling"
    def version(self) -> str: ...
    def parse_pdf(self, path: Path, ctx: ParseContext) -> ParserOutput: ...
class OcrEngineAdapter(Protocol):              # B
    engine: OcrEngine
    def available(self) -> bool: ...
    def version(self) -> str: ...
    def ocr_page(self, png: Path, page: int, size_pt: tuple[float, float], dpi: int) -> OcrPage: ...
@dataclass(frozen=True) class ParseContext: slug: str; sha256: str; page_sizes: tuple[tuple[float,float],...]; text_layer: tuple[bool,...]; config: ProjectConfig; paths: ProjectPaths
```
`config.parsers[0]` is the primary parser and `[1]` the secondary for text-layer pages. Only `pymupdf` and `docling` are registered; an unknown name raises `ParseError`.

**Sources per page:**
| Page | Primary (P) | Secondary (S) | Region-only | Background |
|---|---|---|---|---|
| has text layer | pymupdf | docling | — | `ocr` words attached (§7.4) if `background_ocr_born_digital` |
| no text layer | `ocr` | `ocr_alt` | docling `layout_only` pictures/tables; pymupdf runs and yields only `Skipped(scan_background)` | — |
| DOCX | docx | docling (DOCX backend) | — | — |

**Merge (`merge.merge_page(P, S, R, page) -> list[MergedBlock], list[Disposition]`), pure and deterministic.** All geometry uses `q()`-rounded (3 dp) coordinates.
1. **Regions.** Table and figure candidates from P, S and R are matched across parsers by IoU ≥ 0.5 (greedy, see step 3 ordering). Each match group becomes one region block. Unmatched regions are kept alone. Bbox priority: pymupdf > docling for figures and tables; for figures the union is used if `has_drawings` composite.
2. **Absorption.** A text candidate (any parser) with `contain(cand, region) ≥ 0.8` is absorbed into that region (outcome `absorbed`). Tables: its text feeds that parser's table text when that parser has no table structure there. Figures: labels inside the figure. Captions sit outside regions, so they are never absorbed.
3. **1:1 matching** of remaining text candidates: score = IoU. Pairs are taken greedily in the order `(-iou, p.order, s.order)`, accepted if IoU ≥ 0.5, or if `contain(small, big) ≥ 0.7` and that is the only such partner for both.
4. **P coarser than S** (≥2 unmatched S each with `contain(s, p) ≥ 0.7`): split p's `lines` among those S by line-center containment (lines in no S go to the S with the nearest center by vertical distance). Each piece pairs with its S (outcome `split`). Bbox = union of the assigned lines.
5. **S coarser than P** (≥2 unmatched P each with `contain(p, s) ≥ 0.7`): keep P's segmentation. `textalign.split_text_by_alignment(s.text, [p.text …])` slices s's text onto each p (outcome `aligned`).
6. Every still-unmatched candidate becomes its **own block** (`alone`), with `raw_source` = its parser. **Nothing is dropped.** The only non-block outcomes are `absorbed` (text still lands in the region's `raw_text_by_parser`) and `skipped` with an allowed reason from §2.
7. Block fields: `raw_source` = P if P contributed non-empty text, else S, else R (layout-only). `raw_text` = that source's text. `raw_text_by_parser[k]` = the text of each contributing parser. `order_by_parser[k]` = min native `order` among k's candidates in the block. `bbox` = the primary contributor's bbox.

**Scanned pages (P = ocr, S = ocr_alt).** Both sides have lines with bboxes, so instead of step 3 S is merged at **line** level: each alt line goes to the P block containing its center (expanded by 3 pt). Alt lines in no P block are grouped with `group_lines_into_blocks` into `alone` blocks with `raw_source="ocr_alt"`.

## 4. PDF adapters (A)

### 4.1 PyMuPDF (`pdf_pymupdf.py`)
- Text: `page.get_text("dict", flags=TEXT_PRESERVE_LIGATURES | TEXT_PRESERVE_WHITESPACE | TEXT_MEDIABOX_CLIP, sort=False)`. Line text = the span texts concatenated, rstripped. Whitespace-only lines are dropped. Block text = lines joined `"\n"`. Line `size`/`bold` come from the dominant span (most chars); bold = `flags & 16` or `"Bold"` in the font name. `order` = native block index after splitting.
- **Split** a native block before line i when |size_i − size_{i−1}| > 1.0, bold differs, or the vertical gap > 1.5 × the block's median line height.
- **Tables:** `page.find_tables(strategy="lines")`. B's `tables.from_pymupdf(tab, page)` returns the TableCandidate. Region bbox = `tab.bbox`.
- **Figures:** `page.get_image_info(xrefs=True)` gives the rects (skip w or h < 24 pt). Then `page.cluster_drawings()`: skip clusters with w or h < 24 pt (`tiny_drawing`) or ≥ 50% inside a table bbox (`table_rule`). Image rects and drawing clusters with IoU ≥ 0.3, or containment ≥ 0.8, merge into one figure candidate (union bbox, `image_xrefs` sorted, `has_drawings=True`). On a page with no text layer, an image covering ≥ 80% of the page area becomes `Skipped(scan_background)`.
- Kind guess: §4.4 rules using size/bold.

### 4.2 Docling (`pdf_docling.py`)
- Converter, built once per process and held by the adapter:
  - `PdfPipelineOptions(do_ocr=False, do_table_structure=True, generate_page_images=False, generate_picture_images=False)`, with `table_structure_options.do_cell_matching=True` and the default (ACCURATE) mode.
  - `accelerator_options=AcceleratorOptions(device=CPU, num_threads=4)`, a fixed constant and never `cpu_count()`.
  - Before the first convert: `torch.manual_seed(0)`, `torch.use_deterministic_algorithms(True, warn_only=True)`. Call `initialize_pipeline(InputFormat.PDF)` eagerly.
- Items come from `doc.iterate_items()` in order, and the index gives `order`. One candidate is made per `prov` entry. For multi-prov items, text = `item.text[charspan]`. Bbox = `prov.bbox.to_top_left_origin(page_height=doc.pages[page_no].size.height)` (assert BOTTOMLEFT before converting), as `[l, t, r, b]`. Model-derived regions (picture/table) are quantized to 0.5 pt. Text-item bboxes are `q()`-rounded.
- Labels: `title`/`section_header` → heading. `text`/`paragraph` → paragraph. `list_item` → list, with **consecutive items sharing a parent list group merged** into one candidate (union bbox, item texts joined `"\n"`). `caption` → caption. `page_header`/`page_footer` → paragraph with `hint` set (§6). `table` → table (B's `tables.from_docling(item)`). `picture`/`chart` → figure. `footnote`, `formula`, `code`, everything else → other. On no-text-layer pages every candidate gets `layout_only=True`; text items there are empty and are skipped (`empty_text`).
- Version string: `docling==<v>; docling-ibm-models==<v>; models=<name@refs/main[:12]>…` (sorted, read from the HF cache `refs/main`).

### 4.3 Docling offline and cold start (decision)
Docling **must** run on every PDF fixture for the gate, and on this machine its models are already cached. The adapter never downloads silently:
- On construction it checks for the two model dirs (or `MANUALLABOR_DOCLING_ARTIFACTS` → `artifacts_path`).
- If they are present, it sets `os.environ.setdefault("HF_HUB_OFFLINE", "1")` before importing docling (docling is imported lazily, inside the adapter).
- If they are absent, it raises `ParserUnavailable("docling models not cached; run: uv run docling-tools models download")`, unless `MANUALLABOR_ALLOW_MODEL_DOWNLOAD=1`.

The pipeline does **not** fall back to a single parser (SPEC §4.2: not optional).

Tests use the `requires_docling` fixture. It skips with that reason only when the models are absent **and** `MANUALLABOR_REQUIRE_DOCLING != "1"`. The gate command sets `MANUALLABOR_REQUIRE_DOCLING=1`, so on this machine a missing model is a failure, not a skip.

### 4.4 Type resolution (`classify.py`, applied to merged blocks; first matching rule wins)
| # | Rule |
|---|---|
| 1 | header/footer from §6 |
| 2 | region kinds: table, figure |
| 3 | caption: `CAPTION_RE = r"^(?:Figure|Fig\.|Table)\s+\d+[A-Za-z]?(?:[.:]|\s)"` matches raw_text, **and** (a figure/table region on the page within 48 pt vertical gap **or** docling labelled it caption) |
| 4 | list: docling list, or every non-continuation line starts with a char in `BULLETS = "•·◦▪‣*–-"` followed by a space (continuation = indented ≥ 2 pt past the bullet x0) |
| 5 | heading: docling `section_header`/`title`, **or** the P heuristic: ≤ 3 lines, ≤ 25 words, no terminal `.`, and every line has size ≥ body + 1.0 or (bold and size ≥ body). body = char-weighted mode of line sizes over the doc, rounded to 0.5 pt. For OCR, line size = median word height. |
| 6 | paragraph if text non-empty, else other |

Heading level: if `SECTION_RE = r"^(\d+(?:\.\d+)*)\.?\s+\S"` matches, then `section_number` = group 1 and level = component count (cap 6). Otherwise level = rank of the block's size among the doc's distinct heading sizes (desc, 1-based, cap 6). For a heading with no size (docling-only), use docling `level` clamped to 1..6. `section_number` is set only on headings.

## 5. Reading order (`layout.py`, A)

`order_page(items: Sequence[OrderItem], page_w, page_h) -> tuple[list[int], list[Band]]`, where `OrderItem(bbox, role: "header"|"footer"|"body", tiebreak: tuple)`:
1. Headers first, sorted by (y0, x0, tiebreak). Footers last, same key.
2. Body: an item is **spanning** if width ≥ 0.55 × (max x1 − min x0 of body items). Spanning items, sorted by y0, cut the page into bands.
3. Per band: build an x-coverage array at 1 pt bins from the band's non-spanning items. **Gutters** are runs of zero coverage ≥ 10 pt strictly between the band's min x0 and max x1. Columns are the intervals between gutters. Each item is assigned to the column containing its x-center.
4. Sequence: bands top→bottom with each spanning item placed by its y0. Within a band, columns left→right. Within a column, sort by (round(y0,1), round(x0,1), tiebreak).
5. `tiebreak = (primary order, secondary order)`, which makes the order total.

`detect_columns(boxes, page_w) -> list[Band]` is exposed separately. `group_lines_into_blocks(lines, page_w) -> list[list[Line]]` (used by B for OCR):
- Columns are found with `detect_columns` on line boxes. Lines are sorted per column by y0.
- A new block starts when any of these hold:
  - gap > 0.8 × median line height of the column;
  - line height differs > 25% from the previous line;
  - a bullet line follows a non-bullet line;
  - a non-indented non-bullet line follows a bullet block.

**`reading_order_risk` inputs** (written to `parse/layout.json`): `n_columns` (max over bands), `block_columns`, and `overlaps` (block pairs on the page with IoU > 0.05, excluding absorbed pairs). Parser order disagreement is read by module 3 from `Block.order_by_parser` (per-page native indices).

## 6. Header/footer detection (`headers.py`, A)
- Candidates are merged non-region blocks with y1 ≤ 0.12·H (top band) or y0 ≥ 0.88·H (bottom band).
- `hf_key(t)` = casefold, every digit run → `#`, whitespace collapsed, stripped.
- Grouping is by (band, key). On OCR pages, keys cluster greedily in sorted order with `difflib.SequenceMatcher.ratio() ≥ 0.85`.
- A group is header (top) or footer (bottom) if it appears on ≥ max(3, ⌈0.5·n_pages⌉) distinct pages **and** every member's y-center is within 8 pt of the group median (this tolerates the 0.5° scan rotation).
- Additionally, a block in the band that docling hinted `page_header`/`page_footer` is classified as header/footer.
- Docs with < 3 pages: only the docling hint applies.
- Results: those blocks get `type=header|footer` and **remain blocks** (00 §10.4). `Document.stripped_headers` / `stripped_footers` = `sorted(set(raw_text))` of those blocks (e.g. `["Acme X200 Service Manual"]`, `["Page 10", "Page 11", …]`). Module 5 uses these exact strings for the faithfulness allowance.

## 7. OCR (B)

### 7.1 Engines (`ocr.py`)
- **Tesseract:** `tesseract <png> stdout --dpi <dpi> -l eng --oem 1 --psm 3 tsv`, run with env `OMP_THREAD_LIMIT=1`.
  - Words = level-5 rows with non-blank text and conf ≥ 0; confidence = conf/100.
  - Lines = grouped by (block, par, line); `native_id = "t{b}.{p}.{l}"`.
  - Version = `tesseract --version` line 1 plus `eng.traineddata` sha256[:12] (path from `--list-langs`).
- **RapidOCR:** `rapidocr.RapidOCR(params={"Global.log_level": "error", "EngineConfig.onnxruntime.intra_op_num_threads": 1})`, `return_word_box=True`.
  - Line text = `txts[i]`. Words = whitespace tokens of the line. Each token maps onto `word_results[i]` fragments by character offset (the fragment concatenation equals the line with spaces removed).
  - Word confidence = **min** of overlapping fragment scores; word bbox = union of those fragment boxes.
  - If the concat check fails for a line, words = the fragments themselves.
- Pixel → points: `pt = px × 72 / dpi`, then `q()`. Quads become axis-aligned bboxes clamped to the page.
- `OcrPage → PageParse` (`ocr_page_to_parse(op, role)`): `group_lines_into_blocks`, then per block text = lines joined `"\n"`, words carried on lines. Kind guesses use §4.4 (size = median word height).

### 7.2 Engine roles (decision)
`ocr` = `config.ocr_engine`, `ocr_alt` = the other engine.
- If the configured engine is unavailable (`shutil.which("tesseract")` is None), the roles swap. If only one engine exists, `ocr_alt` is absent: parse emits a `warning` progress line and records `parser_versions["ocr_alt"] = "unavailable"`.
- For scanned pages the "two parsers" are **Tesseract + RapidOCR**: two independent engines, with Docling layout-only for figures.
- PyMuPDF-on-image yields nothing, and Docling+Tesseract would reuse the same engine, so neither is used as the second reader.
- **Open issue 1 requests the default flip to `tesseract`**; the design works either way.

### 7.3 Born-digital background OCR
- Only the `ocr` engine runs, on every text-layer page, when `background_ocr_born_digital` is set.
- OCR never creates blocks on text-layer pages.
- Output goes to `parse/ocr.json` (all pages, `OcrOutput`). Scanned pages' `ocr_alt` goes to `parse/ocr_alt.json`.
- Per-page partials go to `parse/.partial/<role>-p{page:03d}.json` while running (resumability), and are deleted after aggregation.

### 7.4 Attachment (`ocr_attach.attach_ocr(blocks, ocr: OcrOutput, text_layer) -> list[Block]`, pure)
- On text-layer pages, each OCR word goes to the block whose bbox (expanded 2 pt) contains the word center; with several such blocks, the smallest area wins (ties: lower reading_order).
- `block.ocr_words` = assigned words ordered by (line y0, line x0, word x0). `raw_text_by_parser["ocr"]` = those words, joined `" "` within an OCR line and `"\n"` between lines.
- Blocks with no assigned words get `ocr_words=[]` and `raw_text_by_parser["ocr"]=""`.
- On scanned pages `ocr_words` is set by the merge from the `raw_source` engine's words, so it is **never None on scanned blocks**.
- Module 3 computes `textlayer_vs_ocr` from `raw_text_by_parser["pymupdf"]` vs `["ocr"]` plus `ocr_words` confidences, with no re-OCR.

## 8. Ingest, DOCX, metadata

### 8.1 Ingest (`labor ingest <project> <files...>`, A)
Layout (paths only in `ProjectPaths`):
```
<project>/project.json                      ProjectConfig; created as ProjectConfig(name=<dir basename>) if missing
<project>/sources/<filename>                byte copy
<project>/docs/<slug>/document.json         Document (block_ids=[] until parsed)
<project>/docs/<slug>/parse/{pymupdf,docling,ocr,ocr_alt,docx}.json   ParserOutput / OcrOutput (only those that ran)
<project>/docs/<slug>/parse/{layout,merge,figures,state}.json
<project>/docs/<slug>/blocks.json           list[Block], sorted by reading_order
<project>/docs/<slug>/pages/p{page:03d}.png 300-DPI RGB render cache (ocr_dpi)
```
Per file:
1. Compute sha256.
2. If `sources/<filename>` exists with the same sha256, it is a no-op (`status: exists`). With a different sha256 it raises `IngestError` ("rename the file").
3. The same bytes under a new filename become a **new** doc (module 2's dedupe test needs this).
4. Slug = `make_unique_slug(doc_slug_from_filename(name), existing slugs)`.
5. Kind: a page **has a text layer** if it has ≥ 16 non-whitespace chars of *visible* text (chars from `page.get_texttrace()` with render mode ≠ 3).
   - `pages_without_text_layer` = those failing.
   - kind = `scanned_pdf` if more than half the pages fail, else `born_digital_pdf`. Routing is per page regardless (a mixed doc gets both routes).
   - `.docx` → `docx`, with `page_count = docx.count_virtual_pages(path)` (B).
   - Other extensions raise.
6. Metadata per §8.3. Then write document.json.

### 8.2 DOCX (`docx.py`, B)
- Walk `doc.element.body` children in order (`w:p`, `w:tbl`):
  - style `Heading N` → heading level N; `Title` → heading 1.
  - `List*` style or `w:numPr` → list item. Consecutive items become one list block, joined `"\n"` with no glyph.
  - `Caption` style or `CAPTION_RE` → caption.
  - Each `w:drawing` blip → a figure block (`docx_image_rid` = `r:embed`), emitted in run order, before or after the paragraph's text according to position.
  - `w:tbl` → table: spans from `gridSpan`/`vMerge`, i.e. identical `_tc` across grid positions.
  - Empty paragraphs → `Skipped(empty_paragraph)`.
- Virtual pages (00 §5): a new page begins after a `w:br w:type="page"` (text before the break stays on the current page) and after a paragraph whose `pPr` has `w:sectPr`, and after every 999th block. `bbox=None`.
- Second parser: Docling `DocumentConverter(allowed_formats=[InputFormat.DOCX])` (no models).
- Alignment: `difflib.SequenceMatcher` over the two lists of `hf_key`-normalized texts (autojunk off). `equal` and `replace` pairs with ratio ≥ 0.6 match. Unmatched docling items become `alone` blocks placed right after the preceding matched block (same virtual page). Merged lists use `split_text_by_alignment`.
- Output: `build_docx(path, slug, ctx) -> DocxResult(blocks: list[Block], outputs: list[ParserOutput], report: MergeReport, layout: list[PageLayout], figures: list[FigureCandidate], title: str|None)`. `count_virtual_pages(path) -> int`.

`split_text_by_alignment(whole: str, parts: Sequence[str]) -> list[str]` (`textalign.py`):
- Align `whole` against `"\n".join(parts)` with SequenceMatcher (autojunk off).
- Map each part's boundary through the matching blocks to a char offset in `whole`; unmatched boundaries interpolate linearly.
- Slices are stripped. Their concatenation equals `whole` modulo whitespace.

### 8.3 Metadata (`metadata.py`, A)
- **Title** (first hit wins):
  1. Title page: page 1 has ≤ 60 words and a line with size ≥ 1.4 × body; use the lines with the max size, joined `" "`, excluding `SECTION_RE` lines.
  2. PDF `metadata["title"]` / DOCX `core_properties.title`, accepted if ≥ 2 words, not matching `\.\w{2,4}\b`, and not starting with "Microsoft Word".
  3. LLM.
- **product_model:** `MODEL_RE = r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9][A-Z0-9-]{1,15}\b"`, searched first in `Model\s+<tok>` on page 1, then the title, then the filename stem (uppercased). If the token is in the title, the result is the title words up to and including it ("Acme X200 Service Manual" → "Acme X200"). Otherwise it is the token.
- **LLM fallback** (`providers.get(Task.metadata).chat(...)`):
  - Called only if title or product_model is still None. Input: page-1 text (≤ 2000 chars) and filename. `json_schema = {title: string|null, product_model: string|null}`, required, no extras.
  - **Validation:** a value is accepted only if its whitespace-collapsed casefold form is a substring of the page-1 text + filename (same normalization). Accepted product_model → `product_model_inferred=True`. Rejected or ProviderError → leave None, emit a warning line, ingest continues.
  - For scanned docs with nothing found at ingest, parse re-runs this using OCR page-1 text after merge.
- The MockProvider default returns nulls.

## 9. Tables (`tables.py`, B)
- `from_pymupdf(tab, page) -> TableCandidate`:
  - grid = `tab.row_count × tab.col_count`; text = `tab.extract()`.
  - A `None` cell is covered by a span. The span origin is the nearest non-None cell left (col_span) or above (row_span) whose `tab.rows[r].cells[c]` bbox contains the covered cell's center.
  - `header_rows = 1` if `tab.header.external is False`, else 0. Header row cells get `is_header=True`.
- `from_docling(item) -> TableCandidate`: one cell per `data.table_cells` entry, with `row=start_row_offset_idx`, spans = end − start, and `is_header=column_header`. Duplicates at the same origin are de-duplicated. Grid positions not covered by any cell get an empty-text cell.
- Empty-string cells are **kept** (this is how ragged rows appear).
- `table_raw_text(tc)` = per row, non-empty cell texts (inner newlines → space) joined `" | "`; rows joined `"\n"` (the same convention as GT `text`).
- `table_markdown(tc)` = GFM: row 0 is the header line, then `|---|` × n_cols, then the other rows. Span origins carry the text and covered cells are empty. `|` is escaped as `\|` and inner newlines become a space. The result is n_rows+1 lines, with no trailing newline.
- `to_table_data(primary, shapes) -> TableData`:
  - Primary structure = pymupdf if it saw a table on the region, else docling.
  - `shape_by_parser[k] = TableShape(rows, cols)` for each parser with a structure on the region. A parser whose text was absorbed but which had no structure there gets `TableShape(0, 0)` (an explicit disagreement for `table_consistency`).

## 10. CLI, idempotency, progress (`pipeline.py`, `cli.py`, A)
`labor parse <project> [--force] [--doc <slug>]`, for each doc in slug order:
- **Skip** if `state.json.complete` and `sha256`, `parser_versions` (current) and `config_fingerprint` all match.
  - `config_fingerprint = sha256(canonical_json({parsers, ocr_engine, ocr_dpi, background_ocr_born_digital, parse_algo}))`.
  - `PARSE_ALGO_VERSION = "1"`; bump it whenever merge, order, classify or header logic changes.
- **Stage reuse:** a parser output file is reused if its `parser`, `version` and `source_sha256` match.
- **Stages (PDF):** `render` → `ocr` (pool, async) ‖ `pymupdf` → `docling` → `ocr_alt` (no-text pages) → `merge` → `headers` → `order` → `ids` → `ocr_attach` → `metadata` → `write`.
- **DOCX:** `docx` → `write`.
- **Write order:** parse/*.json, then layout/merge/figures, then blocks.json, then document.json (block_ids, parser_versions, stripped_*, maybe title), then state.json `complete=true` last. All writes use `contracts.io.write_json` (atomic).
- **Progress:** one compact JSON line on stdout per stage per doc, `{"doc","stage","status":"done|skip|warning|error","pages","elapsed_ms","detail"}`, with sort_keys. Ingest prints `{"doc","status":"new|exists","kind","pages","file"}`.
- **Errors:** a failing doc prints `status:error` and the next doc continues. Exit code 1 if any doc failed.
- **IDs:** after ordering, page blocks get `block_id(slug, page, i+1)` and figure blocks get `figure_id(slug, page, k)` (k = rank among figures on the page). `reading_order` is a doc-global 0-based counter, page-major. More than 999 blocks on a page raises `ParseError` (never truncate).
- `numeric_tokens = re.findall(r"\d+(?:[.,]\d+)*", raw_text)` is set at parse. `has_numeric_spec`, signals, confidence and status are left at defaults for module 3.
- **ID dependencies:** "same bytes → same IDs" depends on sha256, `parser_versions` (pymupdf, docling and model refs, ocr engine and traineddata hash, ocr_alt, python-docx, `parse_algo`) and the config fingerprint. All of these are recorded in `Document.parser_versions`, which includes `parse_algo` and `config` (the fingerprint) entries.

## 11. Determinism and performance
| Source of nondeterminism | Elimination |
|---|---|
| dict/set iteration, `PYTHONHASHSEED` | Sets are never iterated. Every sort uses a total key ending in (parser, native order). JSON is written with sort_keys. The test re-parses in a subprocess with a different `PYTHONHASHSEED`. |
| Float noise (`264.0640000000001`) | `q()` = round 3 dp at the adapter boundary; IoU thresholds are applied to rounded values; contract round6 on output. Docling model regions are quantized to 0.5 pt. |
| Docling/torch | Fixed `num_threads=4`, `manual_seed(0)`, deterministic algorithms (warn_only). Primary text and bboxes on text pages come from PyMuPDF. |
| OCR threading | Tesseract `OMP_THREAD_LIMIT=1`; ORT `intra_op_num_threads=1`. |
| Parallel completion order | Results are collected by page index (`Executor.map`), never `as_completed`. |
| Process start | `multiprocessing.get_context("spawn")` (fork after torch import is unsafe on macOS). |
| Greedy matching ties | Key `(-iou, p.order, s.order)`. |
| Timestamps, abs paths | None in persisted files; elapsed time appears only on stdout. |

**Budget** (SPEC §9: 200-page born-digital < 5 min, LLM excluded; this design counts background OCR too):
- `W = max(1, min(4, cpu_count − 4))` pool workers (4 here); render and OCR run in the pool concurrently with in-process pymupdf and docling.
- Estimate for 200 pages: pymupdf + find_tables ≈ 30 s; docling ≈ 55 s (+5 s init); render 200 × 0.6 / 4 ≈ 30 s; tesseract 200 × 1.5 / 4 ≈ 75 s (overlapped).
- Wall ≈ 2.5 min, with headroom. Scanned (12 pages): render 2 s + OCR (2 engines) ≈ 12 s + docling init/run ≈ 10 s + python/torch import → ≈ 30 s, well under 90 s.
- If test 26 fails the budget, the first lever is `background_ocr_born_digital` running after `write` (blocks.json is available earlier, and module 7 can schedule it). It is not a lower DPI.

## 12. Test list (`tests/parse/`)
A session fixture (`parsed`, A, in `tests/parse/conftest.py`) copies the 6 fixtures into a tmp project with project-a's mock `project.json` plus `ocr_engine` per config, ingests and parses once. "Matching" = each GT block ↔ the parsed block on the same page with the highest bbox IoU ≥ 0.5 (greedy, unique). Tokens = `re.findall(r"[^\s|•]+", s)`, with GT side = `raw_lines` joined by `\n`.

| # | Owner | Fixture | Assertion |
|---|---|---|---|
| 1 | A | all 6 | `parse/` holds `pymupdf.json`+`docling.json` (5 PDFs), `ocr.json`+`ocr_alt.json` (scanned), `docx.json`+`docling.json` (DOCX). Each has ≥1 non-skipped candidate on ≥ 80% of pages (scanned: ocr, ocr_alt; docling ≥ 3 layout_only figures) |
| 2 | A | all 6 | Re-parse in a subprocess (`PYTHONHASHSEED=123`, fresh copy) → `blocks.json`, `document.json`, `parse/*.json`, layout/merge/figures byte-identical |
| 3 | A | all 6 | `Document.block_ids == [b.id for b in blocks.json]`, ordered by reading_order; `reading_order` = 0..n−1; per-page `n` = 1..k contiguous; all models validate |
| 4 | A | clean, twocol, tables, figures | header/footer blocks' page set == GT header/footer pages exactly; `stripped_headers == ["Acme X200 Service Manual"]`; `stripped_footers == sorted(f"Page {n}")` over the GT pages |
| 5 | A | scanned | header detected on ≥ 9 of 11 GT pages (reported; gate needs only #4) |
| 6 | A | clean, twocol, tables, figures | ≥ 98% of non-header/footer GT blocks are matched; micro token F1 (matched pairs, raw_text vs raw_lines) ≥ 0.98 per fixture |
| 7 | A | all 5 PDFs | no silent drops: each GT block's tokens have recall ≥ 0.98 (scanned ≥ 0.85) against the union of parsed blocks on its page whose bbox intersects it (scanned: GT bbox expanded 8 pt) |
| 8 | A | every PDF | every candidate in every `ParserOutput` appears exactly once in `merge.json`; every non-`skipped` disposition has a block_id in blocks.json; skipped reasons are in the allowed set |
| 9 | A | clean, twocol, tables, figures | matched type == GT type for ≥ 95% of blocks, and 100% for figure/table/header/footer; headings: `heading_level` and `section_number` == GT |
| 10 | A | twocol, clean | per page, the GT indices of matched blocks in parsed reading order are strictly increasing (column-major) |
| 11 | A | figures, clean, twocol | figure blocks' `figure_id`s == GT `expected_id` set; `figures.json` raster entries have an xref whose image size == `source_image`; vector entries `has_drawings`; twocol composite has both |
| 12 | A | scanned | the 3 GT figures each have an IoU ≥ 0.3 figure block with `raw_source="docling"`; no figure block covers ≥ 80% of the page |
| 13 | B | scanned | every non-figure block has non-empty `ocr_words` with confidences in [0,1], `raw_text_by_parser` has `ocr` and (when matched) `ocr_alt`; figure blocks have `ocr_words is not None` |
| 14 | B | clean | every non-figure block has `ocr_words` (non-empty) and `raw_text_by_parser["ocr"]`; token F1(pymupdf, ocr) ≥ 0.95 over the doc |
| 15 | B | clean p3 render | tesseract word bboxes are within 3 pt of `page.get_text("words")` boxes for ≥ 95% of matched words (px→pt scaling) |
| 16 | B | unit | rapidocr word mapping: synthetic fragments → whitespace tokens with min-conf and union bbox; concat mismatch → fragments |
| 17 | B | unit | `shutil.which` monkeypatched to None → roles swap, `parser_versions["ocr_alt"]=="unavailable"`, warning line emitted |
| 18 | B | tables | 6 table blocks; `n_rows`/`n_cols` == GT; ≥ 95% of cells' text == GT; table 4 has a cell with col_span 2; ragged table has empty cells and a row_span > 1; `shape_by_parser` has pymupdf and docling; markdown has n_rows+1 lines |
| 19 | B | unit | `table_markdown`/`table_raw_text` on hand-built spans and ragged rows; escaping of `|` |
| 20 | B | manual.docx | block sequence (type, page, text tokens F1 ≥ 0.98 each) == GT; figure ids `FIG-manual-p001-01`, `FIG-manual-p002-01`; table 4×3 with a header row; all bbox None; `raw_text_by_parser` has docx and docling on ≥ 80% of blocks |
| 21 | B | unit | virtual pages: explicit break mid-paragraph, section break, 1000 blocks → page 2 |
| 22 | B | unit | `split_text_by_alignment` exact on clean input; robust to a 2-char OCR typo; concatenation invariant (hypothesis) |
| 23 | A | unit | columns: 1 column, 2 columns + spanning heading, 3 columns, gutter 8 pt (no split); permuted input → same order |
| 24 | A | unit | headers: `Page 3`/`Page 4` share a key; < 3 pages → none; 12 pt y-jitter → none; OCR noise "Acme X2O0" clusters |
| 25 | A | unit | merge: 1:1; P-split-by-S; S-aligned-onto-P; unmatched both kept; table absorbs cell text; figure absorbs labels; shuffled candidates → identical output |
| 26 | A | `slow` synthetic | 200-page PDF built in-test from clean.pdf pages 2–12 repeated (`insert_pdf`), full pipeline incl. Docling and background OCR, wall < 300 s |
| 27 | A | `slow` scanned | `labor parse` subprocess on a project with only scanned.pdf: wall < 90 s |
| 28 | A | ingest | sha256 == CHECKSUMS; slug == `expected_slug`; re-ingest same file → `exists`; same bytes new name → new slug; same name new bytes → error; kinds: clean born_digital `[]`, scanned `scanned_pdf` `[1..12]`, mixed (clean p1–3 + scanned p4–6) born_digital `[4,5,6]`, docx `page_count==2` |
| 29 | A | ingest/metadata | title and product_model == GT for all 6 with mock providers, and inferred False; LLM path: text "Ranger Pro mower guide", canned `"Ranger Pro"` → inferred True; canned `"Foo 3000"` → rejected, None |
| 30 | A | docling unit | clean p2 heading docling bbox (BOTTOMLEFT t=720) → top-left y0 within 1 pt of GT 72.0; list items merge into GT list blocks |
| 31 | A | CLI | `labor ingest`/`parse` via CliRunner: every stdout line is JSON with required keys; 2nd run all `skip` and files byte-unchanged; `--force` → identical bytes |

Gate commands (into PROGRESS.md):
- `MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest -q tests/parse`
- `MANUALLABOR_REQUIRE_DOCLING=1 uv run pytest -q -m slow tests/parse`
- `uv run pytest -q`
- `uv run ruff check manuallabor tests && uv run mypy manuallabor`

## 13. Work split
| | A | B |
|---|---|---|
| Files | project.py, ingest.py, parse/{__init__,types,geometry,text,pdf_pymupdf,pdf_docling,render,layout,headers,classify,merge,metadata,pipeline}.py, cli.py, pyproject, mock registration, tests/parse/conftest.py, tests 1–12, 23–31 | parse/{tables,ocr,ocr_attach,textalign,docx}.py, tests 13–22 |
| Provides to the other | `types.py` and `geometry.py`/`text.py` **first** (verbatim from §2), `layout.group_lines_into_blocks`, `layout.detect_columns`, `classify.resolve_kind_guess(lines, body_size)` | `tables.from_pymupdf/from_docling/to_table_data/table_raw_text/table_markdown`; `ocr.build_engines(config) -> (ocr, ocr_alt\|None)`, `OcrEngineAdapter.ocr_page`, `ocr.ocr_page_to_parse(op, role, body_size)`; `ocr_attach.attach_ocr`; `textalign.split_text_by_alignment`; `docx.build_docx`, `docx.count_virtual_pages` |
| Consumes | B's table converters in the adapters; OCR adapters in `pipeline` (via `render` pool); `attach_ocr`; `build_docx` | A's types, geometry, layout, classify |

Until the other side lands, each implementer stubs the counterpart's signature exactly as written here. The orchestrator merges and runs the full test list.

## 14. Open issues (resolved with a choice)
1. **OCR default engine.** Measured Tesseract F1 0.99 vs RapidOCR 0.90 here. Choice: the design honours `config.ocr_engine`. Request to orchestrator (M1.0, before implementation): flip `ProjectConfig.ocr_engine` default to `tesseract`, regenerate schemas/types and project-a `project.json` + CHECKSUMS, and update C13. If declined, everything works with RapidOCR as primary and lower OCR text quality.
2. **`rapidocr_onnxruntime` 1.4.4 drops spaces.** Choice: use `rapidocr` 3.10 (already installed, bundled models, offline). Module 6 may drop the old dep.
3. **Scanned second parser.** Choice: Tesseract + RapidOCR as the two text readers, Docling layout-only for figures/tables. Not Docling+Tesseract, because that is the same engine and would hide errors.
4. **DOCX second parser.** SPEC requires two parsers for PDFs only, but the gate says "every fixture". Choice: Docling's DOCX backend (fast, no models) aligned by sequence.
5. **Invisible text layers** (scanned PDFs with OCR text, render mode 3). Choice: treated as no text layer in v1 (OCR route). The invisible text is ignored and noted in `detail` of the ingest line.
6. **Docling model drift.** HF `refs/main` hashes go into `parser_versions`; a changed hash is a new parse (00 §10.10), never silent reuse.
7. **`raw_text` for tables** uses the GT convention (`" | "` / `"\n"`). Module 5 cleanup must treat `|` separators as structure, not content.
8. **OCR language** is fixed to `eng` (no config field). Adding a language later is a config change plus a `parse_algo` bump.
9. **Word confidence for RapidOCR = min of fragments.** This is conservative (SPEC: `ocr_min` matters most); module 3 calibrates.
10. **> 999 blocks on a page** raises instead of widening, because `ids._check` caps n at 999.
11. **Background OCR inside the 5-minute budget.** It is counted, to be safe. If module 7 needs earlier block availability, `ocr_attach` can run after `write` (a pure function on blocks.json); this does not change any ID.
12. **Re-parse after review state exists** (module 7) would be destructive if versions changed. In module 1, `--force` is the only way to re-parse a complete doc; module 7 must guard it.
