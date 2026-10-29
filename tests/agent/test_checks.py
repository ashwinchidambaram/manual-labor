"""Design 10 tests 6-10: the rechecks as pure functions."""

from __future__ import annotations

import pytest

from manuallabor.agent.recheck import (
    attested_faithfulness,
    build_table_data,
    cells_text,
    check_evidence,
    check_shape_cells,
    check_table_consistency,
    check_table_coverage,
    numeric_attested,
)
from manuallabor.agent.vision_reader import skip_reason, validate_vread
from manuallabor.contracts.block import TableCell, TableData, VisionReading
from manuallabor.contracts.config import ModelRef, ProjectConfig
from manuallabor.contracts.enums import BlockType, DocKind, EvidenceSource, FlagCategory
from manuallabor.contracts.proposal import EvidenceRef
from manuallabor.parse.tables import table_markdown_from_data
from tests.conftest import ctx, make_block


def N(raw, readers, text, vision=None, spec=True, raw_source="pymupdf"):  # type: ignore[no-untyped-def]
    return numeric_attested(raw, readers, raw_source, text, vision, spec)


def vis(*nums: str) -> VisionReading:
    return VisionReading(outcome="ok", numbers=list(nums), lines=list(nums))


class TestNumberAttestation:
    raw = "Torque 3S N·m"

    def test_look_alike_needs_one_reader(self) -> None:
        r = N(self.raw, {"pymupdf": self.raw, "docling": "Torque 35 N·m"}, "Torque 35 N·m")
        assert r.passed and "docling" in (r.detail or "")

    def test_new_value_needs_two(self) -> None:
        raw = "Torque 36 N·m"
        readers = {"pymupdf": raw, "docling": "Torque 35 N·m"}
        assert not N(raw, readers, "Torque 35 N·m").passed
        assert N(raw, readers, "Torque 35 N·m", vision=vis("35")).passed
        readers2 = {**readers, "ocr": "Torque 35 N·m"}
        assert N(raw, readers2, "Torque 35 N·m").passed

    def test_vision_alone_attests_a_look_alike(self) -> None:
        assert N(self.raw, {"pymupdf": self.raw}, "Torque 35 N·m", vision=vis("35")).passed
        assert not N(self.raw, {"pymupdf": self.raw}, "Torque 35 N·m", vision=vis("36")).passed
        invalid = VisionReading(outcome="invalid", numbers=[])
        assert not N(self.raw, {"pymupdf": self.raw}, "Torque 35 N·m", vision=invalid).passed

    def test_inserted_number_needs_two_exact_sequences(self) -> None:
        raw = "Torque N·m"
        one = {"pymupdf": raw, "docling": "Torque 35 N·m"}
        two = {**one, "ocr": "Torque 35 N·m"}
        assert not N(raw, one, "Torque 35 N·m").passed
        assert N(raw, two, "Torque 35 N·m").passed
        assert N(raw, one, "Torque 35 N·m", spec=False).passed  # one is enough without a spec

    def test_count_mismatch_attests_nothing(self) -> None:
        raw = "A 3S B 7"
        readers = {"pymupdf": raw, "docling": "A 35"}
        assert not N(raw, readers, "A 35 B 7").passed

    def test_unchanged_numbers_pass(self) -> None:
        assert N("A 5 B", {"pymupdf": "A 5 B"}, "A\n5\nB").passed


class TestAttestedFaithfulness:
    def block(self, raw: str, **texts: str):  # type: ignore[no-untyped-def]
        return make_block(raw, texts={"pymupdf": raw, **texts})

    def test_whitespace_only_passes_strict(self) -> None:
        b = self.block("Check the\ndrive belt.", docling="Check the drive belt.")
        r = attested_faithfulness(b, ctx(), [], "Check the drive belt.")
        assert r.passed and "§5.2" in (r.detail or "")

    def test_span_from_two_readers_passes(self) -> None:
        raw = "Torque 3S N·m and wait 4 min"
        b = self.block(
            raw, docling="Torque 35 N·m and wait 4 min", ocr="Torque 35 N·m and wait 4 min"
        )
        r = attested_faithfulness(b, ctx(), [], "Torque 35 N·m and wait 4 min")
        assert r.passed and "strict" in (r.detail or "") or r.detail == "§5.2 normalization only"

    def test_span_from_no_reader_fails(self) -> None:
        raw = "Tighten the bolt firmly"
        b = self.block(raw, docling="Tighten the bolt firmly")
        r = attested_faithfulness(b, ctx(), [], "Tighten the bolt not firmly")
        assert not r.passed and "unattested" in (r.detail or "")

    def test_split_word_from_ocr_passes(self) -> None:
        raw = "Wipe witha clean cloth"
        b = self.block(raw, ocr="Wipe with a clean cloth")
        assert attested_faithfulness(b, ctx(), [], "Wipe with a clean cloth").passed

    def test_no_independent_reader_means_no_attestation(self) -> None:
        b = make_block("Tighten the bolt", texts={"pymupdf": "Tighten the bolt"})
        assert not attested_faithfulness(b, ctx(), [], "Tighten the bolts and nuts").passed


def test_6_table_cells() -> None:
    raw = "Item | Qty\nBolt | 4\nNut | 8"
    cells = [["Item", "Qty"], ["Bolt", "4"], ["Nut", "8"]]
    td = build_table_data(cells, 1)
    assert td.markdown == table_markdown_from_data(td)
    assert td.markdown.splitlines()[1] == "|---|---|"
    assert check_shape_cells(cells).passed
    assert check_table_coverage(raw, cells, {"pymupdf": raw}, "pymupdf").passed
    dropped = cells[:2]
    r = check_table_coverage(raw, dropped, {"pymupdf": raw}, "pymupdf")
    assert not r.passed and "missing" in (r.detail or "")
    assert not check_shape_cells([["a", "b"], ["c"]]).passed
    assert cells_text(cells).splitlines()[1] == "Bolt | 4"
    blk = make_block(raw, type=BlockType.table, source="pymupdf")
    cur = TableData(
        n_rows=3,
        n_cols=2,
        cells=[
            TableCell(row=r_, col=c, text=cells[r_][c], is_header=r_ == 0)
            for r_ in range(3)
            for c in range(2)
        ],
        markdown="x",
    )
    blk = blk.model_copy(update={"table": cur})
    assert check_table_consistency(blk, td).passed


def test_9_vision_reading_validation() -> None:
    lines, nums, problem = validate_vread("35 N·m\nTorque 12 in", 2)
    assert problem is None and nums == ["35", "12"]
    _l, nums, problem = validate_vread("3? N·m\n60", 2)
    assert nums == ["60"]  # a line with an unreadable character yields no number
    garbage = "x" * 60
    assert validate_vread(garbage, 1)[2] == "no usable line"
    assert validate_vread("\n".join(str(i) for i in range(20)), 1)[2] is not None


def test_9_vision_skips() -> None:
    cfg = ProjectConfig(name="p")
    blk = make_block("Torque 35 N·m", has_numeric_spec=True)
    assert skip_reason(blk, DocKind.born_digital_pdf, FlagCategory.wrong_text, cfg) is None
    assert "DOCX" in (skip_reason(blk, DocKind.docx, FlagCategory.wrong_text, cfg) or "")
    assert skip_reason(
        blk.model_copy(update={"has_numeric_spec": False}),
        DocKind.born_digital_pdf,
        FlagCategory.wrong_text,
        cfg,
    )
    assert skip_reason(blk, DocKind.born_digital_pdf, FlagCategory.bad_crop, cfg)
    off = cfg.model_copy(update={"agent": cfg.agent.model_copy(update={"vision_reader": False})})
    assert skip_reason(blk, DocKind.born_digital_pdf, FlagCategory.wrong_text, off)
    assert ModelRef  # the vision model comes from config.model_for(Task.vision)


def test_10_evidence_check() -> None:
    ev = [
        EvidenceRef(source=EvidenceSource.docling, span="a", verified=False),
        EvidenceRef(source=EvidenceSource.ocr, span="b", verified=True),
    ]
    assert check_evidence(ev).passed
    assert not check_evidence([ev[0]]).passed


def test_vision_reading_has_no_confidence_field() -> None:
    assert not [f for f in VisionReading.model_fields if "conf" in f or "score" in f]
    with pytest.raises(ValueError):
        VisionReading.model_validate({"outcome": "ok", "confidence": 0.9})
