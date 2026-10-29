"""Block type resolution (design 01-parse section 4.4)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from manuallabor.contracts.enums import BlockType
from manuallabor.parse.text import BULLETS, CAPTION_RE, SECTION_RE
from manuallabor.parse.types import Line

CAPTION_REGION_GAP_PT = 48.0
HEADING_MAX_LINES = 3
HEADING_MAX_WORDS = 25
HEADING_STRONG_FACTOR = 1.3
BODY_SIZE_TOL = 0.5


def body_size_of(lines: Iterable[Line]) -> float | None:
    """Char-weighted mode of line sizes, rounded to 0.5 pt."""
    weights: dict[float, int] = {}
    for ln in lines:
        if ln.size is None:
            continue
        key = round(ln.size * 2.0) / 2.0
        weights[key] = weights.get(key, 0) + len(ln.text.strip())
    if not weights:
        return None
    best = max(weights.values())
    return min(k for k, v in weights.items() if v == best)


def _starts_with_bullet(text: str) -> bool:
    t = text.lstrip()
    return len(t) >= 2 and t[0] in BULLETS and t[1].isspace()


def is_bullet_list(lines: Sequence[Line]) -> bool:
    """Every non-continuation line starts with a bullet glyph; continuations are indented."""
    if not lines or not _starts_with_bullet(lines[0].text):
        return False
    bullet_x0 = lines[0].bbox[0]
    for ln in lines:
        if _starts_with_bullet(ln.text):
            bullet_x0 = ln.bbox[0]
        elif ln.bbox[0] < bullet_x0 + 2.0:
            return False
    return True


def looks_like_heading(lines: Sequence[Line], text: str, body: float | None) -> bool:
    if body is None or not lines or len(lines) > HEADING_MAX_LINES:
        return False
    if len(text.split()) > HEADING_MAX_WORDS or text.rstrip().endswith("."):
        # "1. Safety" style numbering ends with a period only inside the text, not at the end
        return False
    for ln in lines:
        if ln.size is None:
            return False
        if not (ln.size >= body + 1.0 or (ln.bold and ln.size >= body)):
            return False
    return True


def resolve_kind_guess(lines: Sequence[Line], body_size: float | None) -> BlockType:
    """Advisory kind for OCR line groups (the merge re-classifies with full context)."""
    text = "\n".join(ln.text for ln in lines)
    if not text.strip():
        return BlockType.other
    if CAPTION_RE.match(text):
        return BlockType.caption
    if is_bullet_list(lines):
        return BlockType.list
    if looks_like_heading(lines, text, body_size):
        return BlockType.heading
    return BlockType.paragraph


@dataclass(frozen=True)
class Classified:
    type: BlockType
    heading_level: int | None = None
    section_number: str | None = None


@dataclass
class ClassifyInput:
    """What classify needs to know about one merged block."""

    page: int
    bbox: Sequence[float] | None
    region: str  # "text" | "table" | "figure"
    text: str
    lines: Sequence[Line]
    size: float | None
    bold: bool
    docling_kind: BlockType | None
    docling_level: int | None
    forced: BlockType | None = None  # header/footer from headers.py


def _caption_near_region(
    item: ClassifyInput, regions_by_page: dict[int, list[Sequence[float]]]
) -> bool:
    if item.bbox is None:
        return False
    for rb in regions_by_page.get(item.page, []):
        gap = max(0.0, item.bbox[1] - rb[3], rb[1] - item.bbox[3])
        if gap <= CAPTION_REGION_GAP_PT:
            return True
    return False


def _heading_allowed(
    it: ClassifyInput,
    body: float | None,
    page_has_body: dict[int, bool],
    page_max: dict[int, float],
) -> bool:
    """A heading candidate is numbered, or bold / clearly larger than body text; on a page with
    no body text (a title page) only the page's largest text may stand as an unnumbered heading."""
    if SECTION_RE.match(it.text.strip()):
        return True
    if body is None or it.size is None:
        return True  # no size evidence (DOCX): keep the parser's hint
    if not (it.bold or it.size >= HEADING_STRONG_FACTOR * body):
        return False
    if not page_has_body.get(it.page, True):
        return it.size >= page_max.get(it.page, it.size) - BODY_SIZE_TOL
    return True


def classify_blocks(items: Sequence[ClassifyInput], body: float | None) -> list[Classified]:
    """Apply the first-match rules, then derive heading level and section number."""
    regions_by_page: dict[int, list[Sequence[float]]] = {}
    for it in items:
        if it.region in ("table", "figure") and it.bbox is not None:
            regions_by_page.setdefault(it.page, []).append(it.bbox)

    page_has_body: dict[int, bool] = {}
    page_max: dict[int, float] = {}
    for it in items:
        if it.forced is not None or it.region != "text" or it.size is None or not it.text.strip():
            continue
        page_has_body.setdefault(it.page, False)
        page_max[it.page] = max(page_max.get(it.page, 0.0), it.size)
        if body is not None and abs(it.size - body) <= BODY_SIZE_TOL:
            page_has_body[it.page] = True

    stage1: list[tuple[BlockType, str | None]] = []  # (type, section_number)
    for it in items:
        if it.forced is not None:
            stage1.append((it.forced, None))
            continue
        if it.region == "table":
            stage1.append((BlockType.table, None))
            continue
        if it.region == "figure":
            stage1.append((BlockType.figure, None))
            continue
        text = it.text
        if not text.strip():
            stage1.append((BlockType.other, None))
            continue
        if CAPTION_RE.match(text) and (
            it.docling_kind == BlockType.caption or _caption_near_region(it, regions_by_page)
        ):
            stage1.append((BlockType.caption, None))
            continue
        if it.docling_kind == BlockType.list or is_bullet_list(it.lines):
            stage1.append((BlockType.list, None))
            continue
        if (
            it.docling_kind == BlockType.heading or looks_like_heading(it.lines, text, body)
        ) and _heading_allowed(it, body, page_has_body, page_max):
            stage1.append((BlockType.heading, None))
            continue
        if it.docling_kind in (BlockType.other,) and not it.lines:
            stage1.append((BlockType.other, None))
            continue
        stage1.append((BlockType.paragraph, None))

    # Heading levels: numbered headings by component count, others by size rank.
    heading_sizes = sorted(
        {
            round(it.size * 2.0) / 2.0
            for it, (t, _) in zip(items, stage1, strict=True)
            if t == BlockType.heading and it.size is not None
        },
        reverse=True,
    )
    out: list[Classified] = []
    for it, (t, _) in zip(items, stage1, strict=True):
        if t != BlockType.heading:
            out.append(Classified(t))
            continue
        m = SECTION_RE.match(it.text.strip())
        if m:
            number = m.group(1)
            level = min(6, number.count(".") + 1)
            out.append(Classified(t, level, number))
            continue
        if it.size is not None and heading_sizes:
            level = heading_sizes.index(round(it.size * 2.0) / 2.0) + 1
        else:
            level = it.docling_level or 1
        out.append(Classified(t, max(1, min(6, level)), None))
    return out
