"""Module 10 review fixes, pure part: positional table checks, the strict look-alike rule in N,
evidence that only quotes the block's own raw text, and the completeness of a stored check
list. The inputs are the reviewer's attack inputs."""

from __future__ import annotations

from typing import Any

from manuallabor.agent.propose import validate_evidence
from manuallabor.agent.recheck import (
    RECHECKS,
    attested_faithfulness,
    build_table_data,
    cells_text,
    check_table_consistency,
    check_table_coverage,
    check_table_position,
    numeric_attested,
    numbers_changed,
)
from manuallabor.agent.types import AgentInput, AgentItem
from manuallabor.contracts.block import VisionReading
from manuallabor.contracts.enums import BlockType, FlagCategory, ProposalKind
from manuallabor.contracts.proposal import REQUIRED_CHECKS, Proposal
from tests.conftest import ctx, make_block

# -- item 1: a table proposal may not move cell values ------------------------------------------

BNW = "Part | Qty\nBolt | 4\nNut | 8\nWasher | 12"
BNW_CELLS = [["Part", "Qty"], ["Bolt", "4"], ["Nut", "8"], ["Washer", "12"]]


def table_block(raw: str, cells: list[list[str]] | None, **texts: str):  # type: ignore[no-untyped-def]
    b = make_block(raw, type=BlockType.table, source="pymupdf", texts={"pymupdf": raw, **texts})
    if cells is not None:
        b = b.model_copy(update={"table": build_table_data(cells, 1)})
    return b


def position(b: Any, cells: list[list[str]], spec: bool = True) -> Any:
    return check_table_position(b, cells, dict(b.raw_text_by_parser), b.raw_source, spec)


def test_cells_kind_runs_the_position_check() -> None:
    assert "table_position" in RECHECKS[ProposalKind.cells]
    assert REQUIRED_CHECKS[ProposalKind.cells] == RECHECKS[ProposalKind.cells]


def test_permuted_values_fail_table_position() -> None:
    b = table_block(BNW, BNW_CELLS, docling=BNW)
    permuted = [["Part", "Qty"], ["Bolt", "8"], ["Nut", "12"], ["Washer", "4"]]
    # the multiset checks cannot see a permutation ...
    assert check_table_coverage(BNW, permuted, {"pymupdf": BNW}, "pymupdf").passed
    assert numeric_attested(BNW, {"pymupdf": BNW}, "pymupdf", cells_text(permuted), None, True)
    assert check_table_consistency(b, build_table_data(permuted, 1)).passed
    # ... the positional one does
    r = position(b, permuted)
    assert not r.passed and "(1,1)" in (r.detail or "")
    assert position(b, BNW_CELLS).passed


def test_reviewer_torque_swap_fails() -> None:
    raw = "Bolt | Torque\nM6 | 10 N·m\nM8 | 25 N·m"
    cur = [["Bolt", "Torque"], ["M6", "10 N·m"], ["M8", "25 N·m"]]
    swapped = [["Bolt", "Torque"], ["M6", "25 N·m"], ["M8", "10 N·m"]]
    b = table_block(raw, cur)
    assert not position(b, swapped).passed
    assert position(b, cur).passed


def test_row_order_swap_fails() -> None:
    b = table_block(BNW, BNW_CELLS, docling=BNW)
    rows = [["Part", "Qty"], ["Nut", "8"], ["Bolt", "4"], ["Washer", "12"]]
    assert not position(b, rows).passed


def test_attested_look_alike_in_one_cell_passes() -> None:
    raw = "Part | Torque\nBolt | 1O N·m\nNut | 25 N·m"
    other = "Part | Torque\nBolt | 10 N·m\nNut | 25 N·m"
    fixed = [["Part", "Torque"], ["Bolt", "10 N·m"], ["Nut", "25 N·m"]]
    b = table_block(raw, [["Part", "Torque"], ["Bolt", "1O N·m"], ["Nut", "25 N·m"]], docling=other)
    r = position(b, fixed)
    assert r.passed, r.detail
    assert "docling" in (r.detail or "")
    # the same change with no reader showing it at that position is refused
    lone = table_block(raw, None)
    assert not position(lone, fixed).passed
    # a reader that shows 10 in another row attests nothing at (1,1)
    moved = "Part | Torque\nBolt | 25 N·m\nNut | 10 N·m"
    assert not position(table_block(raw, None, docling=moved), fixed).passed


def test_new_value_in_a_cell_needs_two_attesters() -> None:
    raw = "Part | Torque\nBolt | 36 N·m"
    other = "Part | Torque\nBolt | 35 N·m"
    fixed = [["Part", "Torque"], ["Bolt", "35 N·m"]]
    assert not position(table_block(raw, None, docling=other), fixed).passed
    assert position(table_block(raw, None, docling=other, ocr=other), fixed).passed


def test_shape_must_match_the_raw_structure_or_rows() -> None:
    b = table_block(BNW, BNW_CELLS, docling=BNW)
    wide = [[*row, ""] for row in BNW_CELLS]
    assert not position(b, wide).passed
    assert not position(b, BNW_CELLS[:3]).passed
    # raw_text rows are a valid reference when the parsed structure is absent
    assert position(table_block(BNW, None), BNW_CELLS).passed


def test_whitespace_and_bullets_are_normalized() -> None:
    raw = "Step | Action\n1 | • Remove  the cover"
    cells = [["Step", "Action"], ["1", "Remove the cover"]]
    assert position(table_block(raw, None), cells).passed


def test_text_change_in_a_cell_needs_a_reader() -> None:
    raw = "Part | Note\nBolt | grade 8"
    cells = [["Part", "Note"], ["Bolt", "grade 8 steel"]]
    assert not position(table_block(raw, None), cells).passed
    other = "Part | Note\nBolt | grade 8 steel"
    assert position(table_block(raw, None, docling=other), cells).passed


def test_bulk_guard_compares_numbers_by_position() -> None:
    assert numbers_changed("A 10 then 25", "A 25 then 10")
    assert numbers_changed(BNW, "Part | Qty\nBolt | 8\nNut | 12\nWasher | 4")
    assert not numbers_changed("A 10 then 25", "A  10\nthen 25")


# -- item 5: adding or dropping a digit is never a look-alike, in N or in A ----------------------


def test_digit_insert_or_drop_needs_two_attesters() -> None:
    raw = "Torque 35 N·m"
    one = {"pymupdf": raw, "docling": "Torque 350 N·m"}
    assert not numeric_attested(raw, one, "pymupdf", "Torque 350 N·m", None, True).passed
    two = {**one, "ocr": "Torque 350 N·m"}
    assert numeric_attested(raw, two, "pymupdf", "Torque 350 N·m", None, True).passed
    raw2 = "Gap 1.5 mm"
    r2 = {"pymupdf": raw2, "docling": "Gap 15 mm"}
    assert not numeric_attested(raw2, r2, "pymupdf", "Gap 15 mm", None, True).passed
    vision = VisionReading(outcome="ok", numbers=["350"], lines=["350"])
    assert not numeric_attested(raw, {"pymupdf": raw}, "pymupdf", "Torque 350 N·m", vision, True)
    # the look-alike itself still needs only one reader
    raw3 = "Torque 3S N·m"
    r3 = {"pymupdf": raw3, "docling": "Torque 35 N·m"}
    assert numeric_attested(raw3, r3, "pymupdf", "Torque 35 N·m", None, True).passed


def test_swapped_numbers_are_compared_by_position() -> None:
    raw = "A 10 then 25"
    b = make_block(raw, texts={"pymupdf": raw})
    assert not attested_faithfulness(b, ctx(), [], "A 25 then 10").passed
    # one reader that shows the swap is not enough: each position changes to a new value
    one = {"pymupdf": raw, "docling": "A 25 then 10"}
    assert not numeric_attested(raw, one, "pymupdf", "A 25 then 10", None, True).passed
    two = {**one, "ocr": "A 25 then 10"}
    assert numeric_attested(raw, two, "pymupdf", "A 25 then 10", None, True).passed


# -- item 6: evidence and check-list completeness ----------------------------------------------


def _input(raw: str, readers: dict[str, str], note: str | None = None) -> AgentInput:
    item = AgentItem(
        flag_id="flag-000001",
        category=FlagCategory.wrong_text,
        note=note,
        target_id="b-clean-p001-01",
        doc_id="clean",
        round=1,
        basis_sha256="0" * 64,
    )
    return AgentInput(
        item=item,
        kind=ProposalKind.text,
        bundle={},
        raw_text=raw,
        raw_source="pymupdf",
        readers=readers,
        current=raw,
        candidates=[],
        candidate_text={},
        vision=None,
        max_text=1000,
    )


def test_evidence_quoting_only_the_raw_text_is_not_evidence() -> None:
    raw = "Torque 3S N·m"
    inp = _input(raw, {"pymupdf": raw, "docling": "Torque 35 N·m"}, note="should read 35")
    ev = validate_evidence(
        inp,
        [
            {"source": "pymupdf", "span": "Torque 3S"},
            {"source": "docling", "span": "Torque 35"},
            {"source": "note", "span": "should read 35"},
        ],
    )
    assert [e.verified for e in ev] == [False, True, True]


def _proposal(kind: str, rechecks: list[dict[str, Any]], **payload: Any) -> Proposal:
    return Proposal.model_validate(
        {
            "id": "prop-000001",
            "flag_id": "flag-000001",
            "target_id": "b-clean-p001-01",
            "round": 1,
            "kind": kind,
            **payload,
            "evidence": [{"source": "note", "span": "x", "verified": True}],
            "rationale": "r",
            "rechecks": rechecks,
            "basis_sha256": "0" * 64,
            "model": "mock/mock-1",
            "input_hash": "a" * 64,
            "created_at": "2026-01-01T00:00:00Z",
        }
    )


def test_incomplete_check_list_never_passes() -> None:
    full = [{"check": c, "passed": True} for c in REQUIRED_CHECKS[ProposalKind.text]]
    assert _proposal("text", full, proposal_text="t").all_checks_passed
    assert not _proposal("text", full[:1], proposal_text="t").all_checks_passed
    assert not _proposal("text", [], proposal_text="t").all_checks_passed
    # a cells proposal with the text kind's checks is incomplete too
    cells = _proposal("cells", full, proposal_text="|a|", proposed_cells=[["a"]])
    assert not cells.all_checks_passed
