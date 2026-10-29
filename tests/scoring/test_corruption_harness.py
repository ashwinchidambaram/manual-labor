"""Test 18 (gate): seeded corruptions H1-H9 land below the threshold, caught by the named
signal; the legitimate edits (header/footer removal, evidence-backed reorder) stay above."""

from __future__ import annotations

import re

import pytest

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType, DiffOpKind, FaithViolationKind
from manuallabor.scoring.types import BlockScore
from tests.scoring import corrupt as H
from tests.scoring.conftest import Scored

THRESHOLD = 0.85
RESULTS: dict[str, tuple[float | None, str]] = {}


def _record(name: str, s: BlockScore, catching: str) -> None:
    RESULTS[name] = (s.confidence, catching)
    print(f"\n{name}: confidence={s.confidence} caught by {catching}; status={s.status}")


def _kinds(s: BlockScore) -> set[FaithViolationKind]:
    assert s.faithfulness is not None
    return {v.kind for v in s.faithfulness.violations}


@pytest.fixture(scope="module")
def sp(scoredproj: Scored) -> Scored:
    return scoredproj


def _case(name: str) -> H.Case:
    return next(c for c in H.CASES if c.name == name)


def _run(sp: Scored, name: str) -> BlockScore:
    c = _case(name)
    blocks = sp.blocks(c.fixture)
    target = c.target(sp, blocks)
    s = H.rescore(sp, c.fixture, c.mutate(target, blocks))
    _record(name, s, c.catching)
    return s


def test_h1_digit_swap_in_cleanup(sp: Scored) -> None:
    s = _run(sp, "H1")
    v, crit, _ = H.signal(s, "faithfulness")
    assert v == 0.0 and crit
    assert {FaithViolationKind.deletion, FaithViolationKind.numeric_mismatch} <= _kinds(s)
    assert s.confidence == 0.0 and s.status == "queued"


def test_h2_digit_swap_in_second_parser(sp: Scored) -> None:
    s = _run(sp, "H2")
    v, crit, detail = H.signal(s, "parser_agreement")
    assert v <= 0.5 and crit and "'35' vs '36'" in detail
    assert s.confidence is not None and s.confidence < THRESHOLD


def test_h3_corrupt_text_layer(sp: Scored) -> None:
    s = _run(sp, "H3")
    v, crit, detail = H.signal(s, "textlayer_vs_ocr")
    assert crit and v <= 0.5 and "confusable '3S' vs '35'" in detail
    pa, pa_crit, _ = H.signal(s, "parser_agreement")
    assert pa <= 0.5 and pa_crit
    assert s.confidence is not None and s.confidence <= 0.5


def test_h4_merged_columns(sp: Scored) -> None:
    blocks = sp.blocks("twocol")
    a, b = H.column_pair(sp, blocks)
    mixed = H.interleave(a.raw_text, b.raw_text)
    # H4a: the text layer itself interleaves two columns
    h4a = a.model_copy(
        update={
            "raw_text": mixed,
            "raw_text_by_parser": {**a.raw_text_by_parser, "pymupdf": mixed},
        }
    )
    s = H.rescore(sp, "twocol", h4a)
    _record("H4a", s, "parser_agreement")
    v, crit, _ = H.signal(s, "parser_agreement")
    assert v < 0.8 and crit
    assert s.confidence is not None and s.confidence < 0.8
    # H4b: cleanup interleaves the neighbouring column into the block
    h4b = a.model_copy(update={"clean_text": mixed})
    s = H.rescore(sp, "twocol", h4b)
    _record("H4b", s, "faithfulness")
    assert FaithViolationKind.insertion in _kinds(s)
    assert s.confidence == 0.0


def test_h5a_dropped_table_row(sp: Scored) -> None:
    s = _run(sp, "H5a")
    assert {FaithViolationKind.deletion, FaithViolationKind.numeric_mismatch} <= _kinds(s)
    assert s.confidence == 0.0


def test_h5b_parser_missed_a_row(sp: Scored) -> None:
    s = _run(sp, "H5b")
    tc, _, detail = H.signal(s, "table_consistency")
    assert tc == pytest.approx(6 / 7, abs=1e-6), detail
    pa, crit, _ = H.signal(s, "parser_agreement")
    assert crit and pa <= 0.5
    assert s.confidence is not None and s.confidence < THRESHOLD


def test_h5c_value_moved_to_neighbour_cell(sp: Scored) -> None:
    s = _run(sp, "H5c")
    assert s.faithfulness is not None and not s.faithfulness.passed
    assert s.confidence == 0.0


def test_h6_inserted_negation(sp: Scored) -> None:
    s = _run(sp, "H6")
    assert FaithViolationKind.insertion in _kinds(s)
    assert s.confidence == 0.0
    # documented limit: the same insert into the second parser's text only lowers agreement
    c = _case("H6")
    blocks = sp.blocks("clean")
    t = c.target(sp, blocks)
    texts = {**t.raw_text_by_parser, "docling": H.insert_not(t.raw_text_by_parser["docling"])}
    s2 = H.rescore(sp, "clean", t.model_copy(update={"raw_text_by_parser": texts}))
    v, _, detail = H.signal(s2, "parser_agreement")
    assert v < 1.0 and "not" in detail


def test_h7_header_footer_removal_is_allowed(sp: Scored) -> None:
    blocks = sp.blocks("clean")
    t = H.p3_para(sp, blocks)
    # this page's footer (another page's `Page n` is body text here: design 4.1 AE3)
    raw = t.raw_text + "\nAcme X200 Service Manual" + f"\nPage {t.page}"
    s = H.rescore(sp, "clean", t.model_copy(update={"raw_text": raw, "clean_text": t.raw_text}))
    _record("H7 (legit)", s, "faithfulness passes")
    assert s.faithfulness is not None and s.faithfulness.passed
    assert s.faithfulness.violations == []
    assert H.signal(s, "faithfulness")[0] == 1.0


def test_h8_sentence_reorder(sp: Scored) -> None:
    blocks = sp.blocks("clean")
    t = H.two_sentence_para(sp, blocks)
    sents = H.sentences(t.raw_text)
    swapped = " ".join([sents[1], sents[0], *sents[2:]])
    # H8a: no reader saw that order -> reorder violation
    s = H.rescore(sp, "clean", t.model_copy(update={"clean_text": swapped}))
    _record("H8a", s, "faithfulness (reorder)")
    assert FaithViolationKind.reorder in _kinds(s)
    assert s.confidence == 0.0
    # H8b: docling also read s2 s1 -> attested reorder passes at 0.9
    texts = {**t.raw_text_by_parser, "docling": swapped}
    s = H.rescore(
        sp, "clean", t.model_copy(update={"clean_text": swapped, "raw_text_by_parser": texts})
    )
    _record("H8b (legit)", s, "faithfulness passes via reorder")
    assert s.faithfulness is not None and s.faithfulness.passed
    assert any(op.op == DiffOpKind.reorder and op.allowed for op in s.faithfulness.diff)
    assert H.signal(s, "faithfulness")[0] == 0.9
    assert s.confidence is not None and s.confidence >= THRESHOLD


def test_h9_scanned_ocr_misread(sp: Scored) -> None:
    s = _run(sp, "H9")
    v, crit, detail = H.signal(s, "parser_agreement")
    assert crit and v <= 0.5, detail
    assert s.confidence is not None and s.confidence <= 0.5


def test_legit_dehyphenated_cleanup_stays_above(sp: Scored) -> None:
    """Hyphen join + line join on a non-numeric clean paragraph keeps it auto-approved."""
    blocks = sp.blocks("clean")
    t = H.non_numeric_para(sp, blocks)
    clean = " ".join(t.raw_text.replace("-\n", "").split())
    s = H.rescore(sp, "clean", t.model_copy(update={"clean_text": clean}))
    _record("hyphen/line join (legit)", s, "faithfulness passes")
    assert s.faithfulness is not None and s.faithfulness.passed
    assert s.confidence is not None and s.confidence >= THRESHOLD


_BULLET_RE = re.compile(r"^[ \t]*[•·◦▪‣●*–-][ \t]+")
_HYPHEN_BREAK_RE = re.compile(r"(?<=[^\W\d_])-[ \t]*\n[ \t]*(?=[^\W\d_])")


def deterministic_cleanup(b: Block, hf: set[str]) -> str:
    """The lossless cleanup passes of SPEC 4.6 without a model: drop recorded header/footer
    lines, join hyphenated line breaks, normalize bullets, join wrapped lines (a list keeps one
    item per line), collapse whitespace; a table becomes its GFM markdown."""
    if b.type == BlockType.table and b.table is not None and b.table.markdown.strip():
        return b.table.markdown
    lines = [ln for ln in b.raw_text.split("\n") if " ".join(ln.split()) not in hf]
    text = _HYPHEN_BREAK_RE.sub("", "\n".join(lines))
    out: list[str] = []
    for ln in text.split("\n"):
        item = _BULLET_RE.match(ln) is not None
        ln = " ".join(_BULLET_RE.sub("- ", ln).split())
        if not ln:
            continue
        if out and not (item and b.type == BlockType.list):
            out[-1] = f"{out[-1]} {ln}"
        else:
            out.append(ln)
    return "\n".join(out)


def test_fixture_wide_legit_cleanup_stays_above(sp: Scored) -> None:
    """Every text block of clean.pdf with the deterministic cleanup passes faithfulness and
    stays >= the threshold unless it is a numeric-spec block (always reviewed anyway)."""
    doc = sp.doc("clean")
    hf = {" ".join(h.split()) for h in (*doc.stripped_headers, *doc.stripped_footers)}
    blocks = sp.blocks("clean")
    n = changed = 0
    low: list[tuple[str, float | None]] = []
    for b in H.in_order(blocks):
        if b.type in (BlockType.header, BlockType.footer, BlockType.figure) or not b.raw_text:
            continue
        clean = deterministic_cleanup(b, hf)
        s = H.rescore(sp, "clean", b.model_copy(update={"clean_text": clean}))
        n += 1
        changed += clean != b.raw_text
        assert s.faithfulness is not None and s.faithfulness.passed, (
            b.id,
            [(v.kind.value, v.raw, v.clean) for v in s.faithfulness.violations],
        )
        if not s.has_numeric_spec and (s.confidence is None or s.confidence < THRESHOLD):
            low.append((b.id, s.confidence))
    print(f"\nclean.pdf legit cleanup: {n} blocks ({changed} changed), all faithful; low {low}")
    assert changed >= 10 and low == []
