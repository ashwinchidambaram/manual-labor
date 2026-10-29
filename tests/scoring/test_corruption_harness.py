"""Test 18 (gate): seeded corruptions H1-H9 land below the threshold, caught by the named
signal; the legitimate edits (header/footer removal, evidence-backed reorder) stay above."""

from __future__ import annotations

import pytest

from manuallabor.contracts.enums import DiffOpKind, FaithViolationKind
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
    raw = t.raw_text + "\nAcme X200 Service Manual" + "\nPage 7"
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
