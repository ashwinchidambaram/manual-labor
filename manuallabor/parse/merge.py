"""Candidate reconciliation across parsers (design 01-parse section 3). Pure and deterministic."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from manuallabor.contracts.block import OcrWord, TableData, TableShape
from manuallabor.contracts.enums import BlockType
from manuallabor.parse import geometry as g
from manuallabor.parse.layout import group_lines_into_blocks
from manuallabor.parse.types import (
    Disposition,
    Line,
    PageParse,
    RawBlock,
    Skipped,
)

IOU_MATCH = 0.5
CONTAIN_ABSORB = 0.8
CONTAIN_PARTIAL = 0.7
ALT_LINE_PAD = 3.0
SPLIT_COVER = 0.6
REGION_COVER = 0.6

Region = Literal["text", "table", "figure"]
DispFn = Callable[..., None]


@dataclass
class MergedBlock:
    page: int
    region: Region
    bbox: list[float] | None
    raw_source: str
    raw_text: str
    text_by_parser: dict[str, str] = field(default_factory=dict)
    order_by_parser: dict[str, int] = field(default_factory=dict)
    lines: list[Line] = field(default_factory=list)
    size: float | None = None
    bold: bool = False
    hints: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, BlockType] = field(default_factory=dict)
    heading_levels: dict[str, int] = field(default_factory=dict)
    table: TableData | None = None
    sources: list[str] = field(default_factory=list)
    image_xrefs: list[int] = field(default_factory=list)
    has_drawings: bool = False
    docx_image_rid: str | None = None
    ocr_words: list[OcrWord] | None = None
    layout_only: bool = False
    boxes: list[list[float]] = field(default_factory=list)
    # (parser, native order) of every candidate that contributed, for the merge report
    members: list[tuple[str, int]] = field(default_factory=list)

    @property
    def primary_key(self) -> tuple[float, float]:
        b = self.bbox or [0.0, 0.0, 0.0, 0.0]
        return (b[1], b[0])


@dataclass
class _Cand:
    key: str
    rb: RawBlock

    @property
    def order(self) -> int:
        return self.rb.order

    @property
    def bbox(self) -> list[float]:
        assert self.rb.bbox is not None
        return self.rb.bbox


def _size_bold(lines: Sequence[Line]) -> tuple[float | None, bool]:
    sizes: dict[float, int] = {}
    for ln in lines:
        if ln.size is not None:
            sizes[ln.size] = sizes.get(ln.size, 0) + len(ln.text.strip())
    size = max(sorted(sizes), key=lambda k: sizes[k]) if sizes else None
    total = sum(len(ln.text) for ln in lines)
    bold = total > 0 and sum(len(ln.text) for ln in lines if ln.bold) * 2 > total
    return size, bold


def _words_of(lines: Sequence[Line]) -> list[OcrWord]:
    out: list[OcrWord] = []
    for ln in lines:
        out.extend(ln.words)
    return out


def _from_text_cand(c: _Cand, page: int, piece_lines: list[Line] | None = None) -> MergedBlock:
    rb = c.rb
    lines = piece_lines if piece_lines is not None else list(rb.lines)
    if piece_lines is not None:
        text = "\n".join(ln.text for ln in lines)
        bbox = g.union([ln.bbox for ln in lines])
        size, bold = _size_bold(lines)
    else:
        text, bbox, size, bold = rb.text, list(rb.bbox) if rb.bbox else None, rb.size, rb.bold  # type: ignore[assignment]
    mb = MergedBlock(
        page=page,
        region="text",
        bbox=bbox,
        raw_source=c.key,
        raw_text=text,
        text_by_parser={c.key: text},
        order_by_parser={c.key: c.order},
        lines=lines,
        size=size,
        bold=bold,
        kinds={c.key: rb.kind},
        layout_only=rb.layout_only,
        members=[(c.key, c.order)],
    )
    if rb.hint:
        mb.hints[c.key] = rb.hint
    if rb.heading_level is not None:
        mb.heading_levels[c.key] = rb.heading_level
    if c.key.startswith("ocr"):
        mb.ocr_words = _words_of(lines)
    return mb


def _add_text_from(mb: MergedBlock, c: _Cand, text: str) -> None:
    """Record a secondary contributor's text/order/hints on an existing merged block."""
    mb.text_by_parser[c.key] = text
    mb.order_by_parser[c.key] = min(c.order, mb.order_by_parser.get(c.key, c.order))
    mb.kinds[c.key] = c.rb.kind
    if c.rb.hint:
        mb.hints[c.key] = c.rb.hint
    if c.rb.heading_level is not None:
        mb.heading_levels[c.key] = c.rb.heading_level
    mb.members.append((c.key, c.order))
    if c.rb.size is not None and mb.size is None:
        mb.size = c.rb.size


# ---------------------------------------------------------------------------------------------
# regions


def _group_regions(cands: list[_Cand], rank: dict[str, int]) -> list[list[_Cand]]:
    """Greedy cross-parser grouping of same-kind region candidates by IoU >= 0.5."""
    pairs: list[tuple[float, int, int, int, int, int, int]] = []
    for i, a in enumerate(cands):
        for j in range(i + 1, len(cands)):
            b = cands[j]
            if a.key == b.key or a.rb.kind != b.rb.kind:
                continue
            v = g.iou(a.bbox, b.bbox)
            if v >= IOU_MATCH:
                lo, hi = sorted((i, j), key=lambda k: (rank[cands[k].key], cands[k].order))
                pairs.append(
                    (
                        -v,
                        rank[cands[lo].key],
                        cands[lo].order,
                        rank[cands[hi].key],
                        cands[hi].order,
                        lo,
                        hi,
                    )
                )
    pairs.sort()
    group_of: dict[int, int] = {i: i for i in range(len(cands))}
    members: dict[int, list[int]] = {i: [i] for i in range(len(cands))}
    for *_, lo, hi in pairs:
        ga, gb = group_of[lo], group_of[hi]
        if ga == gb:
            continue
        keys_a = {cands[m].key for m in members[ga]}
        keys_b = {cands[m].key for m in members[gb]}
        if keys_a & keys_b:
            continue
        for m in members[gb]:
            group_of[m] = ga
        members[ga].extend(members.pop(gb))
    groups = [
        sorted(ms, key=lambda m: (rank[cands[m].key], cands[m].order)) for ms in members.values()
    ]
    out = [[cands[m] for m in ms] for ms in groups]
    out.sort(key=lambda grp: (grp[0].bbox[1], grp[0].bbox[0], rank[grp[0].key], grp[0].order))
    return out


def _region_block(group: list[_Cand], page: int) -> MergedBlock:
    from manuallabor.parse import tables as tables_mod

    first = group[0]
    kind = first.rb.kind
    region: Region = "table" if kind == BlockType.table else "figure"
    mb = MergedBlock(
        page=page,
        region=region,
        bbox=list(first.bbox),
        raw_source=first.key,
        raw_text="",
        sources=[c.key for c in group],
        layout_only=all(c.rb.layout_only for c in group),
        boxes=[list(c.bbox) for c in group],
    )
    for c in group:
        mb.order_by_parser[c.key] = c.order
        mb.kinds[c.key] = c.rb.kind
        mb.members.append((c.key, c.order))
        if c.rb.hint:
            mb.hints[c.key] = c.rb.hint
        mb.image_xrefs = sorted(set(mb.image_xrefs) | set(c.rb.image_xrefs))
        mb.has_drawings = mb.has_drawings or c.rb.has_drawings
        if c.rb.docx_image_rid and mb.docx_image_rid is None:
            mb.docx_image_rid = c.rb.docx_image_rid
    if region == "table":
        structured = [(c.key, c.rb.table) for c in group if c.rb.table is not None]
        if structured:
            shapes = {k: TableShape(rows=t.n_rows, cols=t.n_cols) for k, t in structured}
            mb.table = tables_mod.to_table_data(structured[0][1], shapes)
            for k, t in structured:
                mb.text_by_parser[k] = tables_mod.table_raw_text(t)
    return mb


def _finish_region_text(
    mb: MergedBlock, absorbed: dict[str, list[tuple[int, str]]], line_words: list[OcrWord] | None
) -> None:
    for key in sorted(absorbed):
        text = "\n".join(t for _, t in sorted(absorbed[key]))
        if key not in mb.text_by_parser:
            mb.text_by_parser[key] = text
            if mb.region == "table" and mb.table is not None:
                mb.table.shape_by_parser.setdefault(key, TableShape(rows=0, cols=0))
        mb.order_by_parser.setdefault(key, min(o for o, _ in absorbed[key]))
    if mb.region == "table":
        for key in absorbed:
            if mb.table is not None and key not in mb.table.shape_by_parser:
                mb.table.shape_by_parser[key] = TableShape(rows=0, cols=0)
        # keep shape_by_parser sorted by key (stable serialization)
        if mb.table is not None:
            mb.table.shape_by_parser = dict(sorted(mb.table.shape_by_parser.items()))
    # raw text of a table: first source (in P, S, R order) with a non-empty text
    if mb.region == "table":
        for key in mb.sources + sorted(k for k in mb.text_by_parser if k not in mb.sources):
            t = mb.text_by_parser.get(key, "")
            if t.strip():
                mb.raw_source, mb.raw_text = key, t
                break
    else:
        mb.raw_text = ""
    if line_words is not None:
        mb.ocr_words = line_words


# ---------------------------------------------------------------------------------------------
# page merge


def merge_page(
    P: PageParse | None,
    S: PageParse | None,
    R: PageParse | None,
    page: int,
    *,
    names: tuple[str | None, str | None, str | None] = (None, None, None),
    scanned: bool = False,
) -> tuple[list[MergedBlock], list[Disposition]]:
    """Reconcile the candidates of one page.

    ``names`` are the parser keys of (P, S, R); ``scanned`` merges S into P by OCR lines.
    """
    rank: dict[str, int] = {}
    cands: list[_Cand] = []
    skipped: list[tuple[str, Skipped]] = []
    for idx, (pp, nm) in enumerate(zip((P, S, R), names, strict=True)):
        if pp is None:
            continue
        if nm is not None:
            rank.setdefault(nm, idx)
        for rb in pp.blocks:
            rank.setdefault(rb.parser, idx)
            cands.append(_Cand(rb.parser, rb))
        for sk in pp.skipped:
            skipped.append((nm or (pp.blocks[0].parser if pp.blocks else "unknown"), sk))

    regions = [c for c in cands if c.rb.kind in (BlockType.table, BlockType.figure) and c.rb.bbox]
    texts = [c for c in cands if c not in regions and c.rb.bbox is not None]
    nobox = [c for c in cands if c.rb.bbox is None]

    # 1. regions
    groups = _group_regions(regions, rank)
    # A secondary-parser region that is mostly covered by other parsers' regions is absorbed.
    covered: dict[int, list[_Cand]] = {}
    kept: list[list[_Cand]] = []
    primary_name = names[0]
    for gi, grp in enumerate(groups):
        if len(grp) == 1 and grp[0].key != primary_name and primary_name is not None:
            c = grp[0]
            best: tuple[float, int] | None = None
            total = 0.0
            for oi, other in enumerate(groups):
                if (
                    oi == gi
                    or other[0].rb.kind != c.rb.kind
                    or other[0].key == c.key
                    or not (other[0].key == primary_name or len(other) > 1)
                ):
                    continue
                inter = g.intersection(c.bbox, other[0].bbox)
                total += inter
                if inter > 0 and (best is None or (-inter, oi) < (-best[0], best[1])):
                    best = (inter, oi)
            if best is not None and total >= REGION_COVER * g.area(c.bbox):
                covered.setdefault(best[1], []).append(c)
                continue
        kept.append(grp)
    # remap host indices after dropping the covered groups
    host_of = {id(groups[oi]): oi for oi in range(len(groups))}
    groups = kept
    region_blocks = [_region_block(grp, page) for grp in groups]
    new_index = {host_of[id(grp)]: k for k, grp in enumerate(groups)}
    absorbed_by: list[dict[str, list[tuple[int, str]]]] = [{} for _ in region_blocks]
    region_words: list[list[OcrWord]] = [[] for _ in region_blocks]
    region_absorbed_members: list[list[tuple[str, int]]] = [[] for _ in region_blocks]
    for old_idx, cs in covered.items():
        for c in cs:
            region_absorbed_members[new_index[old_idx]].append((c.key, c.order))

    def region_for(box: Sequence[float]) -> int | None:
        best: tuple[float, int] | None = None
        for i, rbk in enumerate(region_blocks):
            v = max(g.contain(box, b) for b in rbk.boxes)
            if v >= CONTAIN_ABSORB and (best is None or (-v, i) < (-best[0], best[1])):
                best = (v, i)
        return None if best is None else best[1]

    # 2. absorption (the alternate OCR reading is absorbed line by line, below)
    alt_name = names[1] if scanned else None
    free_texts: list[_Cand] = []
    alt_cands: list[_Cand] = []
    for c in texts:
        if alt_name is not None and c.key == alt_name:
            alt_cands.append(c)
            continue
        r = region_for(c.bbox)
        if r is None:
            free_texts.append(c)
            continue
        absorbed_by[r].setdefault(c.key, []).append((c.order, c.rb.text))
        region_absorbed_members[r].append((c.key, c.order))
        if scanned:
            region_words[r].extend(_words_of(c.rb.lines))

    dispositions: dict[tuple[str, int], Disposition] = {}

    def disp(key: str, order: int, outcome: str, detail: str | None = None) -> None:
        dispositions[(key, order)] = Disposition(
            parser=key,
            page=page,
            order=order,
            outcome=outcome,  # type: ignore[arg-type]
            detail=detail,
        )

    if scanned:
        text_blocks = _merge_alt_lines(
            free_texts,
            alt_cands,
            alt_name or "ocr_alt",
            region_blocks,
            absorbed_by,
            page,
            disp,
        )
    else:
        text_blocks = _merge_text(free_texts, rank, page, disp, names[0])

    for i, mb in enumerate(region_blocks):
        _finish_region_text(mb, absorbed_by[i], region_words[i] if scanned else None)
        for m_idx, (k, o) in enumerate(mb.members):
            disp(k, o, "primary" if m_idx == 0 else "matched")
        for k, o in region_absorbed_members[i]:
            disp(k, o, "absorbed")
        mb.members.extend(region_absorbed_members[i])

    # candidates without geometry are kept alone
    for c in nobox:
        mb = _from_text_cand(c, page)
        mb.bbox = None
        text_blocks.append(mb)
        disp(c.key, c.order, "alone")

    merged = region_blocks + text_blocks
    for key, sk in skipped:
        disp(key, sk.order, "skipped", sk.reason)
    merged.sort(
        key=lambda m: (m.primary_key[0], m.primary_key[1], sorted(m.order_by_parser.items()))
    )
    return merged, sorted(dispositions.values(), key=lambda d: (d.page, d.parser, d.order))


def _merge_text(
    free: list[_Cand],
    rank: dict[str, int],
    page: int,
    disp: DispFn,
    primary_key: str | None,
) -> list[MergedBlock]:
    keys = sorted({c.key for c in free}, key=lambda k: rank.get(k, 9))
    if len(keys) == 0:
        return []
    pk = primary_key if primary_key in keys else keys[0]
    p_list = sorted([c for c in free if c.key == pk], key=lambda c: c.order)
    others = [k for k in keys if k != pk]
    out: list[MergedBlock] = []
    if not others:
        for p in p_list:
            out.append(_from_text_cand(p, page))
            disp(p.key, p.order, "primary")
        return out
    sk = others[0]
    s_list = sorted([c for c in free if c.key == sk], key=lambda c: c.order)
    # any third parser's candidates are kept alone
    extras = [c for c in free if c.key not in (pk, sk)]

    p_taken: set[int] = set()
    s_taken: set[int] = set()
    blocks_for_p: dict[int, list[MergedBlock]] = {}

    # A. P coarser than S: several S lie inside one p and cover most of it.
    for i, p in enumerate(p_list):
        if i in p_taken or not p.rb.lines:
            continue
        inside = [
            j
            for j, sc in enumerate(s_list)
            if j not in s_taken and g.contain(sc.bbox, p.bbox) >= CONTAIN_PARTIAL
        ]
        if len(inside) < 2 or len({s_list[j].rb.kind for j in inside}) < 2:
            continue
        if sum(g.area(s_list[j].bbox) for j in inside) < SPLIT_COVER * g.area(p.bbox):
            continue
        assign: dict[int, list[Line]] = {j: [] for j in inside}
        for ln in p.rb.lines:
            cx, cy = g.center(ln.bbox)
            owner = next(
                (j for j in inside if g.contains_point(s_list[j].bbox, cx, cy)),
                None,
            )
            if owner is None:
                owner = min(inside, key=lambda j: (abs(g.center(s_list[j].bbox)[1] - cy), j))
            assign[owner].append(ln)
        used = [j for j in inside if assign[j]]
        if len(used) < 2:
            continue
        pieces: list[MergedBlock] = []
        for j in used:
            sc = s_list[j]
            mb = _from_text_cand(p, page, piece_lines=assign[j])
            _add_text_from(mb, sc, sc.rb.text)
            pieces.append(mb)
            s_taken.add(j)
            disp(sc.key, sc.order, "split")
        blocks_for_p[i] = pieces
        p_taken.add(i)
        disp(p.key, p.order, "split")

    # B. S coarser than P: several p lie inside one s and cover most of it.
    for j, sc in enumerate(s_list):
        if j in s_taken:
            continue
        inside_p = [
            i
            for i, p in enumerate(p_list)
            if i not in p_taken and g.contain(p.bbox, sc.bbox) >= CONTAIN_PARTIAL
        ]
        if len(inside_p) < 2:
            continue
        if sum(g.area(p_list[i].bbox) for i in inside_p) < SPLIT_COVER * g.area(sc.bbox):
            continue
        try:
            from manuallabor.parse.textalign import split_text_by_alignment
        except ImportError:  # pragma: no cover
            continue
        slices = split_text_by_alignment(sc.rb.text, [p_list[i].rb.text for i in inside_p])
        for i, sl in zip(inside_p, slices, strict=True):
            mb = _from_text_cand(p_list[i], page)
            _add_text_from(mb, sc, sl)
            blocks_for_p[i] = [mb]
            p_taken.add(i)
            disp(p_list[i].key, p_list[i].order, "aligned")
        s_taken.add(j)
        disp(sc.key, sc.order, "aligned")

    # C. 1:1 by IoU (or unique containment) among what is left.
    def related(a: list[float], b: list[float]) -> bool:
        small, big = (a, b) if g.area(a) <= g.area(b) else (b, a)
        return g.contain(small, big) >= CONTAIN_PARTIAL

    left_p = [i for i in range(len(p_list)) if i not in p_taken]
    left_s = [j for j in range(len(s_list)) if j not in s_taken]
    partners_p = {i: [j for j in left_s if related(p_list[i].bbox, s_list[j].bbox)] for i in left_p}
    partners_s = {j: [i for i in left_p if related(p_list[i].bbox, s_list[j].bbox)] for j in left_s}
    pairs: list[tuple[float, int, int, int, int]] = []
    for i in left_p:
        for j in left_s:
            v = g.iou(p_list[i].bbox, s_list[j].bbox)
            only = len(partners_p[i]) == 1 and len(partners_s[j]) == 1 and partners_p[i][0] == j
            if v >= IOU_MATCH or only:
                pairs.append((-v, p_list[i].order, s_list[j].order, i, j))
    pairs.sort()
    for _, _, _, i, j in pairs:
        if i in p_taken or j in s_taken:
            continue
        p_taken.add(i)
        s_taken.add(j)
        p, sc = p_list[i], s_list[j]
        mb = _from_text_cand(p, page)
        _add_text_from(mb, sc, sc.rb.text)
        blocks_for_p[i] = [mb]
        disp(p.key, p.order, "primary")
        disp(sc.key, sc.order, "matched")
    # D. Leftover S fully inside a P block: absorb its text into that block.
    for j, sc in enumerate(s_list):
        if j in s_taken:
            continue
        hosts = [i for i, p in enumerate(p_list) if g.contain(sc.bbox, p.bbox) >= CONTAIN_PARTIAL]
        if not hosts:
            continue
        host = min(hosts, key=lambda i: (g.area(p_list[i].bbox), i))
        if host not in blocks_for_p:
            hp = p_list[host]
            blocks_for_p[host] = [_from_text_cand(hp, page)]
            disp(hp.key, hp.order, "primary")
        target = blocks_for_p[host][0]
        prev_text = target.text_by_parser.get(sc.key, "")
        target.text_by_parser[sc.key] = (prev_text + "\n" + sc.rb.text) if prev_text else sc.rb.text
        target.order_by_parser[sc.key] = min(sc.order, target.order_by_parser.get(sc.key, sc.order))
        target.members.append((sc.key, sc.order))
        s_taken.add(j)
        disp(sc.key, sc.order, "absorbed")
    s_done = s_taken
    # 6. alone
    for i, p in enumerate(p_list):
        if i in blocks_for_p:
            out.extend(blocks_for_p[i])
            continue
        out.append(_from_text_cand(p, page))
        disp(p.key, p.order, "alone")
    for j, s in enumerate(s_list):
        if j in s_done:
            continue
        out.append(_from_text_cand(s, page))
        disp(s.key, s.order, "alone")
    for c in sorted(extras, key=lambda c: (rank.get(c.key, 9), c.order)):
        out.append(_from_text_cand(c, page))
        disp(c.key, c.order, "alone")
    return out


def _merge_alt_lines(
    p_cands: list[_Cand],
    alt_cands: list[_Cand],
    alt_key: str,
    region_blocks: list[MergedBlock],
    absorbed_by: list[dict[str, list[tuple[int, str]]]],
    page: int,
    disp: DispFn,
) -> list[MergedBlock]:
    """Scanned pages: merge the alternate OCR reading into the primary at line level."""
    p_cands = sorted(p_cands, key=lambda c: c.order)
    blocks: list[MergedBlock] = []
    for p in p_cands:
        blocks.append(_from_text_cand(p, page))
        disp(p.key, p.order, "primary")
    assigned: dict[int, list[tuple[Line, int]]] = {i: [] for i in range(len(blocks))}
    region_lines: dict[int, list[tuple[Line, int]]] = {}
    free: list[tuple[Line, int]] = []
    owner_of: dict[int, set[str]] = {}
    for c in sorted(alt_cands, key=lambda c: c.order):
        owner_of[c.order] = set()
        lines = c.rb.lines or [
            Line(
                text=c.rb.text,
                bbox=list(c.rb.bbox or [0, 0, 0, 0]),
                native_id=f"{c.key}{c.order}",
            )
        ]
        for ln in lines:
            cx, cy = g.center(ln.bbox)
            reg = None
            for i, rbk in enumerate(region_blocks):
                if rbk.bbox is not None and g.contains_point(rbk.bbox, cx, cy):
                    reg = i
                    break
            if reg is not None:
                region_lines.setdefault(reg, []).append((ln, c.order))
                owner_of[c.order].add(f"r{reg}")
                continue
            best: tuple[float, int] | None = None
            for bi, mb in enumerate(blocks):
                if mb.bbox is not None and g.contains_point(
                    g.expand(mb.bbox, ALT_LINE_PAD), cx, cy
                ):
                    a = g.area(mb.bbox)
                    if best is None or (a, bi) < best:
                        best = (a, bi)
            if best is not None:
                assigned[best[1]].append((ln, c.order))
                owner_of[c.order].add(f"b{best[1]}")
            else:
                free.append((ln, c.order))
                owner_of[c.order].add("free")

    def line_key(t: tuple[Line, int]) -> tuple[float, float, str]:
        return (round(t[0].bbox[1], 1), round(t[0].bbox[0], 1), t[0].native_id)

    for bi, mb in enumerate(blocks):
        got = sorted(assigned[bi], key=line_key)
        if got:
            mb.text_by_parser[alt_key] = "\n".join(ln.text for ln, _ in got)
            mb.order_by_parser[alt_key] = min(od for _, od in got)
            for od in sorted({od for _, od in got}):
                mb.members.append((alt_key, od))
    for reg, rlines in sorted(region_lines.items()):
        got = sorted(rlines, key=line_key)
        absorbed_by[reg].setdefault(alt_key, []).append(
            (min(od for _, od in got), "\n".join(ln.text for ln, _ in got))
        )
        for od in sorted({od for _, od in got}):
            region_blocks[reg].members.append((alt_key, od))
    free = sorted(free, key=line_key)
    order_of_line = {id(ln): od for ln, od in free}
    for grp in group_lines_into_blocks([ln for ln, _ in free], 0.0):
        mb = MergedBlock(
            page=page,
            region="text",
            bbox=g.union([ln.bbox for ln in grp]),
            raw_source=alt_key,
            raw_text="\n".join(ln.text for ln in grp),
            lines=list(grp),
            ocr_words=_words_of(grp),
        )
        mb.size, mb.bold = _size_bold(grp)
        mb.text_by_parser[alt_key] = mb.raw_text
        first = min(order_of_line[id(ln)] for ln in grp)
        mb.order_by_parser[alt_key] = first
        mb.members.append((alt_key, first))
        mb.kinds[alt_key] = BlockType.paragraph
        blocks.append(mb)
    for c in alt_cands:
        owners = owner_of.get(c.order, set())
        if owners == {"free"}:
            outcome = "alone"
        elif len(owners) == 1:
            outcome = "absorbed" if next(iter(owners)).startswith("r") else "matched"
        else:
            outcome = "split"
        disp(c.key, c.order, outcome)
    return blocks
