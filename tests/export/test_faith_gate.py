"""Design 11 section 20.16 (P3 amended, final review 2026-11-02): a block whose cleaned text
failed the faithfulness check is never covered by an override. It blocks the export until a
person approves it after reading the change, edits it or rejects it; assembly refuses to emit
such a block's cleaned text without a person's decision; the review file records the verdict and
the validator refuses a faith-failed paragraph nobody checked (invariant 1)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from manuallabor.contracts.block import FaithfulnessResult, FaithfulnessViolation
from manuallabor.contracts.enums import BlockStatus, FaithViolationKind
from manuallabor.export.types import ExportError, GateLocked
from manuallabor.export.validate import validate_zip
from manuallabor.export.zip import write_zip
from tests.export.synth import bid, blk, override, run, synth_inputs

ART = "doc--main"
REVP = f"articles/{ART}.review.json"


def failed(raw: str = "35", clean: str = "53") -> FaithfulnessResult:
    return FaithfulnessResult(
        passed=False,
        alignment_ratio=0.5,
        violations=[
            FaithfulnessViolation(
                kind=FaithViolationKind.numeric_mismatch,
                raw_start=0,
                raw_end=2,
                clean_start=0,
                clean_end=2,
                raw=raw,
                clean=clean,
            )
        ],
        diff=[],
    )


def faith_blocks(status: BlockStatus = BlockStatus.queued) -> list[Any]:
    return [
        blk(1, "Ok.", status=BlockStatus.approved),
        blk(
            2,
            "Tighten to 35 N·m.",
            status=status,
            clean="Tighten to 53 N·m. Do not exceed 999 N·m.",
            faithfulness=failed(),
            confidence=0.0,
        ),
        blk(3, "Queued.", status=BlockStatus.queued),
    ]


def test_g1_a_blanket_override_never_covers_a_faith_failed_block() -> None:
    with pytest.raises(GateLocked) as ei:
        run(synth_inputs(faith_blocks(), overrides=[override(5, "ship it")]))
    assert ei.value.blockers == [bid(2)]  # block 3 is covered, block 2 is not
    assert ei.value.faith_failed == [bid(2)]
    assert "cleanup changed" in str(ei.value) and bid(2) in str(ei.value)


def test_g1_a_targeted_override_does_not_cover_it_either() -> None:
    from manuallabor.export.gate import export_gate

    blocks = faith_blocks()
    g = export_gate(
        {"doc": blocks},
        {"doc": {b.id for b in blocks}},
        [],
        [override(5, "x", target=bid(2)), override(6, "y", target=bid(3))],
    )
    assert g.blockers == [bid(2)] and g.faith_blockers == [bid(2)]
    assert bid(2) not in g.covered and bid(3) in g.covered
    assert g.counts["faith_failed"] == 1 and g.counts["to_review"] == 1
    assert g.counts["blocking"] == 1 and g.counts["overridden"] == 1


def test_g1_the_count_is_the_to_review_part_no_override_covers() -> None:
    """Review nit: `counts.faith_failed` counts the faith-failed blocks in `to_review`, so the
    screen's "to review" less it is exactly what a block override may cover; a faith-failed
    block whose `flagged` status remains after its flag was covered sits in `flagged`."""
    from manuallabor.export.gate import export_gate

    blocks = faith_blocks(BlockStatus.flagged)
    g = export_gate(
        {"doc": blocks},
        {"doc": {b.id for b in blocks}},
        [],
        [override(5, "x")],
    )
    assert g.faith_blockers == [bid(2)]
    assert g.counts["flagged"] == 1 and g.counts["faith_failed"] == 0
    assert g.counts["to_review"] == 0 and g.counts["overridden"] == 1


def test_g2_a_person_s_approval_exports_the_text_they_approved_and_records_the_verdict() -> None:
    res = run(synth_inputs(faith_blocks(BlockStatus.approved), overrides=[override(5, "ship it")]))
    (a,) = res.articles
    assert "Tighten to 53 N·m. Do not exceed 999 N·m." in a.text  # what the person approved
    by = {e.block_id: e for e in a.review.blocks}
    assert (by[bid(2)].status, by[bid(2)].faithfulness_passed) == ("approved", False)
    assert by[bid(1)].faithfulness_passed is None  # no check recorded on the synthetic block


def test_g3_assembly_refuses_cleaned_text_that_failed_without_a_person() -> None:
    """Defensive (invariant 1 is a hard stop): even when the gate does not see the block (out
    of scope here), assembly never emits its cleaned text."""
    inp = synth_inputs(faith_blocks(BlockStatus.auto_approved))
    inp.docs["doc"].scope = set()  # the gate sees nothing; assembly still checks every block
    with pytest.raises(ExportError, match=f"{bid(2)}.*faithfulness"):
        run(inp)


def test_g4_the_validator_refuses_a_faith_failed_paragraph_nobody_checked(tmp_path: Path) -> None:
    res = run(synth_inputs(faith_blocks(BlockStatus.approved), overrides=[override(5, "x")]))
    files = {n: v.encode() for n, v in res.files.items() if isinstance(v, str)}
    write_zip(files, tmp_path / "ok.zip")
    assert validate_zip(tmp_path / "ok.zip") == []
    d = json.loads(files[REVP])
    e = d["blocks"][1]
    assert e["faithfulness_passed"] is False
    e.update(status="auto_approved", decided_by="checks", at=None, confidence=0.9)
    d["counts"]["auto_approved"] += 1
    d["counts"]["approved"] -= 1
    files[REVP] = (json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    write_zip(files, tmp_path / "bad.zip")
    msgs = [p.detail for p in validate_zip(tmp_path / "bad.zip") if p.code == "Z9"]
    assert any("faithfulness" in m for m in msgs), msgs


# -- the reviewer's scenario on project-a ----------------------------------------------------


def _mutate_and_rescore(paths: Any) -> tuple[str, str, str]:
    """Change one cleaned text (35 -> 53, M8 -> M10, an invented sentence), keep the clean
    fingerprint, rescore: the block fails the faithfulness check and is queued."""
    from tests.export.helpers import labor_run

    f = paths.doc("clean").clean
    d = json.loads(f.read_text(encoding="utf-8"))
    target = next(e for e in d["blocks"] if e.get("clean_text") and "35" in e["clean_text"])
    target["clean_text"] = (
        target["clean_text"].replace("35", "53").replace("M8", "M10") + " (DO NOT exceed 999 N·m)"
    )
    f.write_text(json.dumps(d, indent=2), encoding="utf-8")
    labor_run(paths.root, "--force", "score2")
    from manuallabor.state.review import load_review_blocks
    from manuallabor.state.store import Store

    store = Store.open(paths)
    try:
        b = next(x for x in load_review_blocks(paths, store, "clean") if x.id == target["block_id"])
    finally:
        store.close()
    assert b.status == BlockStatus.queued and b.faithfulness is not None
    assert b.faithfulness.passed is False
    return str(target["block_id"]), str(target["clean_text"]), b.raw_text


def _article_with(zp: Path, block_id: str) -> tuple[str, dict[str, Any]]:
    with zipfile.ZipFile(zp) as zf:
        m = json.loads(zf.read("manifest.json"))
        art = next(a for a in m["articles"] if block_id in a["block_ids"])
        rv = json.loads(zf.read(art["review_sidecar"]))
        return zf.read(art["path"]).decode(), next(
            e for e in rv["blocks"] if e["block_id"] == block_id
        )


def test_g5_the_reviewer_s_scenario_is_refused_until_a_person_decides(work: Any) -> None:
    from manuallabor.export.pipeline import (
        export_status,
        record_override,
        resolve_clock,
        run_export,
    )
    from manuallabor.state.errors import InvalidOp
    from manuallabor.state.models import ReviewActionIn
    from manuallabor.state.store import Store
    from tests.export.helpers import CLOCK, reviewer
    from tests.export.test_api import Env
    from tests.export.test_pipeline import labor

    tid, mutated, raw = _mutate_and_rescore(work)
    # the service refuses a block override, naming the reason
    store = Store.open(work)
    try:
        with pytest.raises(InvalidOp, match="faithfulness"):
            record_override(work, store, "ship it", target_id=tid)
        st = export_status(work, store)
        assert st.faith_blockers == [tid] and tid in st.blockers
        assert st.counts is not None and st.counts.faith_failed == 1
    finally:
        store.close()
    # the route answers 422 with the reason; the export route is locked and says why
    env = Env(work)
    try:
        r = env.client.post("/api/export/override", json={"reason": "ship it", "target_id": tid})
        assert r.status_code == 422 and "faithfulness" in r.json()["detail"]
        locked = env.client.post("/api/export")
        assert locked.status_code == 409 and locked.json()["faith_blockers"] == [tid]
    finally:
        env.close()
    # the CLI's blanket override records, but the export stays locked by the faith blocker
    out = labor("export", str(work.root), "--override", "reviewer: ship it", "--now", CLOCK)
    assert out.returncode == 2, out.stdout + out.stderr
    assert tid in out.stderr and "cleanup changed" in out.stderr
    assert not work.zip_path.exists()
    # a person approves it after reading the change: the text they approved goes out
    store = Store.open(work)
    try:
        reviewer(work, store).act(ReviewActionIn(kind="approve", block_id=tid, request_id="g5-a"))
        rec = run_export(work, store, clock=resolve_clock(CLOCK), emit=lambda _o: None)
        text, entry = _article_with(Path(rec.zip_path), tid)
        assert mutated in text and entry["status"] == "approved"
        assert entry["faithfulness_passed"] is False
        assert validate_zip(Path(rec.zip_path)) == []
        # a person edits it back to the source text instead: the edit goes out, not the change
        reviewer(work, store).act(
            ReviewActionIn(kind="edit", block_id=tid, text=raw, request_id="g5-e")
        )
        rec2 = run_export(work, store, clock=resolve_clock(CLOCK), emit=lambda _o: None)
        text2, entry2 = _article_with(Path(rec2.zip_path), tid)
        assert raw in text2 and "999" not in text2
        assert entry2["status"] == "edited" and entry2["original_text"] == raw
        assert validate_zip(Path(rec2.zip_path)) == []
    finally:
        store.close()
