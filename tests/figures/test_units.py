"""Unit tests on synthetic inputs (design 12, tests 16-21 and the synthetic parts of 17-18)."""

from __future__ import annotations

import io
import re
import struct
from typing import Any

import pymupdf
from PIL import Image

from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import AttachRule, BlockStatus, BlockType, Extraction
from manuallabor.contracts.figure import FigureRecord
from manuallabor.figures.captions import find_captions
from manuallabor.figures.decide import decide
from manuallabor.figures.dedupe import DedupeItem, dedupe, hamming, phash_hex
from manuallabor.figures.encode import encode_png
from manuallabor.figures.page_content import load_page_content
from manuallabor.figures.pipeline import extract_pdf_figure
from manuallabor.figures.sidecar import build_record
from manuallabor.figures.types import DedupeEntry, FigureExtraction


def gradient(w: int = 60, h: int = 40) -> Image.Image:
    im = Image.new("RGB", (w, h))
    im.putdata([(x * 4 % 256, y * 6 % 256, 128) for y in range(h) for x in range(w)])
    return im


def png_bytes(im: Image.Image) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def new_doc() -> tuple[Any, Any]:
    doc = pymupdf.open()
    return doc, doc.new_page(width=612, height=792)


RECT = pymupdf.Rect(100, 100, 220, 180)
BOX = [100.0, 100.0, 220.0, 180.0]


def decision_for(doc: Any, bbox: list[float]) -> Any:
    pc = load_page_content(doc, doc[0], has_text_layer=True)
    return decide(bbox, pc)


# ---- test 17: decide -------------------------------------------------------------------------


def test_17_image_with_text_overlay() -> None:
    doc, page = new_doc()
    page.insert_image(RECT, stream=png_bytes(gradient()))
    page.insert_text((110, 140), "OVERLAY LABEL", fontsize=12)
    d = decision_for(doc, BOX)
    assert (d.method, d.reason) == (Extraction.crop, "image_with_text")
    out = extract_pdf_figure(doc, 0, BOX)
    assert out.method == Extraction.crop and out.crop_source == "render"


def test_17_two_images_in_region() -> None:
    doc, page = new_doc()
    page.insert_image(pymupdf.Rect(100, 100, 160, 180), stream=png_bytes(gradient()))
    page.insert_image(pymupdf.Rect(160, 100, 220, 180), stream=png_bytes(gradient()))
    d = decision_for(doc, BOX)
    assert (d.method, d.reason) == (Extraction.crop, "multiple_images")
    # the same xref drawn twice counts as two placements
    doc2, page2 = new_doc()
    xref = page2.insert_image(pymupdf.Rect(100, 100, 160, 180), stream=png_bytes(gradient()))
    page2.insert_image(pymupdf.Rect(160, 100, 220, 180), xref=xref)
    assert decision_for(doc2, BOX).reason == "multiple_images"


def test_17_clip_path_gives_render_disagreement() -> None:
    doc, page = new_doc()
    dark = Image.new("RGB", (60, 40), (10, 10, 10))
    page.insert_image(RECT, stream=png_bytes(dark))
    xref = page.get_contents()[0]
    stream = doc.xref_stream(xref)
    # clip to the left half of the image (PDF space: y is flipped, 792 - 180 = 612)
    doc.update_stream(xref, b"q 100 612 60 80 re W n\n" + stream + b"\nQ\n")
    d = decision_for(doc, BOX)
    assert (d.method, d.reason) == (Extraction.native, "single_image")  # rule 12 still to run
    out = extract_pdf_figure(doc, 0, BOX)
    assert out.method == Extraction.crop and out.reason == "render_disagreement"


def test_17_partial_cover() -> None:
    doc, page = new_doc()
    page.insert_image(RECT, stream=png_bytes(gradient()))
    half = [100.0, 100.0, 160.0, 180.0]  # the region covers only the left half of the image
    d = decision_for(doc, half)
    assert (d.method, d.reason) == (Extraction.crop, "image_partial_cover")
    out = extract_pdf_figure(doc, 0, half)
    assert out.crop_source == "raster"  # one image covers the region: sub-crop its pixels
    assert out.image.size == (31, 40) or abs(out.image.width - 31) <= 2


def test_17_frame_and_background_do_not_block_native() -> None:
    doc, page = new_doc()
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))  # white page background
    page.insert_image(RECT, stream=png_bytes(gradient()))
    page.draw_rect(RECT, color=(0.5, 0.5, 0.5), width=1)  # frame around the image
    d = decision_for(doc, BOX)
    assert (d.method, d.reason) == (Extraction.native, "single_image")
    assert extract_pdf_figure(doc, 0, BOX).method == Extraction.native


def test_17_text_only_region_is_no_content() -> None:
    doc, page = new_doc()
    page.insert_text((110, 140), "just words", fontsize=12)
    d = decision_for(doc, BOX)
    assert (d.method, d.reason) == (Extraction.crop, "no_content")


def test_17_path_crossing_margin() -> None:
    doc, page = new_doc()
    page.draw_rect(pymupdf.Rect(110, 110, 200, 170), color=(0, 0, 0), width=1)
    page.draw_line((150, 140), (400, 140), color=(0, 0, 0), width=1)
    d = decision_for(doc, BOX)
    assert (d.method, d.reason) == (Extraction.crop, "vector_crossing_paths")
    # without the crossing line the same region is vector
    doc2, page2 = new_doc()
    page2.draw_rect(pymupdf.Rect(110, 110, 200, 170), color=(0, 0, 0), width=1)
    assert decision_for(doc2, BOX).reason == "vector_only"


def test_17_scanned_page_and_docx_rules() -> None:
    doc, _ = new_doc()
    pc = load_page_content(doc, doc[0], has_text_layer=False)
    assert decide(BOX, pc).reason == "scanned_page"
    assert decide(None, pc).reason == "docx_image"


# ---- test 18: native colour handling ---------------------------------------------------------


def test_18_cmyk_jpeg() -> None:
    cm = Image.new("CMYK", (60, 40))
    cm.putdata([(x * 4 % 256, y * 6 % 256, 30, 20) for y in range(40) for x in range(60)])
    b = io.BytesIO()
    cm.save(b, "JPEG", quality=95)
    doc, page = new_doc()
    page.insert_image(RECT, stream=b.getvalue())
    out = extract_pdf_figure(doc, 0, BOX)
    assert out.method == Extraction.native, out.reason
    assert out.source_format == "jpeg" and out.image.mode == "RGB"
    assert out.mad is not None and out.mad <= 3.0


def test_18_smask_alpha_preserved() -> None:
    src = gradient().convert("RGBA")
    alpha = Image.new("L", src.size)
    alpha.putdata([max(60, (x * 4) % 256) for y in range(40) for x in range(60)])
    src.putalpha(alpha)
    doc, page = new_doc()
    page.insert_image(RECT, stream=png_bytes(src))
    out = extract_pdf_figure(doc, 0, BOX)
    assert out.method == Extraction.native, out.reason
    assert out.image.mode == "RGBA"
    assert out.image.getchannel("A").tobytes() == alpha.tobytes()


def test_18_gray_stays_gray() -> None:
    g = Image.new("L", (60, 40))
    g.putdata([(x * 4 + y) % 256 for y in range(40) for x in range(60)])
    doc, page = new_doc()
    page.insert_image(RECT, stream=png_bytes(g))
    out = extract_pdf_figure(doc, 0, BOX)
    assert out.method == Extraction.native and out.image.mode == "L"
    assert out.image.tobytes() == g.tobytes()


def test_18_flipped_placement() -> None:
    src = gradient()
    doc, page = new_doc()
    page.insert_image(RECT, stream=png_bytes(src))
    xref = page.get_contents()[0]
    stream = doc.xref_stream(xref)
    assert b"120 0 0 80 100 612 cm" in stream
    doc.update_stream(xref, stream.replace(b"120 0 0 80 100 612 cm", b"-120 0 0 80 220 612 cm"))
    out = extract_pdf_figure(doc, 0, BOX)
    assert out.method == Extraction.native, out.reason
    assert out.image.tobytes() == src.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()


# ---- test 16: captions -----------------------------------------------------------------------


def blk(
    n: int,
    typ: BlockType,
    bbox: list[float] | None,
    *,
    page: int = 1,
    text: str = "",
    fig: bool = False,
) -> Block:
    return Block(
        id=f"b-d-p{page:03d}-{n:02d}",
        doc_id="d",
        page=page,
        bbox=bbox,
        type=typ,
        reading_order=page * 100 + n,
        raw_text=text,
        raw_source="pymupdf",
        figure_id=f"FIG-d-p{page:03d}-{n:02d}" if fig else None,
    )


F1 = [72.0, 100.0, 300.0, 250.0]


def test_16_below_beats_above() -> None:
    blocks = [
        blk(1, BlockType.caption, [72, 60, 300, 90], text="Above."),
        blk(2, BlockType.figure, F1, fig=True),
        blk(3, BlockType.caption, [72, 252, 300, 270], text="Below."),
    ]
    m = find_captions(blocks)
    assert m["FIG-d-p001-02"].text == "Below."


def test_16_caption_claimed_once() -> None:
    blocks = [
        blk(1, BlockType.figure, F1, fig=True),
        blk(2, BlockType.caption, [72, 252, 300, 270], text="Cap."),
        blk(3, BlockType.figure, [72, 280, 300, 400], fig=True),
    ]
    m = find_captions(blocks)
    assert list(m) == ["FIG-d-p001-01"]


def test_16_gap_overlap_and_header_footer() -> None:
    far = [blk(1, BlockType.figure, F1, fig=True), blk(2, BlockType.caption, [72, 320, 300, 340])]
    assert find_captions(far) == {}
    side = [blk(1, BlockType.figure, F1, fig=True), blk(2, BlockType.caption, [320, 252, 500, 270])]
    assert find_captions(side) == {}
    skip = [
        blk(1, BlockType.figure, F1, fig=True),
        blk(2, BlockType.footer, [72, 760, 300, 780], text="Page 1"),
        blk(3, BlockType.caption, [72, 252, 300, 270], text="Cap."),
    ]
    assert find_captions(skip)["FIG-d-p001-01"].block_id == "b-d-p001-03"


def test_16_trim_fused_caption() -> None:
    blocks = [
        blk(1, BlockType.figure, F1, fig=True),
        blk(
            2, BlockType.caption, [72, 252, 300, 270], text="Figure 2. Idler pulley\nKeep the belt."
        ),
        blk(3, BlockType.figure, [72, 300, 300, 400], page=1, fig=True),
    ]
    assert find_captions(blocks)["FIG-d-p001-01"].trimmed is False
    fused = [
        blk(1, BlockType.figure, F1, fig=True),
        blk(2, BlockType.caption, [72, 252, 300, 270], text="Figure 2. Idler positions.\nKeep th"),
    ]
    m = find_captions(fused)["FIG-d-p001-01"]
    assert (m.text, m.trimmed) == ("Figure 2. Idler positions.", True)


# ---- test 19: dedupe -------------------------------------------------------------------------


def hx(v: int) -> str:
    return f"{v:016x}"


def item(
    fid: str,
    ph: int,
    *,
    method: Extraction = Extraction.native,
    size: tuple[int, int] = (600, 400),
    sha: str | None = None,
    blank: bool = False,
    svg: str | None = None,
) -> DedupeItem:
    return DedupeItem(
        figure_id=fid,
        source_doc=fid.split("-")[1],
        method=method,
        width=size[0],
        height=size[1],
        png_sha256=sha or (fid.encode().hex() * 8)[:64],
        svg_sha256=svg,
        phash=hx(ph),
        blank=blank,
    )


def by_id(entries: list[DedupeEntry]) -> dict[str, DedupeEntry]:
    return {e.figure_id: e for e in entries}


def test_19_no_chaining() -> None:
    a = 0
    b = 0b111111  # d(a,b) = 6
    c = 0b111111_111111  # d(b,c) = 6, d(a,c) = 12
    assert (hamming(hx(a), hx(b)), hamming(hx(b), hx(c)), hamming(hx(a), hx(c))) == (6, 6, 12)
    e = by_id(
        dedupe([item("FIG-a-p001-01", a), item("FIG-b-p001-01", b), item("FIG-c-p001-01", c)])
    )
    assert e["FIG-b-p001-01"].duplicate_of == "FIG-a-p001-01" and e["FIG-b-p001-01"].kind == "near"
    assert e["FIG-c-p001-01"].duplicate_of is None


def test_19_vector_never_dups_native_and_blank_never_near() -> None:
    sha = "ab" * 32
    e = by_id(
        dedupe(
            [
                item("FIG-a-p001-01", 5, sha=sha),
                item("FIG-b-p001-01", 5, method=Extraction.vector, sha=sha, svg="cd" * 32),
            ]
        )
    )
    assert e["FIG-b-p001-01"].duplicate_of is None
    e2 = by_id(dedupe([item("FIG-a-p001-01", 5, blank=True), item("FIG-b-p001-01", 5, blank=True)]))
    assert e2["FIG-b-p001-01"].duplicate_of is None
    # identical blank pixels are still exact duplicates
    sha2 = "ef" * 32
    e3 = by_id(
        dedupe(
            [
                item("FIG-a-p001-01", 5, blank=True, sha=sha2),
                item("FIG-b-p001-01", 5, blank=True, sha=sha2),
            ]
        )
    )
    assert e3["FIG-b-p001-01"].kind == "exact"


def test_19_canonical_order() -> None:
    sha = "12" * 32
    e = by_id(
        dedupe(
            [
                item("FIG-a-p001-01", 0, method=Extraction.crop, sha=sha),
                item("FIG-b-p001-01", 0, method=Extraction.native, sha=sha),
            ]
        )
    )
    assert e["FIG-a-p001-01"].duplicate_of == "FIG-b-p001-01"
    e = by_id(
        dedupe(
            [
                item("FIG-a-p001-01", 0, size=(300, 200)),
                item("FIG-b-p001-01", 1, size=(600, 400)),
            ]
        )
    )
    assert e["FIG-a-p001-01"].duplicate_of == "FIG-b-p001-01" and e["FIG-a-p001-01"].kind == "near"
    # aspect ratio differing by more than 5% blocks near duplicates
    e = by_id(dedupe([item("FIG-a-p001-01", 0), item("FIG-b-p001-01", 1, size=(600, 300))]))
    assert e["FIG-b-p001-01"].duplicate_of is None


# ---- test 20: encoding -----------------------------------------------------------------------


def chunk_types(data: bytes) -> list[str]:
    pos, out = 8, []
    while pos < len(data):
        (n,) = struct.unpack(">I", data[pos : pos + 4])
        out.append(data[pos + 4 : pos + 8].decode())
        pos += 12 + n
    return out


def test_20_encode_and_phash() -> None:
    im = gradient()
    a, b = encode_png(im), encode_png(im.copy())
    assert a == b
    types = chunk_types(a)
    assert "tEXt" not in types and "pHYs" not in types and "iTXt" not in types
    h = phash_hex(im)
    assert re.fullmatch(r"[0-9a-f]{16}", h)
    assert phash_hex(im.convert("RGBA")) == h


# ---- test 21: sidecar rewrite ----------------------------------------------------------------


def test_21_rewrite_preserves_downstream_fields() -> None:
    fid = "FIG-d-p001-01"
    doc = Document(
        slug="d",
        sha256="0" * 64,
        filename="d.pdf",
        kind="born_digital_pdf",
        page_count=1,
        block_ids=[],
        product_model="Acme X200",
    )
    ext = FigureExtraction(
        figure_id=fid,
        block_id="b-d-p001-01",
        page=1,
        bbox=[1, 2, 3, 4],
        method=Extraction.native,
        reason="single_image",
        png_sha256="a" * 64,
        width=10,
        height=10,
        phash="0" * 16,
    )
    entry = DedupeEntry(figure_id=fid, source_doc="d")
    fresh = build_record(ext, doc, entry, None)
    assert (fresh.confidence, fresh.review, fresh.attach_rule) == (
        1.0,
        BlockStatus.queued,
        AttachRule.none,
    )
    assert fresh.product_model == "Acme X200"
    edited = FigureRecord.model_validate(
        {
            **fresh.model_dump(mode="json"),
            "description_generated": "A belt.",
            "tags": ["belt", "idler"],
            "articles": ["d--belts"],
            "attach_rule": "caption_ref",
            "confidence": 0.42,
            "review": "approved",
        }
    )
    again = build_record(ext, doc, entry, edited)
    for k in ("description_generated", "tags", "articles", "attach_rule", "confidence", "review"):
        assert getattr(again, k) == getattr(edited, k), k
    assert again.file == f"{fid}.png" and again.svg is None
