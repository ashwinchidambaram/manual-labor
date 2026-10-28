"""DOCX adapter: python-docx primary, Docling DOCX backend secondary (design section 8.2)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from importlib import metadata
from pathlib import Path
from typing import Any

from docx import Document as load_docx
from docx.oxml.ns import qn

from manuallabor import ids
from manuallabor.contracts.block import Block, TableCell, TableShape
from manuallabor.contracts.enums import BlockType
from manuallabor.parse.tables import (
    from_docling,
    shape_of,
    table_raw_text,
    to_table_data,
)
from manuallabor.parse.text import CAPTION_RE, SECTION_RE, hf_key, numeric_tokens
from manuallabor.parse.textalign import split_text_by_alignment
from manuallabor.parse.types import (
    Disposition,
    FigureCandidate,
    MergeReport,
    PageLayout,
    PageParse,
    ParserOutput,
    RawBlock,
    Skipped,
    TableCandidate,
)

MAX_BLOCKS_PER_PAGE = 999
NOMINAL_PAGE = (612.0, 792.0)
_MATCH_RATIO = 0.6
_WS = re.compile(r"[ \t\r\f\v]+")


class DocxError(ValueError):
    """Raised when a DOCX cannot be represented (e.g. more than 999 blocks on a virtual page)."""


# --------------------------------------------------------------------------- python-docx pass


@dataclass
class _Item:
    """A block-level item before page assignment."""

    kind: BlockType
    text: str
    style: str
    heading_level: int | None = None
    table: TableCandidate | None = None
    rid: str | None = None
    break_before: bool = False  # a page break precedes this item
    break_after: bool = False  # a section break follows the paragraph that produced this item
    skipped: bool = False
    list_item: bool = False


@dataclass
class DocxParse:
    pages: list[PageParse]
    items_by_page: list[list[RawBlock]] = field(default_factory=list)
    title: str | None = None


def _style_name(p: Any) -> str:
    try:
        return str(p.style.name or "")
    except Exception:  # noqa: BLE001 - python-docx raises KeyError for dangling style ids
        return ""


def _heading_level(style: str) -> int | None:
    s = style.strip()
    m = re.match(r"^Heading\s+(\d+)$", s, flags=re.IGNORECASE)
    if m:
        return max(1, min(6, int(m.group(1))))
    if s.lower() == "title":
        return 1
    return None


def _is_list(p_el: Any, style: str) -> bool:
    if style.lower().startswith("list"):
        return True
    ppr = p_el.find(qn("w:pPr"))
    return ppr is not None and ppr.find(qn("w:numPr")) is not None


def _cell_text(tc: Any) -> str:
    paras = []
    for p in tc.findall(qn("w:p")):
        paras.append(_para_text(p))
    return "\n".join(t for t in paras if t.strip()).strip()


def _para_text(p_el: Any) -> str:
    out: list[str] = []
    for run in p_el.iter(qn("w:r")):
        for child in run:
            tag = child.tag
            if tag == qn("w:t") and child.text:
                out.append(child.text)
            elif tag == qn("w:tab"):
                out.append(" ")
            elif tag == qn("w:br") and child.get(qn("w:type")) in (None, "textWrapping"):
                out.append("\n")
    return "".join(out)


def _segments(p_el: Any) -> list[tuple[str, str]]:
    """Ordered ('text', s) / ('fig', rid) / ('pagebreak', '') segments of a paragraph."""
    segs: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            segs.append(("text", "".join(buf)))
            buf.clear()

    for run in p_el.iter(qn("w:r")):
        for child in run:
            tag = child.tag
            if tag == qn("w:t") and child.text:
                buf.append(child.text)
            elif tag == qn("w:tab"):
                buf.append(" ")
            elif tag == qn("w:br"):
                if child.get(qn("w:type")) == "page":
                    flush()
                    segs.append(("pagebreak", ""))
                elif child.get(qn("w:type")) in (None, "textWrapping"):
                    buf.append("\n")
            elif tag == qn("w:drawing"):
                for blip in child.iter(qn("a:blip")):
                    rid = blip.get(qn("r:embed"))
                    if rid:
                        flush()
                        segs.append(("fig", rid))
    flush()
    return segs


def _table_candidate(tbl: Any) -> TableCandidate:
    rows = tbl.findall(qn("w:tr"))
    grid_cols = tbl.find(qn("w:tblGrid"))
    n_grid = len(grid_cols.findall(qn("w:gridCol"))) if grid_cols is not None else 0

    # origin (row, col) -> [row_span, col_span, text]; vertical merges extend the origin above.
    origins: dict[tuple[int, int], list[Any]] = {}
    open_vm: dict[int, tuple[int, int]] = {}  # col -> origin key
    n_cols = n_grid
    header_flags: list[bool] = []
    for r, tr in enumerate(rows):
        trpr = tr.find(qn("w:trPr"))
        header_flags.append(trpr is not None and trpr.find(qn("w:tblHeader")) is not None)
        col = 0
        before = trpr.find(qn("w:gridBefore")) if trpr is not None else None
        if before is not None:
            col += int(before.get(qn("w:val"), "0") or 0)
        seen_cols: set[int] = set()
        for tc in tr.findall(qn("w:tc")):
            tcpr = tc.find(qn("w:tcPr"))
            span = 1
            vm: Any = None
            if tcpr is not None:
                gs = tcpr.find(qn("w:gridSpan"))
                if gs is not None:
                    span = max(1, int(gs.get(qn("w:val"), "1") or 1))
                vm = tcpr.find(qn("w:vMerge"))
            if vm is not None and vm.get(qn("w:val")) in (None, "continue") and col in open_vm:
                origins[open_vm[col]][0] += 1
                seen_cols.add(col)
            else:
                origins[(r, col)] = [1, span, _cell_text(tc)]
                if vm is not None and vm.get(qn("w:val")) == "restart":
                    open_vm[col] = (r, col)
                else:
                    open_vm.pop(col, None)
                seen_cols.add(col)
            col += span
        for c in [c for c in open_vm if c not in seen_cols]:
            del open_vm[c]
        n_cols = max(n_cols, col)

    n_rows = max(1, len(rows))
    n_cols = max(1, n_cols)
    header_rows = 0
    for flag in header_flags:
        if not flag:
            break
        header_rows += 1
    if header_rows == 0:
        look = tbl.find(qn("w:tblPr") + "/" + qn("w:tblLook"))
        if look is not None:
            first = look.get(qn("w:firstRow"))
            val = look.get(qn("w:val"))
            if first is not None:
                on = first in ("1", "true", "on")
            else:
                on = bool(int(val, 16) & 0x0020) if val else False
            header_rows = 1 if on else 0
    header_rows = min(header_rows, n_rows)

    covered = [[False] * n_cols for _ in range(n_rows)]
    cells: list[TableCell] = []
    for (r, c), (rs, cs, text) in sorted(origins.items()):
        rs = min(rs, n_rows - r)
        cs = min(cs, n_cols - c)
        cells.append(
            TableCell(row=r, col=c, row_span=rs, col_span=cs, text=text, is_header=r < header_rows)
        )
        for rr in range(r, r + rs):
            for cc in range(c, c + cs):
                covered[rr][cc] = True
    for r in range(n_rows):
        for c in range(n_cols):
            if not covered[r][c]:
                cells.append(TableCell(row=r, col=c, text="", is_header=r < header_rows))
    cells.sort(key=lambda x: (x.row, x.col))
    return TableCandidate(n_rows=n_rows, n_cols=n_cols, cells=cells, header_rows=header_rows)


def _collect_items(document: Any) -> list[_Item]:
    from docx.text.paragraph import Paragraph

    items: list[_Item] = []
    for el in document.element.body.iterchildren():
        if el.tag == qn("w:tbl"):
            tc = _table_candidate(el)
            items.append(
                _Item(BlockType.table, table_raw_text(tc), "", table=tc),
            )
            continue
        if el.tag != qn("w:p"):
            continue
        style = _style_name(Paragraph(el, document))
        level = _heading_level(style)
        lst = level is None and _is_list(el, style)
        ppr = el.find(qn("w:pPr"))
        section_break = ppr is not None and ppr.find(qn("w:sectPr")) is not None
        segs = _segments(el)
        produced = False
        pending_break = False
        for kind, val in segs:
            if kind == "pagebreak":
                pending_break = True
                continue
            if kind == "fig":
                items.append(
                    _Item(BlockType.figure, "", style, rid=val, break_before=pending_break)
                )
                pending_break = False
                produced = True
                continue
            text = _WS.sub(" ", val).strip()
            if not text:
                continue
            if level is not None:
                bt = BlockType.heading
            elif lst:
                bt = BlockType.list
            elif style.lower() == "caption":
                bt = BlockType.caption
            else:
                bt = BlockType.paragraph
            items.append(
                _Item(
                    bt,
                    text,
                    style,
                    heading_level=level,
                    break_before=pending_break,
                    list_item=lst,
                )
            )
            pending_break = False
            produced = True
        if not produced:
            items.append(
                _Item(
                    BlockType.other,
                    "",
                    style,
                    break_before=pending_break,
                    skipped=True,
                )
            )
        elif pending_break:
            # trailing page break after content: the next item starts a new page
            items.append(_Item(BlockType.other, "", style, break_before=True, skipped=True))
        if section_break and items:
            items[-1].break_after = True
    _classify_captions(items)
    return items


def _classify_captions(items: list[_Item]) -> None:
    """Promote 'Figure N.' / 'Table N.' paragraphs next to a figure or table to captions."""
    live = [i for i, it in enumerate(items) if not it.skipped]
    for pos, idx in enumerate(live):
        it = items[idx]
        if it.kind != BlockType.paragraph or not CAPTION_RE.match(it.text):
            continue
        if len(it.text.split()) > 30:
            continue
        prev_kind = items[live[pos - 1]].kind if pos > 0 else None
        next_kind = items[live[pos + 1]].kind if pos + 1 < len(live) else None
        near = (BlockType.figure, BlockType.table)
        if prev_kind in near or next_kind in near:
            it.kind = BlockType.caption


def _merge_lists(items: list[_Item]) -> list[_Item]:
    """Consecutive list paragraphs become one block; empty paragraphs between them are ignored."""
    out: list[_Item] = []
    for it in items:
        if it.kind == BlockType.list and not it.skipped and not it.break_before:
            k = len(out) - 1
            while k >= 0 and out[k].skipped and not out[k].break_before:
                k -= 1
            if (
                k >= 0
                and out[k].kind == BlockType.list
                and not out[k].skipped
                and not out[k].break_after
            ):
                out[k].text += "\n" + it.text
                out[k].break_after = it.break_after
                continue
        out.append(it)
    return out


def _parse_pages(path: Path) -> DocxParse:
    document = load_docx(str(path))
    items = _merge_lists(_collect_items(document))
    pages: list[PageParse] = []
    blocks: list[RawBlock] = []
    skipped: list[Skipped] = []
    page = 1
    order = 0
    count = 0

    def close_page() -> None:
        nonlocal blocks, skipped
        pages.append(
            PageParse(
                page=len(pages) + 1,
                width=NOMINAL_PAGE[0],
                height=NOMINAL_PAGE[1],
                has_text_layer=True,
                blocks=blocks,
                skipped=skipped,
            )
        )
        blocks, skipped = [], []

    def new_page() -> None:
        nonlocal page, order, count
        close_page()
        page += 1
        order = 0
        count = 0

    carry_break = False
    for it in items:
        if it.break_before or carry_break:
            new_page()
            carry_break = False
        if it.skipped:
            skipped.append(Skipped(page=page, order=order, reason="empty_paragraph"))
            order += 1
            if it.break_after:
                carry_break = True
            continue
        if count >= MAX_BLOCKS_PER_PAGE:
            new_page()
        sec = None
        level = it.heading_level
        if it.kind == BlockType.heading:
            m = SECTION_RE.match(it.text)
            if m:
                sec = m.group(1)
        blocks.append(
            RawBlock(
                parser="docx",
                page=page,
                order=order,
                bbox=None,
                kind=it.kind,
                text=it.text,
                heading_level=level,
                section_number=sec,
                hint=it.style or None,
                table=it.table,
                docx_image_rid=it.rid,
            )
        )
        order += 1
        count += 1
        if it.break_after:
            carry_break = True
    close_page()
    # drop trailing pages that hold no blocks
    while len(pages) > 1 and not pages[-1].blocks:
        pages.pop()
    title = (document.core_properties.title or "").strip() or None
    return DocxParse(pages=pages, title=title)


def count_virtual_pages(path: Path) -> int:
    """Number of virtual pages (at least 1) that hold at least one block."""
    return max(1, len(_parse_pages(Path(path)).pages))


# --------------------------------------------------------------------------- Docling pass


@dataclass
class _DoclingCand:
    kind: BlockType
    text: str
    table: TableCandidate | None
    order: int
    hint: str | None = None
    skipped: bool = False


def _docling_candidates(path: Path) -> tuple[list[_DoclingCand], str]:
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter(allowed_formats=[InputFormat.DOCX])
    doc = converter.convert(str(path)).document
    try:
        version = f"docling=={metadata.version('docling')}"
    except metadata.PackageNotFoundError:
        version = "docling==unknown"
    cands: list[_DoclingCand] = []
    last_list_parent: str | None = None
    for item, _level in doc.iterate_items():
        raw_label = getattr(item, "label", "")
        label = str(getattr(raw_label, "value", raw_label))
        order = len(cands)
        if label in ("title", "section_header"):
            kind = BlockType.heading
        elif label == "list_item":
            kind = BlockType.list
        elif label == "caption":
            kind = BlockType.caption
        elif label in ("text", "paragraph") or label in ("page_header", "page_footer"):
            kind = BlockType.paragraph
        elif label == "table":
            kind = BlockType.table
        elif label in ("picture", "chart"):
            kind = BlockType.figure
        else:
            kind = BlockType.other
        if kind == BlockType.table:
            tc = from_docling(item)
            cands.append(_DoclingCand(kind, table_raw_text(tc), tc, order))
            last_list_parent = None
            continue
        text = _WS.sub(" ", str(getattr(item, "text", "") or "")).strip()
        if kind == BlockType.list:
            parent = getattr(getattr(item, "parent", None), "cref", None)
            if cands and cands[-1].kind == BlockType.list and parent == last_list_parent:
                cands[-1].text += "\n" + text
                continue
            last_list_parent = parent
            cands.append(_DoclingCand(kind, text, None, order))
            continue
        last_list_parent = None
        hint = label if label in ("page_header", "page_footer") else None
        cands.append(
            _DoclingCand(
                kind, text, None, order, hint=hint, skipped=kind != BlockType.figure and not text
            )
        )
    return cands, version


# --------------------------------------------------------------------------- merge


def _key(kind: BlockType, text: str) -> str:
    cls = "fig" if kind == BlockType.figure else "tbl" if kind == BlockType.table else "txt"
    return f"{cls}:{hf_key(text)}"


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


@dataclass
class _Alignment:
    text: dict[int, str] = field(default_factory=dict)  # docx index -> docling text
    outcome: dict[int, str] = field(default_factory=dict)  # docx index -> matched | aligned
    g_for: dict[int, list[int]] = field(default_factory=dict)  # docx index -> docling indices
    g_owner: dict[int, int] = field(default_factory=dict)  # docling index -> docx index


def _align(d_blocks: Sequence[RawBlock], g_cands: Sequence[_DoclingCand]) -> _Alignment:
    """Align the two parsers' sequences (SequenceMatcher over hf_key-normalized texts)."""
    a_keys = [_key(b.kind, b.text) for b in d_blocks]
    g_keys = [_key(c.kind, c.text) for c in g_cands]
    res = _Alignment()

    def take(i: int, js: list[int], outcome: str, text: str | None = None) -> None:
        res.text[i] = "\n".join(g_cands[j].text for j in js) if text is None else text
        res.outcome[i] = outcome
        res.g_for[i] = js
        for j in js:
            res.g_owner[j] = i

    def similar(i: int, j: int) -> bool:
        return d_blocks[i].kind == g_cands[j].kind and _ratio(a_keys[i], g_keys[j]) >= _MATCH_RATIO

    sm = SequenceMatcher(None, a_keys, g_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                take(i1 + k, [j1 + k], "matched")
        elif tag == "replace":
            n, m = i2 - i1, j2 - j1
            if n > 1 and m == 1 and d_blocks[i1].kind == g_cands[j1].kind:
                # docling is coarser: slice its text onto the docx segmentation
                parts = split_text_by_alignment(
                    g_cands[j1].text, [d_blocks[i].text for i in range(i1, i2)]
                )
                for k, i in enumerate(range(i1, i2)):
                    take(i, [j1], "aligned", parts[k])
                res.g_owner[j1] = i1
            elif n == 1 and m > 1:
                joined_key = _key(d_blocks[i1].kind, "\n".join(c.text for c in g_cands[j1:j2]))
                if _ratio(a_keys[i1], joined_key) >= _MATCH_RATIO:
                    take(i1, list(range(j1, j2)), "aligned")
            else:
                j = j1
                for i in range(i1, i2):
                    if j >= j2:
                        break
                    if similar(i, j):
                        take(i, [j], "matched")
                        j += 1
    return res


@dataclass
class DocxResult:
    blocks: list[Block]
    outputs: list[ParserOutput]
    report: MergeReport
    layout: list[PageLayout]
    figures: list[FigureCandidate]
    title: str | None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _version(dist: str) -> str:
    try:
        return f"{dist}=={metadata.version(dist)}"
    except metadata.PackageNotFoundError:
        return f"{dist}==unknown"


def build_docx(path: Path, slug: str, ctx: Any | None = None) -> DocxResult:
    """Parse a DOCX with python-docx and Docling, align them, and build final blocks."""
    path = Path(path)
    sha = str(getattr(ctx, "sha256", None) or _sha(path))
    parsed = _parse_pages(path)
    g_all, _ = _docling_candidates(path)
    flat: list[RawBlock] = [b for p in parsed.pages for b in p.blocks]
    live: list[_DoclingCand] = [c for c in g_all if not c.skipped]
    al = _align(flat, live)

    # unmatched docling candidates follow the nearest preceding consumed candidate's docx block
    after: dict[int, list[int]] = {}
    for j in range(len(live)):
        if j in al.g_owner:
            continue
        anchor = -1
        for k in range(j - 1, -1, -1):
            if k in al.g_owner:
                anchor = al.g_owner[k]
                break
        after.setdefault(anchor, []).append(j)

    entries: list[tuple[str, int, int]] = []  # (kind, index, page)
    first_page = flat[0].page if flat else 1
    entries.extend(("alone", j, first_page) for j in after.get(-1, []))
    for i, b in enumerate(flat):
        entries.append(("docx", i, b.page))
        entries.extend(("alone", j, b.page) for j in after.get(i, []))

    # ids
    per_page: dict[int, int] = {}
    fig_per_page: dict[int, int] = {}
    block_ids: dict[tuple[str, int], str] = {}
    for kind, idx, page in entries:
        n = per_page.get(page, 0) + 1
        if n > MAX_BLOCKS_PER_PAGE:
            raise DocxError(f"more than {MAX_BLOCKS_PER_PAGE} blocks on virtual page {page}")
        per_page[page] = n
        block_ids[(kind, idx)] = ids.block_id(slug, page, n)

    alone_page = {idx: pg for k, idx, pg in entries if k == "alone"}
    # docling page and page-local order follow the alignment
    g_page: dict[int, int] = {}
    cur = first_page
    live_pos = {id(c): j for j, c in enumerate(live)}
    for c in g_all:
        if c.skipped:
            g_page[c.order] = cur
            continue
        j = live_pos[id(c)]
        cur = flat[al.g_owner[j]].page if j in al.g_owner else alone_page[j]
        g_page[c.order] = cur

    g_order: dict[int, int] = {}
    counters: dict[int, int] = {}
    for c in g_all:
        pg = g_page[c.order]
        g_order[c.order] = counters.get(pg, 0)
        counters[pg] = g_order[c.order] + 1

    blocks: list[Block] = []
    figures: list[FigureCandidate] = []
    layout_cols: dict[int, dict[str, int]] = {}
    for order, (kind, idx, page) in enumerate(entries):
        bid = block_ids[(kind, idx)]
        layout_cols.setdefault(page, {})[bid] = 0
        figure_id: str | None = None
        table = None
        heading_level: int | None = None
        section: str | None = None
        rid: str | None = None
        if kind == "docx":
            b = flat[idx]
            btype, text, source = b.kind, b.text, "docx"
            by_parser = {"docx": b.text}
            order_by = {"docx": b.order}
            heading_level, section, rid = b.heading_level, b.section_number, b.docx_image_rid
            g_cand = live[al.g_for[idx][0]] if idx in al.g_for else None
            if idx in al.g_for:
                by_parser["docling"] = al.text[idx]
                order_by["docling"] = min(g_order[live[j].order] for j in al.g_for[idx])
            if b.table is not None:
                shapes: dict[str, TableShape | tuple[int, int]] = {"docx": shape_of(b.table)}
                if g_cand is not None and g_cand.table is not None:
                    shapes["docling"] = shape_of(g_cand.table)
                table = to_table_data(b.table, shapes)
            sources = ["docx", *(["docling"] if idx in al.g_for else [])]
        else:
            g = live[idx]
            btype, text, source = g.kind, g.text, "docling"
            by_parser = {"docling": g.text}
            order_by = {"docling": g_order[g.order]}
            if g.table is not None:
                table = to_table_data(g.table, {"docling": shape_of(g.table)})
            sources = ["docling"]
        if btype == BlockType.figure:
            fig_per_page[page] = fig_per_page.get(page, 0) + 1
            figure_id = ids.figure_id(slug, page, fig_per_page[page])
            figures.append(
                FigureCandidate(
                    figure_id=figure_id,
                    block_id=bid,
                    page=page,
                    bbox=None,
                    sources=sources,
                    image_xrefs=[],
                    has_drawings=False,
                    docx_image_rid=rid,
                )
            )
        blocks.append(
            Block(
                id=bid,
                doc_id=slug,
                page=page,
                bbox=None,
                type=btype,
                reading_order=order,
                raw_text=text,
                raw_source=source,
                raw_text_by_parser=by_parser,
                order_by_parser=order_by,
                heading_level=heading_level if btype == BlockType.heading else None,
                section_number=section if btype == BlockType.heading else None,
                table=table,
                numeric_tokens=numeric_tokens(text),
                figure_id=figure_id,
            )
        )

    n_pages = len(parsed.pages)
    g_pages = {
        p: PageParse(
            page=p, width=NOMINAL_PAGE[0], height=NOMINAL_PAGE[1], has_text_layer=True, blocks=[]
        )
        for p in range(1, n_pages + 1)
    }
    dispositions: list[Disposition] = []
    for c in g_all:
        pg = g_page[c.order]
        o = g_order[c.order]
        if c.skipped:
            g_pages[pg].skipped.append(Skipped(page=pg, order=o, reason="empty_text"))
            dispositions.append(
                Disposition(
                    parser="docling", page=pg, order=o, outcome="skipped", detail="empty_text"
                )
            )
            continue
        g_pages[pg].blocks.append(
            RawBlock(
                parser="docling",
                page=pg,
                order=o,
                bbox=None,
                kind=c.kind,
                text=c.text,
                hint=c.hint,
                table=c.table,
            )
        )
        j = live_pos[id(c)]
        if j in al.g_owner:
            i = al.g_owner[j]
            outcome = al.outcome[i]
            bid = block_ids[("docx", i)]
        else:
            outcome = "alone"
            bid = block_ids[("alone", j)]
        dispositions.append(
            Disposition(
                parser="docling",
                page=pg,
                order=o,
                outcome=outcome,  # type: ignore[arg-type]
                block_id=bid,
            )
        )
    flat_pos = {id(rb): i for i, rb in enumerate(flat)}
    for p in parsed.pages:
        for rb in p.blocks:
            i = flat_pos[id(rb)]
            dispositions.append(
                Disposition(
                    parser="docx",
                    page=rb.page,
                    order=rb.order,
                    outcome="primary",
                    block_id=block_ids[("docx", i)],
                )
            )
        for sk in p.skipped:
            dispositions.append(
                Disposition(
                    parser="docx",
                    page=sk.page,
                    order=sk.order,
                    outcome="skipped",
                    detail=sk.reason,
                )
            )
    dispositions.sort(key=lambda d: (d.page, d.parser, d.order))

    outputs = [
        ParserOutput(
            parser="docx", version=_version("python-docx"), source_sha256=sha, pages=parsed.pages
        ),
        ParserOutput(
            parser="docling",
            version=_version("docling"),
            source_sha256=sha,
            pages=[g_pages[p] for p in sorted(g_pages)],
        ),
    ]
    layout = [
        PageLayout(
            page=p,
            source="docx",
            n_columns=1,
            bands=[],
            block_columns=layout_cols[p],
            overlaps=[],
        )
        for p in sorted(layout_cols)
    ]
    return DocxResult(
        blocks=blocks,
        outputs=outputs,
        report=MergeReport(doc_id=slug, dispositions=dispositions),
        layout=layout,
        figures=figures,
        title=parsed.title,
    )
