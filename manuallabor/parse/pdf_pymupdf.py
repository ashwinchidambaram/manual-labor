"""PyMuPDF adapter (design 01-parse section 4.1)."""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from manuallabor.contracts.enums import BlockType
from manuallabor.parse import geometry as g
from manuallabor.parse.types import (
    Line,
    PageParse,
    ParseContext,
    ParserOutput,
    RawBlock,
    Skipped,
    TableCandidate,
)

NAME = "pymupdf"
MIN_REGION_PT = 24.0
SPLIT_SIZE_DELTA = 1.0
SPLIT_GAP_FACTOR = 1.5


def _import() -> Any:
    import pymupdf

    return pymupdf


def pm() -> Any:
    return _import()


def open_pdf(path: Path) -> Any:
    return _import().open(str(path))


def pymupdf_version() -> str:
    pm = _import()
    return f"{pm.version[0]}; mupdf={pm.version[1]}"


def _line_from_dict(line: dict[str, Any], native_id: str) -> Line | None:
    spans = line.get("spans", [])
    text = "".join(s["text"] for s in spans).rstrip()
    if not text.strip():
        return None
    # dominant span = most chars (first wins on ties)
    best: dict[str, Any] | None = None
    best_n = -1
    for s in spans:
        n = len(s["text"].strip())
        if n > best_n:
            best, best_n = s, n
    assert best is not None
    bold = bool(best["flags"] & 16) or "bold" in str(best["font"]).lower()
    return Line(
        text=text,
        bbox=g.qbox(line["bbox"]),
        size=g.q(best["size"]),
        bold=bold,
        native_id=native_id,
    )


def _split_block(lines: list[Line]) -> list[list[Line]]:
    if len(lines) <= 1:
        return [lines]
    heights = [ln.bbox[3] - ln.bbox[1] for ln in lines]
    med_h = statistics.median(heights)
    groups: list[list[Line]] = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:], strict=False):
        gap = cur.bbox[1] - prev.bbox[3]
        size_p = prev.size if prev.size is not None else 0.0
        size_c = cur.size if cur.size is not None else 0.0
        if (
            abs(size_c - size_p) > SPLIT_SIZE_DELTA
            or cur.bold != prev.bold
            or gap > SPLIT_GAP_FACTOR * med_h
        ):
            groups.append([cur])
        else:
            groups[-1].append(cur)
    return groups


def _block_from_lines(lines: list[Line], page: int, order: int) -> RawBlock:
    sizes: dict[float, int] = {}
    for ln in lines:
        if ln.size is not None:
            sizes[ln.size] = sizes.get(ln.size, 0) + len(ln.text.strip())
    size = max(sorted(sizes), key=lambda k: sizes[k]) if sizes else None
    bold = sum(len(ln.text) for ln in lines if ln.bold) * 2 > sum(len(ln.text) for ln in lines)
    return RawBlock(
        parser=NAME,
        page=page,
        order=order,
        bbox=g.union([ln.bbox for ln in lines]),
        kind=BlockType.paragraph,
        text="\n".join(ln.text for ln in lines),
        lines=lines,
        size=size,
        bold=bold,
    )


def _cluster_boxes(pm: Any, page: Any) -> list[list[float]]:
    return [g.qbox(tuple(r)) for r in page.cluster_drawings()]


def _find_tables(page: Any, page_no: int) -> list[tuple[list[float], TableCandidate | None]]:
    try:
        from manuallabor.parse import tables as tables_mod
    except ImportError:
        return []
    out: list[tuple[list[float], TableCandidate | None]] = []
    try:
        found = page.find_tables(strategy="lines")
    except Exception:  # pragma: no cover - PyMuPDF internal failure on odd pages
        return []
    for tab in found.tables:
        cand = tables_mod.from_pymupdf(tab, page)
        out.append((g.qbox(tab.bbox), cand))
    return out


def _regions(
    page: Any,
    page_no: int,
    page_w: float,
    page_h: float,
    has_text: bool,
    table_boxes: list[list[float]],
) -> tuple[list[RawBlock], list[Skipped]]:
    """Figure candidates (raster + vector, merged) and skipped regions."""
    skipped: list[Skipped] = []
    page_box = [0.0, 0.0, page_w, page_h]
    page_area = g.area(page_box)
    images: list[tuple[list[float], int]] = []
    for info in page.get_image_info(xrefs=True):
        box = g.qbox(info["bbox"])
        clipped = [
            max(0.0, box[0]),
            max(0.0, box[1]),
            min(page_w, box[2]),
            min(page_h, box[3]),
        ]
        if g.width(clipped) < MIN_REGION_PT or g.height(clipped) < MIN_REGION_PT:
            continue
        if not has_text and g.area(clipped) >= 0.8 * page_area:
            skipped.append(Skipped(page=page_no, order=0, bbox=clipped, reason="scan_background"))
            continue
        images.append((clipped, int(info.get("xref", 0))))
    drawings: list[list[float]] = []
    for box in _cluster_boxes(None, page):
        if g.width(box) < MIN_REGION_PT or g.height(box) < MIN_REGION_PT:
            skipped.append(Skipped(page=page_no, order=0, bbox=box, reason="tiny_drawing"))
            continue
        if any(g.contain(box, tb) >= 0.5 for tb in table_boxes):
            skipped.append(Skipped(page=page_no, order=0, bbox=box, reason="table_rule"))
            continue
        drawings.append(box)

    # Union-find over images + drawings with IoU >= 0.3 or containment >= 0.8.
    items: list[tuple[list[float], int | None]] = [(b, x) for b, x in images] + [
        (b, None) for b in drawings
    ]
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i][0], items[j][0]
            if g.iou(a, b) >= 0.3 or g.contain(a, b) >= 0.8 or g.contain(b, a) >= 0.8:
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    figs: list[RawBlock] = []
    for members in groups.values():
        boxes = [items[m][0] for m in members]
        xrefs = sorted({x for m in members if (x := items[m][1]) is not None})
        has_dr = any(items[m][1] is None for m in members)
        figs.append(
            RawBlock(
                parser=NAME,
                page=page_no,
                order=0,
                bbox=g.union(boxes),
                kind=BlockType.figure,
                text="",
                image_xrefs=xrefs,
                has_drawings=has_dr,
            )
        )
    figs.sort(key=lambda b: (b.bbox[1], b.bbox[0]) if b.bbox else (0, 0))
    return figs, skipped


def _assign_orders(texts: list[RawBlock], regions: list[RawBlock]) -> list[RawBlock]:
    """Native text order, with each region inserted before the first piece starting below it."""
    seq: list[RawBlock] = list(texts)
    for r in sorted(regions, key=lambda b: (b.bbox[1], b.bbox[0]) if b.bbox else (0, 0)):
        idx = len(seq)
        for k, t in enumerate(seq):
            if t.parser == NAME and t.kind != BlockType.paragraph:
                continue
            if t.bbox and r.bbox and t.bbox[1] >= r.bbox[1] - 0.5:
                idx = k
                break
        seq.insert(idx, r)
    return [b.model_copy(update={"order": i}) for i, b in enumerate(seq)]


class PyMuPdfAdapter:
    name = NAME

    def version(self) -> str:
        return pymupdf_version()

    def parse_pdf(self, path: Path, ctx: ParseContext) -> ParserOutput:
        pm = _import()
        flags = pm.TEXT_PRESERVE_LIGATURES | pm.TEXT_PRESERVE_WHITESPACE | pm.TEXT_MEDIABOX_CLIP
        pages: list[PageParse] = []
        with pm.open(path) as doc:
            for idx in range(doc.page_count):
                page_no = idx + 1
                page = doc[idx]
                w, h = ctx.page_sizes[idx]
                has_text = ctx.text_layer[idx]
                skipped: list[Skipped] = []
                texts: list[RawBlock] = []
                regions: list[RawBlock] = []
                if has_text:
                    order = 0
                    d = page.get_text("dict", flags=flags, sort=False)
                    for bi, blk in enumerate(d["blocks"]):
                        if blk.get("type") != 0:
                            continue
                        lines: list[Line] = []
                        for li, ln in enumerate(blk.get("lines", [])):
                            line = _line_from_dict(ln, f"b{bi}.l{li}")
                            if line is not None:
                                lines.append(line)
                            else:
                                skipped.append(
                                    Skipped(
                                        page=page_no,
                                        order=bi,
                                        bbox=g.qbox(ln["bbox"]),
                                        reason="empty_text",
                                    )
                                )
                        if not lines:
                            continue
                        for grp in _split_block(lines):
                            texts.append(_block_from_lines(grp, page_no, order))
                            order += 1
                    tabs = _find_tables(page, page_no)
                    table_boxes = [b for b, _ in tabs]
                    for bbox, cand in tabs:
                        if cand is None:
                            continue
                        regions.append(
                            RawBlock(
                                parser=NAME,
                                page=page_no,
                                order=0,
                                bbox=bbox,
                                kind=BlockType.table,
                                text="",
                                table=cand,
                            )
                        )
                else:
                    table_boxes = []
                figs, sk = _regions(page, page_no, w, h, has_text, table_boxes)
                skipped.extend(sk)
                if has_text:
                    regions.extend(figs)
                blocks = _assign_orders(texts, regions)
                # skipped candidates get orders after the blocks so (page, order) stays unique
                skipped = [
                    sk.model_copy(update={"order": len(blocks) + k}) for k, sk in enumerate(skipped)
                ]
                pages.append(
                    PageParse(
                        page=page_no,
                        width=w,
                        height=h,
                        has_text_layer=has_text,
                        blocks=blocks,
                        skipped=skipped,
                    )
                )
        return ParserOutput(
            parser=NAME, version=self.version(), source_sha256=ctx.sha256, pages=pages
        )
