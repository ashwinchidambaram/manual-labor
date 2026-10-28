"""Assign background-OCR words to born-digital blocks (design section 7.4). Pure."""

from __future__ import annotations

from collections.abc import Sequence

from manuallabor.contracts.block import Block, OcrWord
from manuallabor.parse.geometry import area, center, contains_point, expand
from manuallabor.parse.types import Line, OcrOutput

_PAD = 2.0


def _pick(blocks: Sequence[Block], x: float, y: float) -> Block | None:
    """Smallest-area block containing the point (expanded 2 pt); ties go to lower reading_order."""
    best: Block | None = None
    best_key: tuple[float, int, str] | None = None
    for b in blocks:
        if b.bbox is None or not contains_point(expand(b.bbox, _PAD), x, y):
            continue
        key = (area(b.bbox), b.reading_order, b.id)
        if best_key is None or key < best_key:
            best, best_key = b, key
    return best


def _word_center(w: OcrWord, line: Line) -> tuple[float, float]:
    return center(w.bbox if w.bbox is not None else line.bbox)


def attach_ocr(blocks: Sequence[Block], ocr: OcrOutput, text_layer: Sequence[bool]) -> list[Block]:
    """Return blocks with ``ocr_words`` / ``raw_text_by_parser["ocr"]`` set on text-layer pages.

    ``text_layer[page - 1]`` says whether the page has a text layer. Blocks on scanned pages are
    returned unchanged (the merge sets their ocr_words). Pages absent from ``ocr`` are untouched.
    """
    pages = {p.page: p for p in ocr.pages}
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)

    # block id -> list of (line y0, line x0, line index, word x0, word)
    assigned: dict[str, list[tuple[float, float, int, float, OcrWord]]] = {}
    for page_no in sorted(by_page):
        has_layer = text_layer[page_no - 1] if 0 < page_no <= len(text_layer) else False
        op = pages.get(page_no)
        if not has_layer or op is None:
            continue
        cands = by_page[page_no]
        for li, line in enumerate(op.lines):
            for w in line.words:
                cx, cy = _word_center(w, line)
                target = _pick(cands, cx, cy)
                if target is None:
                    continue
                wx0 = w.bbox[0] if w.bbox is not None else line.bbox[0]
                assigned.setdefault(target.id, []).append((line.bbox[1], line.bbox[0], li, wx0, w))

    out: list[Block] = []
    for b in blocks:
        op = pages.get(b.page)
        has_layer = text_layer[b.page - 1] if 0 < b.page <= len(text_layer) else False
        if not has_layer or op is None:
            out.append(b)
            continue
        items = sorted(assigned.get(b.id, []), key=lambda t: (t[0], t[1], t[2], t[3]))
        words = [t[4] for t in items]
        rows: list[list[str]] = []
        last_line: int | None = None
        for _, _, li, _, w in items:
            if li != last_line:
                rows.append([])
                last_line = li
            rows[-1].append(w.text)
        text = "\n".join(" ".join(r) for r in rows)
        by_parser = dict(b.raw_text_by_parser)
        by_parser["ocr"] = text
        out.append(b.model_copy(update={"ocr_words": words, "raw_text_by_parser": by_parser}))
    return out
