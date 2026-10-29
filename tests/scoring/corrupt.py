"""Seeded corruption harness (design 9, test-only).

A corruption takes the parsed fixture block (and its document's blocks) and returns a mutated
copy; the copy is re-scored with its real page context. Targets are deterministic: the first
block in reading order that matches the predicate."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from manuallabor.contracts.block import Block, TableShape
from manuallabor.contracts.enums import BlockType
from manuallabor.scoring.pipeline import score_block
from manuallabor.scoring.types import BlockScore
from tests.scoring.conftest import Scored

Corruption = Callable[[Block, list[Block]], Block]
Target = Callable[[Scored, list[Block]], Block]

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def in_order(blocks: list[Block]) -> list[Block]:
    return sorted(blocks, key=lambda b: b.reading_order)


def first(blocks: list[Block], pred: Callable[[Block], bool]) -> Block:
    for b in in_order(blocks):
        if pred(b):
            return b
    raise LookupError("no block matches the corruption target")


def rescore(sp: Scored, slug: str, block: Block, threshold: float = 0.85) -> BlockScore:
    """Re-score a (mutated) block with its real page context."""
    blocks = [block if b.id == block.id else b for b in sp.blocks(slug)]
    ctx = sp.contexts(slug, blocks)[block.id]
    return score_block(block, ctx, threshold=threshold)


def signal(score: BlockScore, name: str) -> tuple[float, bool, str]:
    s = next(s for s in score.signals if s.name.value == name)
    return s.value, s.critical, s.detail or ""


# -- targets ----------------------------------------------------------------------------------


def is_para(b: Block) -> bool:
    return b.type == BlockType.paragraph


def torque_para(sp: Scored, blocks: list[Block]) -> Block:
    return first(blocks, lambda b: is_para(b) and "35 N·m" in b.raw_text)


def non_numeric_para(sp: Scored, blocks: list[Block]) -> Block:
    scores = {s.block_id: s for s in sp_scores(sp, blocks[0].doc_id)}
    return first(blocks, lambda b: is_para(b) and not scores[b.id].has_numeric_spec)


def p3_para(sp: Scored, blocks: list[Block]) -> Block:
    return first(blocks, lambda b: is_para(b) and b.page == 3)


def sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_RE.split(" ".join(text.split())) if s]


def two_sentence_para(sp: Scored, blocks: list[Block]) -> Block:
    scores = {s.block_id: s for s in sp_scores(sp, blocks[0].doc_id)}
    return first(
        blocks,
        lambda b: (
            is_para(b) and not scores[b.id].has_numeric_spec and len(sentences(b.raw_text)) >= 2
        ),
    )


def nth_table(n: int) -> Target:
    def t(sp: Scored, blocks: list[Block]) -> Block:
        tables = [b for b in in_order(blocks) if b.type == BlockType.table]
        return tables[n]

    return t


def table_with_empty_neighbour(sp: Scored, blocks: list[Block]) -> Block:
    for b in in_order(blocks):
        if b.type == BlockType.table and b.table is not None and _movable_cell(b) is not None:
            return b
    raise LookupError("no table with an empty cell next to a body cell")


def scanned_35(sp: Scored, blocks: list[Block]) -> Block:
    return first(
        blocks, lambda b: "35" in b.raw_text_by_parser.get("ocr", "") and b.raw_source == "ocr"
    )


def column_pair(sp: Scored, blocks: list[Block]) -> tuple[Block, Block]:
    """twocol p2: the first column-0 and first column-1 paragraphs with >= 2 lines."""
    lay = next(pl for pl in sp.layouts("twocol") if pl.page == 2)

    def pick(col: int) -> Block:
        return first(
            blocks,
            lambda b: (
                b.page == 2
                and is_para(b)
                and lay.block_columns.get(b.id) == col
                and b.raw_text.count("\n") >= 1
            ),
        )

    return pick(0), pick(1)


def sp_scores(sp: Scored, slug: str) -> list[BlockScore]:
    from manuallabor.contracts.io import read_json
    from manuallabor.scoring.types import ScoreFile

    return read_json(sp.paths.doc(slug).scores, ScoreFile).blocks


# -- mutations ---------------------------------------------------------------------------------


def interleave(a: str, b: str) -> str:
    la, lb = a.split("\n"), b.split("\n")
    out: list[str] = []
    for i in range(max(len(la), len(lb))):
        if i < len(la):
            out.append(la[i])
        if i < len(lb):
            out.append(lb[i])
    return "\n".join(out)


def gfm_rows(b: Block) -> list[list[str]]:
    """The block's table grid as GFM rows (header first), covered span slots empty."""
    assert b.table is not None
    t = b.table
    grid = [["" for _ in range(t.n_cols)] for _ in range(t.n_rows)]
    for c in t.cells:
        grid[c.row][c.col] = c.text.replace("|", "\\|")
    return grid


def to_gfm(rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _movable_cell(b: Block) -> tuple[int, int, int] | None:
    """(row, col, target col): a non-empty body cell with an empty right/left neighbour."""
    rows = gfm_rows(b)
    assert b.table is not None
    origins = {(c.row, c.col) for c in b.table.cells}
    for r, row in enumerate(rows):
        if r == 0:
            continue
        for c, text in enumerate(row):
            if not text.strip():
                continue
            for d in (1, -1):
                k = c + d
                if 0 <= k < len(row) and not row[k].strip() and (r, k) not in origins:
                    return r, c, k
    return None


def drop_body_row(b: Block, n: int) -> str:
    rows = gfm_rows(b)
    return to_gfm(rows[:n] + rows[n + 1 :])


def move_cell(b: Block) -> str:
    rows = gfm_rows(b)
    found = _movable_cell(b)
    assert found is not None
    r, c, k = found
    rows[r][k], rows[r][c] = rows[r][c], ""
    return to_gfm(rows)


def insert_not(text: str) -> str:
    toks = list(re.finditer(r"\S+", text))
    s = toks[1].start()
    return text[:s] + "not " + text[s:]


@dataclass
class Case:
    name: str
    fixture: str
    target: Target
    mutate: Corruption
    catching: str  # the signal that must catch it
    expect: str  # human-readable assertion
    notes: list[str] = field(default_factory=list)


def _table_minus_row(b: Block, _: list[Block]) -> Block:
    assert b.table is not None
    shapes = dict(b.table.shape_by_parser)
    d = shapes["docling"]
    shapes["docling"] = TableShape(rows=d.rows - 1, cols=d.cols)
    table = b.table.model_copy(update={"shape_by_parser": shapes})
    lines = b.raw_text_by_parser["docling"].split("\n")
    texts = dict(b.raw_text_by_parser)
    texts["docling"] = "\n".join(lines[:3] + lines[4:])  # body row 3 (line 0 is the header)
    return b.model_copy(update={"table": table, "raw_text_by_parser": texts})


CASES: list[Case] = [
    Case(
        "H1",
        "clean",
        torque_para,
        lambda b, _: b.model_copy(update={"clean_text": b.raw_text.replace("35", "36", 1)}),
        "faithfulness",
        "value 0.0, conf 0.0, queued",
    ),
    Case(
        "H2",
        "clean",
        torque_para,
        lambda b, _: b.model_copy(
            update={
                "raw_text_by_parser": {
                    **b.raw_text_by_parser,
                    "docling": b.raw_text_by_parser["docling"].replace("35", "36", 1),
                }
            }
        ),
        "parser_agreement",
        "parser_agreement <= 0.5 critical, conf < 0.85",
    ),
    Case(
        "H3",
        "clean",
        torque_para,
        lambda b, _: b.model_copy(
            update={
                "raw_text": b.raw_text.replace("35", "3S", 1),
                "raw_text_by_parser": {
                    **b.raw_text_by_parser,
                    "pymupdf": b.raw_text_by_parser["pymupdf"].replace("35", "3S", 1),
                },
            }
        ),
        "textlayer_vs_ocr",
        "confusable '3S' vs '35'; conf <= 0.5",
    ),
    Case(
        "H5a",
        "tables",
        nth_table(0),
        lambda b, _: b.model_copy(update={"clean_text": drop_body_row(b, 3)}),
        "faithfulness",
        "deletion + numeric_mismatch; conf 0.0",
    ),
    Case(
        "H5b",
        "tables",
        nth_table(0),
        _table_minus_row,
        "table_consistency",
        "table_consistency 6/7 + parser_agreement numeric; conf < 0.85",
    ),
    Case(
        "H5c",
        "tables",
        table_with_empty_neighbour,
        lambda b, _: b.model_copy(update={"clean_text": move_cell(b)}),
        "faithfulness",
        "cell position violation; conf 0.0",
    ),
    Case(
        "H6",
        "clean",
        non_numeric_para,
        lambda b, _: b.model_copy(update={"clean_text": insert_not(b.raw_text)}),
        "faithfulness",
        "insertion; conf 0.0",
    ),
    Case(
        "H9",
        "scanned",
        scanned_35,
        lambda b, _: b.model_copy(
            update={
                "raw_text": b.raw_text.replace("35", "3S", 1),
                "raw_text_by_parser": {
                    **b.raw_text_by_parser,
                    "ocr": b.raw_text_by_parser["ocr"].replace("35", "3S", 1),
                },
            }
        ),
        "parser_agreement",
        "parser_agreement numeric; conf <= 0.5",
    ),
]
