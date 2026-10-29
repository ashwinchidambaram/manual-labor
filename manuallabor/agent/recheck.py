"""Rechecks of a proposal (design 10 section 3.6). Every model output goes through here before
it is stored; nothing the model says about itself is read.

The checks are deterministic, or use only independent sources: the other readers of the same
region, the vision reader's numbers, deterministic figure/caption rules and cached embeddings.
A proposal that fails any check is stored and shown with its failing check, never hidden, and is
never applied."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Final

from manuallabor import ids
from manuallabor.agent.data import figure_facts
from manuallabor.agent.inputs import DocEmbeddings, cosine, topic_of
from manuallabor.agent.types import (
    BBOX_INK_MIN,
    BBOX_IOU_SAME,
    BBOX_MAX_AREA_FRAC,
    BBOX_MIN_AREA_FRAC,
    BBOX_MIN_SIDE,
    BBOX_TEXT_OVERLAP_MAX,
    CELLS_MAX_CHARS,
    CELLS_MAX_COLS,
    CELLS_MAX_ROWS,
    AgentInput,
)
from manuallabor.cleanup.attach import build_articles, caption_content, content
from manuallabor.cleanup.refs import caption_number, find_refs, is_chaptered
from manuallabor.cleanup.types import MATCH_MIN_TOKENS, T_MATCH
from manuallabor.contracts.block import (
    Block,
    FaithfulnessViolation,
    NumericVariant,
    TableCell,
    TableData,
    TableShape,
    VisionReading,
)
from manuallabor.contracts.enums import BlockType, ProposalKind
from manuallabor.contracts.proposal import REQUIRED_CHECKS, EvidenceRef, RecheckResult
from manuallabor.grouping.coverage import overlap
from manuallabor.grouping.pipeline import check_partition
from manuallabor.parse import geometry as g
from manuallabor.parse.tables import table_markdown_from_data
from manuallabor.parse.text import collapse_ws
from manuallabor.project import ProjectPaths
from manuallabor.scoring.faithfulness import (
    _TOKEN_PUNCT,
    check_faithfulness_ex,
    numeric_tokens,
    ocr_confusable,
    table_coverage,
)
from manuallabor.scoring.garbage import garbage_ratio
from manuallabor.scoring.pipeline import faith_kwargs
from manuallabor.scoring.tables import ragged_rows, table_consistency
from manuallabor.scoring.text import cmp_tokens, weighted_agreement
from manuallabor.scoring.types import BlockContext
from manuallabor.state.data import ProjectData

__all__ = [
    "RECHECKS",
    "Resolved",
    "attested_faithfulness",
    "build_table_data",
    "check_table_position",
    "numbers_changed",
    "numeric_attested",
    "resolve_payload",
    "run_rechecks",
]

RECHECKS: Final[dict[ProposalKind, tuple[str, ...]]] = REQUIRED_CHECKS


def _r(check: str, passed: bool, detail: str | None = None) -> RecheckResult:
    return RecheckResult(
        check=check, passed=passed, detail=None if detail is None else detail[:300]
    )


def _clip(s: str, n: int = 24) -> str:
    s = collapse_ws(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# -- text ----------------------------------------------------------------------------------------


def check_shape_text(text: str, max_len: int) -> RecheckResult:
    if not text.strip():
        return _r("shape", False, "empty text")
    if "<item>" in text or "<raw>" in text or "</item>" in text or "</raw>" in text:
        return _r("shape", False, "the text contains prompt tags")
    if len(text) > max_len:
        return _r("shape", False, f"{len(text)} chars exceed the {max_len} limit")
    return _r("shape", True)


def check_shape_cells(cells: Sequence[Sequence[str]]) -> RecheckResult:
    if not cells:
        return _r("shape", False, "no rows")
    n = len(cells[0])
    if n < 1:
        return _r("shape", False, "no columns")
    if any(len(row) != n for row in cells):
        return _r("shape", False, "rows have different lengths")
    if len(cells) > CELLS_MAX_ROWS or n > CELLS_MAX_COLS:
        return _r("shape", False, f"{len(cells)}x{n} exceeds {CELLS_MAX_ROWS}x{CELLS_MAX_COLS}")
    if any(len(c) > CELLS_MAX_CHARS for row in cells for c in row):
        return _r("shape", False, f"a cell exceeds {CELLS_MAX_CHARS} characters")
    return _r("shape", True, f"{len(cells)}x{n}")


def check_changed_text(text: str, current: str) -> RecheckResult:
    if collapse_ws(text) == collapse_ws(current):
        return _r("changed", False, "identical to the text the reviewer saw")
    return _r("changed", True)


def check_evidence(evidence: Sequence[EvidenceRef]) -> RecheckResult:
    ok = [e for e in evidence if e.verified]
    if not ok:
        return _r("evidence", False, f"0 of {len(evidence)} quoted spans occur in their source")
    return _r("evidence", True, f"{len(ok)} of {len(evidence)} verified")


def _intervals(violations: Sequence[FaithfulnessViolation], n: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for v in violations:
        if v.clean_start is None or v.clean_end is None:
            out.append((0, n))
        else:
            out.append((v.clean_start, v.clean_end))
    return out


def _touch(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def attested_faithfulness(
    block: Block, ctx: BlockContext, variants: Sequence[NumericVariant], text: str
) -> RecheckResult:
    """A: pass when strict §5.2 passes, or when every violation sits where an independent
    reader, taken as the raw text, has no violation (that reader says the same thing)."""
    base = check_faithfulness_ex(block.raw_text, text, **faith_kwargs(block, ctx, variants))
    if base.result.passed:
        return _r("faithfulness", True, "§5.2 normalization only")
    n = len(text)
    indep = sorted(k for k in block.raw_text_by_parser if k != block.raw_source)
    bad: dict[str, list[tuple[int, int]]] = {}
    for k in indep:
        bk = block.model_copy(update={"raw_text": block.raw_text_by_parser[k], "raw_source": k})
        o = check_faithfulness_ex(bk.raw_text, text, **faith_kwargs(bk, ctx, []))
        bad[k] = _intervals(o.result.violations, n)
    viol = base.result.violations
    iv = _intervals(viol, n)
    parts: list[str] = []
    failed: list[str] = []
    for v, span in zip(viol, iv, strict=True):
        who = next((k for k in indep if not any(_touch(span, b) for b in bad[k])), None)
        shown = _clip(v.clean or v.raw)
        if who is None:
            failed.append(f"{shown!r} ({v.kind.value})")
        else:
            parts.append(f"{shown!r}←{who}")
    if failed:
        return _r("faithfulness", False, "unattested: " + "; ".join(failed))
    return _r("faithfulness", True, f"strict: {len(viol)} violations; " + ", ".join(parts))


def _norm_tok(t: str) -> str:
    return t.strip(_TOKEN_PUNCT)


def _numtoks(text: str) -> list[str]:
    return [x for x in (_norm_tok(t) for t in numeric_tokens(text)) if any(c.isdigit() for c in x)]


def numeric_attested(
    raw: str,
    readers: Mapping[str, str],
    raw_source: str,
    text: str,
    vision: VisionReading | None,
    has_numeric_spec: bool,
) -> RecheckResult:
    """N: a changed number needs an attester. One independent reader that shows the new value
    at the same position is enough only when the change is an OCR look-alike (`3S`->`35`);
    otherwise two sources must agree (readers or the vision reader). An inserted or deleted
    number needs two sources that show exactly the new sequence (one when the block has no
    numeric spec). Numbers are compared by position: the same numbers in another order are
    changed numbers (`10 ... 25` -> `25 ... 10`)."""
    tr, tp = _numtoks(raw), _numtoks(text)
    if tp == tr:
        return _r("numeric_attested", True, "numbers unchanged")
    indep = {k: _numtoks(v) for k, v in sorted(readers.items()) if k != raw_source}
    vnum: list[str] | None = None
    if vision is not None and vision.outcome == "ok":
        vnum = [_norm_tok(t) for t in vision.numbers]
    ok_all = True
    notes: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, tr, tp, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            for d in range(i2 - i1):
                i, old, new = i1 + d, tr[i1 + d], tp[j1 + d]
                who = [k for k, tk in indep.items() if len(tk) == len(tr) and tk[i] == new]
                if vnum is not None and len(vnum) == len(tr) and vnum[i] == new:
                    who.append("vision")
                ok = (len(who) >= 1 and ocr_confusable(old, new)) or len(who) >= 2
                ok_all = ok_all and ok
                notes.append(f"{old}→{new} [{', '.join(who) or 'no attester'}]")
            continue
        need = 2 if has_numeric_spec else 1
        who = [k for k, tk in indep.items() if tk == tp]
        if vnum is not None and vnum == tp:
            who.append("vision")
        ok = len(who) >= need
        ok_all = ok_all and ok
        notes.append(
            f"{' '.join(tr[i1:i2]) or '(none)'}→{' '.join(tp[j1:j2]) or '(none)'} "
            f"[{', '.join(who) or 'no attester'}; need {need}]"
        )
    return _r("numeric_attested", ok_all, "; ".join(notes))


def numbers_changed(raw: str, text: str) -> bool:
    """The digit-bearing tokens differ by position (a permutation is a change)."""
    return _numtoks(raw) != _numtoks(text)


def _code_tokens(text: str) -> Counter[str]:
    return Counter(t for t in text.split() if any(c.isdigit() or c == "/" for c in t))


def check_token_whitespace(
    raw: str, text: str, readers: Mapping[str, str], raw_source: str
) -> RecheckResult:
    """V5: no whitespace inserted into or removed from a token with a digit or `/`, unless an
    independent reader shows the new token verbatim."""
    a, b = _code_tokens(raw), _code_tokens(text)
    if a == b:
        return _r("token_whitespace", True)
    seen: set[str] = set()
    for k, v in readers.items():
        if k != raw_source:
            seen.update(v.split())
    new = b - a
    unattested = sorted(t for t in new if t not in seen)
    if unattested:
        return _r(
            "token_whitespace", False, "new token(s) no reader shows: " + ", ".join(unattested[:3])
        )
    return _r("token_whitespace", True, "differing tokens occur in an independent reader")


def check_garbage(raw: str, text: str) -> RecheckResult:
    a, b = garbage_ratio(raw, is_table=False), garbage_ratio(text, is_table=False)
    if a is None or b is None:
        return _r("garbage_ratio", True, "no tokens")
    if b.value >= a.value:
        return _r("garbage_ratio", True, f"{a.value:g} → {b.value:g}")
    return _r("garbage_ratio", False, f"worse: {a.value:g} → {b.value:g}")


def check_parser_agreement(
    raw: str, text: str, readers: Mapping[str, str], raw_source: str
) -> RecheckResult:
    """The fix moves toward the other readers, never away from them."""
    others = [v for k, v in sorted(readers.items()) if k != raw_source and v.strip()]
    if not others:
        return _r("parser_agreement", True, "no independent reader")

    def best(t: str) -> float:
        tk = cmp_tokens(t)
        return max(weighted_agreement(tk, cmp_tokens(o), directional=False).value for o in others)

    before, after = best(raw), best(text)
    if after >= before:
        return _r("parser_agreement", True, f"{before:g} → {after:g}")
    return _r(
        "parser_agreement", False, f"moves away from the other readers: {before:g} → {after:g}"
    )


# -- cells ---------------------------------------------------------------------------------------


def build_table_data(
    cells: Sequence[Sequence[str]],
    header_rows: int,
    shape_by_parser: Mapping[str, TableShape] | None = None,
) -> TableData:
    n_rows, n_cols = len(cells), len(cells[0])
    tcs = [
        TableCell(row=r, col=c, text=cells[r][c], is_header=r < header_rows)
        for r in range(n_rows)
        for c in range(n_cols)
    ]
    td = TableData(
        n_rows=n_rows,
        n_cols=n_cols,
        cells=tcs,
        markdown="|",
        shape_by_parser=dict(shape_by_parser or {}),
    )
    return td.model_copy(update={"markdown": table_markdown_from_data(td)})


def cells_text(cells: Sequence[Sequence[str]]) -> str:
    return "\n".join(" | ".join(c for c in row if c.strip()) for row in cells)


def check_table_coverage(
    raw: str, cells: Sequence[Sequence[str]], readers: Mapping[str, str], raw_source: str
) -> RecheckResult:
    cov = table_coverage(raw, cells)
    if cov.ok:
        return _r("table_coverage", True, cov.detail())
    for k, v in sorted(readers.items()):
        if k != raw_source and table_coverage(v, cells).ok:
            return _r("table_coverage", True, f"cells cover the {k} reader's text")
    return _r("table_coverage", False, cov.detail())


def check_table_consistency(block: Block, td: TableData) -> RecheckResult:
    new = table_consistency(td, block.raw_text)
    ragged, _body = ragged_rows(td)
    cur = next((s.value for s in block.signals if s.name.value == "table_consistency"), None)
    if cur is None and block.table is not None:
        cur = table_consistency(block.table, block.raw_text).value
    if ragged:
        return _r("table_consistency", False, f"{ragged} ragged row(s)")
    if cur is not None and new.value < cur:
        return _r("table_consistency", False, f"{cur:g} → {new.value:g}")
    return _r("table_consistency", True, f"{cur if cur is not None else '-'} → {new.value:g}")


_BULLET_RE: Final = re.compile(r"^[•·◦▪‣●*–-]\s+")
_SEP_RE: Final = re.compile(r"^:?-{3,}:?$")
Grid = list[list[str]]


def _norm_cell(text: str) -> str:
    """Whitespace collapsed, a leading bullet glyph followed by a space removed (`-35` keeps
    its sign: a bullet is a glyph and a space)."""
    return _BULLET_RE.sub("", collapse_ws(text))


def _text_grid(text: str) -> Grid:
    """Rows of a pipe-delimited table text: one row per non-empty line, cells split on `|`
    (outer pipes and GFM separator rows dropped), padded with empty cells to the widest row."""
    rows: Grid = []
    for line in text.splitlines():
        ln = line.strip()
        if not ln:
            continue
        if ln.startswith("|"):
            ln = ln[1:]
        if ln.endswith("|"):
            ln = ln[:-1]
        cells = [_norm_cell(c) for c in ln.split("|")]
        if cells and all(_SEP_RE.match(c) for c in cells):
            continue
        rows.append(cells)
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


def _table_grid(td: TableData) -> Grid:
    grid = [[""] * td.n_cols for _ in range(td.n_rows)]
    for c in td.cells:
        if 0 <= c.row < td.n_rows and 0 <= c.col < td.n_cols:
            grid[c.row][c.col] = _norm_cell(c.text)
    return grid


def _shape(g: Grid) -> tuple[int, int]:
    return len(g), (len(g[0]) if g else 0)


def _position_failures(
    base: Grid,
    prop: Grid,
    others: Mapping[str, Grid],
    raw_source: str,
    has_numeric_spec: bool,
) -> tuple[list[str], list[str]]:
    """(failures, attested changes) of `prop` against `base`, cell by cell."""
    bad: list[str] = []
    changed: list[str] = []
    for r, row in enumerate(prop):
        for c, new in enumerate(row):
            old = base[r][c]
            if new == old:
                continue
            at = f"({r},{c}) {_clip(old, 16)!r}→{_clip(new, 16)!r}"
            who = sorted(k for k, g in others.items() if g[r][c] == new)
            if not who:
                bad.append(f"{at} [no reader shows it there]")
                continue
            cell_readers = {raw_source: old, **{k: g[r][c] for k, g in others.items()}}
            n = numeric_attested(old, cell_readers, raw_source, new, None, has_numeric_spec)
            if not n.passed:
                bad.append(f"{at} [{n.detail}]")
                continue
            changed.append(f"{at} [{', '.join(who)}]")
    return bad, changed


def check_table_position(
    block: Block,
    cells: Sequence[Sequence[str]],
    readers: Mapping[str, str],
    raw_source: str,
    has_numeric_spec: bool,
) -> RecheckResult:
    """Cells compared by position (row, col) with the raw table: the parsed structure of the
    raw source, or its raw_text rows. The shape must equal one of them; every cell must equal
    the raw cell at that position (whitespace and bullets normalized), except cells the
    proposal changes, each of which an independent reader must show at the SAME position and
    which must pass the numeric-attestation rule there. Moving values between cells or rows
    (a permutation the multiset checks cannot see) fails."""
    prop: Grid = [[_norm_cell(str(c)) for c in row] for row in cells]
    shape = _shape(prop)
    bases: list[tuple[str, Grid]] = []
    if block.table is not None:
        bases.append(("parsed table", _table_grid(block.table)))
    tg = _text_grid(block.raw_text)
    if tg and all(tg != g for _n, g in bases):
        bases.append(("raw rows", tg))
    same = [(n, g) for n, g in bases if _shape(g) == shape]
    if not same:
        have = ", ".join(f"{n} {a}x{b}" for n, (a, b) in ((n, _shape(g)) for n, g in bases))
        return _r(
            "table_position",
            False,
            f"{shape[0]}x{shape[1]} cells match no raw shape ({have or 'no raw table'})",
        )
    others = {
        k: g
        for k, v in sorted(readers.items())
        if k != raw_source and _shape(g := _text_grid(v)) == shape
    }
    best: tuple[str, list[str], list[str]] | None = None
    for name, grid in same:
        bad, changed = _position_failures(grid, prop, others, raw_source, has_numeric_spec)
        if not bad:
            what = f"; changed: {'; '.join(changed)}" if changed else ""
            return _r("table_position", True, f"cells match the {name} by position{what}")
        if best is None or len(bad) < len(best[1]):
            best = (name, bad, changed)
    assert best is not None
    return _r("table_position", False, f"vs the {best[0]}: " + "; ".join(best[1][:4]))


# -- figures and groups -------------------------------------------------------------------------


@dataclass
class Resolved:
    """The model's payload turned into proposal fields, plus facts the checks need."""

    fields: dict[str, Any]
    extra: dict[str, Any] = field(default_factory=dict)


def _article_facts(
    paths: ProjectPaths, data: ProjectData, slug: str
) -> tuple[dict[str, list[str]], dict[str, Block]]:
    gf = data.groups(slug)
    sel = data.selection()
    selected = {b for b in sel.block_ids if ids.parse_block_id(b)[0] == slug}
    blocks = {b.id: b for b in data.raw_blocks(slug)}
    order = {b.id: b.reading_order for b in blocks.values()}
    arts = build_articles(slug, gf, selected, sel.article_split, order) if gf is not None else {}
    return arts, blocks


def resolve_payload(
    inp: AgentInput,
    payload: Mapping[str, Any],
    paths: ProjectPaths,
    data: ProjectData,
) -> Resolved:
    """Model payload -> Proposal fields. The model only chose; ids and coordinates come from
    the candidates."""
    item = inp.item
    slug = item.doc_id
    if inp.kind == ProposalKind.text:
        return Resolved({"proposal_text": str(payload["proposal_text"])})
    if inp.kind == ProposalKind.cells:
        cells = [[str(c) for c in row] for row in payload["cells"]]
        header = int(payload.get("header_rows", 0))
        out: dict[str, Any] = {"proposed_cells": cells}
        extra: dict[str, Any] = {"header_rows": header}
        if check_shape_cells(cells).passed:
            blk = next((b for b in data.raw_blocks(slug) if b.id == item.target_id), None)
            td = build_table_data(
                cells, header, blk.table.shape_by_parser if blk and blk.table else None
            )
            out["proposal_text"] = td.markdown
            extra["td"] = td
        else:
            out["proposal_text"] = cells_text(cells) or "(empty)"
        return Resolved(out, extra)
    choice = str(payload["choice"])
    if inp.kind == ProposalKind.bbox:
        cand = next(c for c in inp.candidates if str(c["id"]) == choice)
        return Resolved({"proposed_bbox": [float(v) for v in cand["bbox"]]}, {"candidate": cand})
    if inp.kind == ProposalKind.regroup:
        return Resolved(
            {"proposed_regroup": {"block_id": item.target_id, "to_topic_slug": choice}},
            {},
        )
    # attach
    arts, blocks = _article_facts(paths, data, slug)
    if item.target_id.startswith("FIG-"):
        article = choice
        anchor = _anchor_for(paths, data, slug, item.target_id, arts.get(article, []), blocks)
        fig = item.target_id
    else:
        fig = choice
        mine = data.articles_of(slug, item.target_id)
        article = mine[0] if mine else ids.article_id(slug, None)
        anchor = item.target_id
    return Resolved(
        {"proposed_attach": {"figure_id": fig, "article_id": article, "anchor_block_id": anchor}}
    )


def _anchor_for(
    paths: ProjectPaths,
    data: ProjectData,
    slug: str,
    figure_id: str,
    members: Sequence[str],
    blocks: Mapping[str, Block],
) -> str | None:
    ff = figure_facts(paths, data, figure_id)
    cap = ff.record.caption_original if ff is not None and ff.record is not None else None
    num = caption_number(cap)
    if num is None:
        return None
    chaptered = is_chaptered([num])
    for m in members:
        b = blocks.get(m)
        if b is not None and any(r.number == num for r in find_refs(b.raw_text, chaptered)):
            return m
    return None


def check_changed_attach(
    data: ProjectData, slug: str, figure_id: str, article_id: str
) -> RecheckResult:
    af = data.attach(slug)
    if af is not None:
        for art in af.articles:
            if art.article_id == article_id and any(a.figure_id == figure_id for a in art.figures):
                return _r("changed", False, "the figure is already attached to that article")
    return _r("changed", True)


def check_attach_target(
    paths: ProjectPaths, data: ProjectData, figure_id: str, article_id: str
) -> RecheckResult:
    try:
        fslug = ids.parse_figure_id(figure_id)[0]
        aslug, _topic = ids.parse_article_id(article_id)
    except ValueError as exc:
        return _r("attach_target", False, str(exc))
    if fslug != aslug:
        return _r("attach_target", False, "figure and article belong to different documents")
    ff = figure_facts(paths, data, figure_id)
    if ff is None or ff.record is None:
        return _r("attach_target", False, "the figure has no sidecar (extraction failed)")
    img = paths.figure_dir(fslug) / (ff.record.svg or ff.record.file)
    alt = paths.figure_dir(fslug) / ff.record.file
    if not img.is_file() and not alt.is_file():
        return _r("attach_target", False, "the figure has no image file")
    arts, _blocks = _article_facts(paths, data, fslug)
    if article_id not in arts:
        return _r("attach_target", False, "the article is not in the current selection")
    return _r("attach_target", True)


def check_attach_evidence(
    paths: ProjectPaths, data: ProjectData, figure_id: str, article_id: str
) -> RecheckResult:
    """A deterministic rule supports (figure, article): caption_ref, caption_match or
    proximity (05 section 5.2)."""
    slug = ids.parse_figure_id(figure_id)[0]
    ff = figure_facts(paths, data, figure_id)
    if ff is None:
        return _r("attach_evidence", False, "unknown figure")
    arts, blocks = _article_facts(paths, data, slug)
    members = [blocks[m] for m in arts.get(article_id, []) if m in blocks]
    if not members:
        return _r("attach_evidence", False, "the article has no blocks")
    caption = ff.record.caption_original if ff.record is not None else None
    num = caption_number(caption)
    chaptered = is_chaptered([num])
    if num is not None:
        for b in members:
            if any(r.number == num for r in find_refs(b.raw_text, chaptered)):
                return _r("attach_evidence", True, f"caption_ref: {b.id} cites figure {num}")
    if caption:
        cap = caption_content(caption)
        if len(cap) >= MATCH_MIN_TOKENS:
            for b in members:
                common = cap & content(b.raw_text)
                if len(common) >= MATCH_MIN_TOKENS and len(common) / len(cap) >= T_MATCH:
                    return _r(
                        "attach_evidence",
                        True,
                        f"caption_match: {b.id} shares {sorted(common)[:4]}",
                    )
    pages = {b.page for b in members}
    if any(abs(p - ff.block.page) <= 1 for p in pages):
        return _r(
            "attach_evidence", True, f"proximity: figure page {ff.block.page} within article pages"
        )
    return _r("attach_evidence", False, "no caption reference, caption match or nearby page")


def check_changed_regroup(data: ProjectData, slug: str, block_id: str, to: str) -> RecheckResult:
    gf = data.groups(slug)
    cur = topic_of(gf, block_id) if gf is not None else None
    if cur is not None and cur.slug == to:
        return _r("changed", False, "the block is already in that topic")
    return _r("changed", True)


def check_regroup_target(data: ProjectData, slug: str, block_id: str, to: str) -> RecheckResult:
    gf = data.groups(slug)
    if gf is None:
        return _r("regroup_target", False, "the document has no topic view")
    target = next((t for t in gf.topics if t.slug == to and not t.is_unassigned), None)
    cur = topic_of(gf, block_id)
    if target is None:
        return _r("regroup_target", False, f"no topic {to!r}")
    if cur is None:
        return _r("regroup_target", False, "the block is unassigned; use Verify")
    topics = []
    for t in gf.topics:
        if t.id == cur.id:
            ids_ = [b for b in t.block_ids if b != block_id]
            topics.append(t.model_copy(update={"block_ids": ids_, "block_count": len(ids_)}))
        elif t.id == target.id:
            ids_ = [*t.block_ids, block_id]
            topics.append(t.model_copy(update={"block_ids": ids_, "block_count": len(ids_)}))
        else:
            topics.append(t)
    problems = check_partition(
        data.raw_blocks(slug),
        gf.model_copy(update={"topics": topics, "overlap": overlap(gf.structure, topics)}),
    )
    if problems:
        return _r("regroup_target", False, "; ".join(problems[:2]))
    return _r("regroup_target", True, f"{cur.slug} → {to}")


def check_regroup_similarity(
    data: ProjectData, slug: str, block_id: str, to: str, emb: DocEmbeddings | None
) -> RecheckResult:
    gf = data.groups(slug)
    if gf is None or emb is None:
        return _r("regroup_similarity", False, "embeddings are unavailable")
    vec = emb.vec(block_id)
    cur = topic_of(gf, block_id)
    target = next((t for t in gf.topics if t.slug == to), None)
    if vec is None or cur is None or target is None:
        return _r("regroup_similarity", False, "the block has no embedding")
    c_cur, c_new = emb.centroid_of(cur.block_ids), emb.centroid_of(target.block_ids)
    if c_cur is None or c_new is None:
        return _r("regroup_similarity", False, "a topic has no embedded block")
    s_cur, s_new = cosine(vec, c_cur), cosine(vec, c_new)
    ok = s_new >= s_cur
    return _r("regroup_similarity", ok, f"target {s_new:.3f} vs current {s_cur:.3f}")


# -- bbox ----------------------------------------------------------------------------------------

_BODY: Final = frozenset(
    {BlockType.paragraph, BlockType.list, BlockType.heading, BlockType.other, BlockType.table}
)


def check_changed_bbox(new: Sequence[float], cur: Sequence[float] | None) -> RecheckResult:
    if cur is not None and g.iou(new, cur) >= BBOX_IOU_SAME:
        return _r("changed", False, f"IoU with the current crop is {g.iou(new, cur):.2f}")
    return _r("changed", True)


def check_bbox_geometry(bbox: Sequence[float], page: Sequence[float]) -> RecheckResult:
    w, h = g.width(bbox), g.height(bbox)
    if (
        bbox[0] < page[0] - 0.01
        or bbox[1] < page[1] - 0.01
        or bbox[2] > page[2] + 0.01
        or bbox[3] > page[3] + 0.01
    ):
        return _r("bbox_geometry", False, "the box leaves the page")
    if min(w, h) < BBOX_MIN_SIDE:
        return _r("bbox_geometry", False, f"min side {min(w, h):.0f} pt < {BBOX_MIN_SIDE:.0f}")
    frac = g.area(bbox) / g.area(page) if g.area(page) > 0 else 0.0
    if frac < BBOX_MIN_AREA_FRAC or frac >= BBOX_MAX_AREA_FRAC:
        return _r("bbox_geometry", False, f"area fraction {frac:.3f} outside [0.002, 0.9)")
    return _r("bbox_geometry", True, f"{w:.0f}x{h:.0f} pt, {frac:.3f} of the page")


def check_bbox_text_overlap(
    bbox: Sequence[float], blocks: Sequence[Block], page_no: int
) -> RecheckResult:
    bad: list[str] = []
    for b in blocks:
        if b.page != page_no or b.type not in _BODY or b.bbox is None:
            continue
        a = g.area(b.bbox)
        if a > 0 and g.intersection(b.bbox, bbox) > BBOX_TEXT_OVERLAP_MAX * a:
            bad.append(b.id)
    if bad:
        return _r("bbox_text_overlap", False, f"covers body text: {', '.join(bad[:3])}")
    return _r("bbox_text_overlap", True)


def ink_fraction(pdf_path: Any, page_no: int, bbox: Sequence[float]) -> float:
    from manuallabor.parse.pdf_pymupdf import open_pdf, pm

    with open_pdf(pdf_path) as doc:
        pg = doc[page_no - 1]
        pix = pg.get_pixmap(clip=pm().Rect(*bbox), dpi=72, colorspace=pm().csGRAY)
        samples = pix.samples
    if not samples:
        return 0.0
    return sum(1 for v in samples if v < 200) / len(samples)


def check_bbox_content(frac: float) -> RecheckResult:
    if frac < BBOX_INK_MIN:
        return _r("bbox_content", False, f"ink fraction {frac:.3f} < {BBOX_INK_MIN}")
    return _r("bbox_content", True, f"ink fraction {frac:.3f}")


# -- orchestration -------------------------------------------------------------------------------


def run_rechecks(
    inp: AgentInput,
    res: Resolved,
    evidence: Sequence[EvidenceRef],
    paths: ProjectPaths,
    data: ProjectData,
    emb_for: Callable[[], DocEmbeddings | None],
) -> list[RecheckResult]:
    """The category's recheck list in the order of `RECHECKS` (the contract sorts by name)."""
    item = inp.item
    slug = item.doc_id
    kind = inp.kind
    out: list[RecheckResult] = []
    f = res.fields
    if kind in (ProposalKind.text, ProposalKind.cells):
        block = next(b for b in data.machine_blocks(slug) if b.id == item.target_id)
        ctx = data.contexts(slug)[block.id]
        sf = data.score_file(slug)
        variants: list[NumericVariant] = []
        if sf is not None:
            for s in sf.blocks:
                if s.block_id == block.id and s.faithfulness is not None:
                    variants = list(s.faithfulness.numeric_variants)
        raw_block = block.model_copy(update={"clean_text": None})
        text = str(f["proposal_text"])
        if kind == ProposalKind.text:
            out.append(check_shape_text(text, inp.max_text))
            out.append(check_changed_text(text, inp.current))
            out.append(check_evidence(evidence))
            out.append(attested_faithfulness(raw_block, ctx, variants, text))
            out.append(
                numeric_attested(
                    block.raw_text,
                    inp.readers,
                    block.raw_source,
                    text,
                    inp.vision,
                    block.has_numeric_spec,
                )
            )
            out.append(check_token_whitespace(block.raw_text, text, inp.readers, block.raw_source))
            out.append(check_garbage(block.raw_text, text))
            out.append(check_parser_agreement(block.raw_text, text, inp.readers, block.raw_source))
        else:
            cells = f["proposed_cells"]
            shape = check_shape_cells(cells)
            out.append(shape)
            out.append(check_changed_text(text, inp.current))
            out.append(check_evidence(evidence))
            ctext = cells_text(cells)
            if shape.passed:
                out.append(
                    check_table_coverage(block.raw_text, cells, inp.readers, block.raw_source)
                )
                out.append(
                    check_table_position(
                        block, cells, inp.readers, block.raw_source, block.has_numeric_spec
                    )
                )
            else:
                out.append(_r("table_coverage", False, "cells are malformed"))
                out.append(_r("table_position", False, "cells are malformed"))
            out.append(
                numeric_attested(
                    block.raw_text,
                    inp.readers,
                    block.raw_source,
                    ctext,
                    inp.vision,
                    block.has_numeric_spec,
                )
            )
            td = res.extra.get("td")
            if td is not None:
                out.append(check_table_consistency(block, td))
            else:
                out.append(_r("table_consistency", False, "cells are malformed"))
        return out
    if kind == ProposalKind.attach:
        pa = f["proposed_attach"]
        out.append(check_changed_attach(data, slug, pa["figure_id"], pa["article_id"]))
        out.append(check_evidence(evidence))
        out.append(check_attach_target(paths, data, pa["figure_id"], pa["article_id"]))
        out.append(check_attach_evidence(paths, data, pa["figure_id"], pa["article_id"]))
        return out
    if kind == ProposalKind.regroup:
        pr = f["proposed_regroup"]
        out.append(check_changed_regroup(data, slug, pr["block_id"], pr["to_topic_slug"]))
        out.append(check_evidence(evidence))
        out.append(check_regroup_target(data, slug, pr["block_id"], pr["to_topic_slug"]))
        out.append(
            check_regroup_similarity(data, slug, pr["block_id"], pr["to_topic_slug"], emb_for())
        )
        return out
    # bbox
    bbox = f["proposed_bbox"]
    ff = figure_facts(paths, data, item.target_id)
    cur = ff.bbox if ff is not None else None
    page_no = ff.block.page if ff is not None else 1
    out.append(check_changed_bbox(bbox, cur))
    out.append(check_evidence(evidence))
    page = inp.page_rect
    if page is None:
        out.append(_r("bbox_geometry", False, "no page geometry"))
        out.append(_r("bbox_text_overlap", False, "no page geometry"))
        out.append(_r("bbox_content", False, "no page geometry"))
        return out
    out.append(check_bbox_geometry(bbox, page))
    out.append(check_bbox_text_overlap(bbox, data.raw_blocks(slug), page_no))
    doc = data.document(slug)
    out.append(check_bbox_content(ink_fraction(paths.source(doc.filename), page_no, bbox)))
    return out
