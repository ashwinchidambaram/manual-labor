"""Design 11 sections 20.12 to 20.15 (Dana's fourth report, "What I'd change next"): the original
text of edited paragraphs, a marker on every figure line, reason references, and visible review
marks as an export option.

F1 to F4 run on hand-built inputs (no parser); F4f uses project-a. Expectations are re-derived
here with test-local regexes; the code under test is used only to produce the export, plus
`strip_visible_marks`, the helper the design names for the faithfulness comparisons."""

from __future__ import annotations

import hashlib
import html as htmlmod
import json
import re
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from manuallabor.contracts.article import ArticleReview
from manuallabor.contracts.enums import AttachRule, BlockStatus, BlockType
from manuallabor.export.markers import strip_visible_marks
from manuallabor.export.types import ExportError, HumanDecision, Problem
from manuallabor.export.validate import validate_zip
from manuallabor.export.zip import write_zip
from tests.export.synth import (
    CLOCK,
    att,
    bid,
    blk,
    fid,
    figure_data,
    flag,
    override,
    run,
    synth_inputs,
)

ART = "doc--main"
ARTP = f"articles/{ART}.md"
REVP = f"articles/{ART}.review.json"
LONG = (
    "Checked against the paper manual, revision B, page 42; the torque table there matches "
    "the scan line for line -- rev B > rev A"
)
# the grammar of design 11 sections 20.2, 20.13 and 20.14, written out again (not imported)
MARKER_RE = re.compile(
    r"^<!-- ml: (?P<status>approved|edited|auto-approved|overridden); "
    r"block: (?P<block>b-[a-z0-9-]+-p\d{3,}-\d{2,}|FIG-[a-z0-9-]+-p\d{3,4}-\d{2,3})"
    r"(?:; flag: (?P<flag>flag-\d{6}))?(?:; reason: (?P<reason>r[1-9]\d*))? -->$"
)
FIG_LINE_RE = re.compile(r"^!\[(?P<fid>FIG-[a-z0-9-]+-p\d{3,4}-\d{2,3}) — .*\]\(images/.*\.png\)$")
TAG = {"auto-approved": "[unchecked]", "overridden": "[overridden]"}

Files = dict[str, bytes]


def body_of(text: str) -> str:
    return text[text.index("\n---\n", 3) + 5 :]


def lines_of(text: str) -> list[str]:
    return body_of(text).split("\n")


def markers(text: str) -> list[re.Match[str]]:
    out = []
    for ln in lines_of(text):
        if ln.startswith("<!--"):
            m = MARKER_RE.match(ln)
            assert m is not None, f"malformed marker {ln!r}"
            out.append(m)
    return out


def visible(md_text: str) -> str:
    from markdown_it import MarkdownIt

    out = MarkdownIt("commonmark").enable(["table", "strikethrough"]).render(md_text)
    out = re.sub(r"<!--.*?-->", " ", out, flags=re.S)
    out = re.sub(r"<[^>]+>", " ", out)
    return " ".join(htmlmod.unescape(out).split())


def text_files(res: Any) -> Files:
    """Every file of the export as bytes; synthetic figures have no image (an empty file, which
    Z4 reports and these tests ignore by reading Z9 only)."""
    return {n: v.encode("utf-8") if isinstance(v, str) else b"" for n, v in res.files.items()}


def zip_problems(files: Files, tmp: Path, name: str = "f.zip") -> list[Problem]:
    write_zip(files, tmp / name)
    return validate_zip(tmp / name)


def z9(problems: list[Problem]) -> list[str]:
    return [f"{p.where}: {p.detail}" for p in problems if p.code == "Z9"]


def edit_review(files: Files, fn: Callable[[dict[str, Any]], None]) -> None:
    d = json.loads(files[REVP])
    fn(d)
    files[REVP] = (json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def edit_article(files: Files, fn: Callable[[str], str]) -> None:
    new = fn(files[ARTP].decode())
    assert new != files[ARTP].decode(), "the edit changed nothing"
    files[ARTP] = new.encode()


# -- F1 the original text of an edited paragraph (20.12) ----------------------------------------

RAW = (
    "Check the deflec-\ntion at the midpoint with a spring scale: 10 mm at 50 N is right for "
    "the X200 belt."
)
EARLIER = datetime(2026, 10, 29, 11, 0, 0, tzinfo=UTC)


def edited_inputs(**kw: Any) -> Any:
    blocks = [
        blk(1, RAW, status=BlockStatus.edited, clean="Check the deflection at the midpoint."),
        blk(2, "Approved.", status=BlockStatus.approved),
        blk(3, "Auto.", status=BlockStatus.auto_approved),
    ]
    return synth_inputs(blocks, **kw)


def test_f1a_an_edited_entry_carries_the_full_original_text_and_when_it_was_edited() -> None:
    decisions = {
        bid(1): HumanDecision(
            at=CLOCK, edited_by="agent_proposal", edited_at=EARLIER, original_text=RAW
        ),
        bid(2): HumanDecision(at=CLOCK, edited_by=None),
    }
    (a,) = run(edited_inputs(decisions=decisions)).articles
    by = {e.block_id: e.model_dump(mode="json") for e in a.review.blocks}
    assert len(RAW) > 80
    assert by[bid(1)]["original_text"] == RAW  # full, not the 80-character `text`
    assert by[bid(1)]["edited_at"] == "2026-10-29T11:00:00Z"
    assert by[bid(1)]["at"] == "2026-10-29T12:00:00Z"  # a later approval of the edited text
    assert by[bid(1)]["edited_by"] == "agent_proposal"
    for n in (2, 3):
        assert by[bid(n)]["original_text"] is None and by[bid(n)]["edited_at"] is None
    # the article holds the edited text; the original is only in the review file
    assert "deflec-" not in a.text and "Check the deflection at the midpoint." in a.text
    raw_json = json.loads(str(run(edited_inputs(decisions=decisions)).files[REVP]))
    assert raw_json["blocks"][0]["original_text"] == RAW


def test_f1b_human_decisions_take_the_original_from_the_block_the_edit_was_made_on() -> None:
    from manuallabor.contracts.decision import Decision
    from manuallabor.contracts.enums import DecisionAction
    from manuallabor.export.load import human_decisions
    from manuallabor.state.models import DecisionRecord
    from manuallabor.state.review import derive
    from manuallabor.state.store import sha_text

    b = blk(1, RAW, status=BlockStatus.queued)

    def rec(seq: int, action: DecisionAction, ts: datetime, raw_sha: str, **kw: Any) -> Any:
        return DecisionRecord(
            decision=Decision(
                seq=seq,
                block_id=b.id,
                action=action,
                score=0.5,
                threshold=0.85,
                signals=[],
                timestamp=ts,
                **kw,
            ),
            action_id=seq,
            doc_id="doc",
            raw_sha256=raw_sha,
            shown_text_sha256=sha_text("Check the deflection."),
        )

    good = sha_text(RAW)
    edit = rec(1, DecisionAction.edit, EARLIER, good, edited_text="Check the deflection.")
    approve = rec(2, DecisionAction.approve, CLOCK, good)
    r = derive(b, [edit, approve], {})
    assert r.status == BlockStatus.edited
    from manuallabor.state.review import overlay_block

    out = human_decisions([(overlay_block(b, r), r)])
    d = out[b.id]
    assert (d.original_text, d.edited_at, d.at) == (RAW, EARLIER, CLOCK)
    # an edit made on other raw text is no proof: the export refuses rather than guess
    forged = rec(1, DecisionAction.edit, EARLIER, "0" * 64, edited_text="x")
    r2 = derive(b, [edit], {})
    r2 = type(r2)(r2.status, r2.stale_reason, forged, forged, 0, False, forged)
    with pytest.raises(ExportError, match=b.id):
        human_decisions([(overlay_block(b, derive(b, [edit], {})), r2)])


def test_f1c_original_text_on_the_wrong_entry_fails_z9(tmp_path: Path) -> None:
    files = text_files(run(edited_inputs()))
    assert z9(zip_problems(files, tmp_path, "ok.zip")) == []

    def put(d: dict[str, Any]) -> None:
        d["blocks"][1]["original_text"] = "Approved."

    edit_review(files, put)
    msgs = z9(zip_problems(files, tmp_path))
    assert any("original_text" in m for m in msgs), msgs

    files = text_files(run(edited_inputs()))
    edit_review(files, lambda d: d["blocks"][0].update(original_text=None))
    msgs = z9(zip_problems(files, tmp_path, "g.zip"))
    assert any("original_text" in m for m in msgs), msgs


# -- F2 a marker on every figure line (20.13) ----------------------------------------------------


def figure_inputs(**kw: Any) -> Any:
    """Figures decided every way: 2 attached by the checks, 3 approved by a person in Verify
    (attached by a caption reference), 4 attached by a person, 5 exported under an override."""
    blocks = [
        blk(1, "See Figure 1.", status=BlockStatus.approved),
        blk(2, type=BlockType.figure, status=BlockStatus.auto_approved),
        blk(3, type=BlockType.figure, status=BlockStatus.approved),
        blk(4, type=BlockType.figure, status=BlockStatus.auto_approved),
        blk(5, type=BlockType.figure, status=BlockStatus.queued),
        blk(6, "Last paragraph.", status=BlockStatus.auto_approved),
    ]
    return synth_inputs(
        blocks,
        figures=[figure_data(n) for n in (2, 3, 4, 5)],
        attach={
            ART: [
                att(fid(2)),
                att(fid(3), rule=AttachRule.caption_ref, anchor=bid(1)),
                att(fid(4), rule=AttachRule.human, anchor=bid(6)),
                att(fid(5)),
            ]
        },
        overrides=[override(7, LONG)],
        **kw,
    )


def test_f2a_every_figure_line_has_its_marker_directly_above_it() -> None:
    (a,) = run(figure_inputs()).articles
    lines = lines_of(a.text)
    seen: dict[str, re.Match[str]] = {}
    for i, ln in enumerate(lines):
        fm = FIG_LINE_RE.match(ln)
        if fm is None:
            continue
        assert lines[i - 2] == "", ln  # the marker starts the unit, after a blank line
        mk = MARKER_RE.match(lines[i - 1])
        assert mk is not None, f"no marker above {ln!r}"
        assert mk.group("block") == fm.group("fid")
        seen[fm.group("fid")] = mk
    assert set(seen) == {fid(n) for n in (2, 3, 4, 5)}
    assert seen[fid(2)].group("status") == "auto-approved"  # the checks attached it
    assert seen[fid(3)].group("status") == "approved"  # a person approved the figure block
    assert seen[fid(4)].group("status") == "approved"  # a person attached it
    assert seen[fid(5)].group("status") == "overridden"
    assert seen[fid(5)].group("reason") == "r1" and seen[fid(5)].group("flag") is None
    for f in (2, 3, 4):
        assert seen[fid(f)].group("reason") is None and seen[fid(f)].group("flag") is None
    # every figure line and every paragraph is marked: no line of the body is left bare
    n_marked = len(markers(a.text))
    assert n_marked == 2 + 4 and len(a.review.figure_lines) == 4


def test_f2b_the_review_file_lists_the_figure_lines_in_body_order() -> None:
    (a,) = run(figure_inputs()).articles
    order = [m.group("fid") for ln in lines_of(a.text) if (m := FIG_LINE_RE.match(ln))]
    rows = [fl.model_dump(mode="json") for fl in a.review.figure_lines]
    assert [r["figure_id"] for r in rows] == order
    by = {r["figure_id"]: r for r in rows}
    assert by[fid(2)] == {
        "figure_id": fid(2),
        "block_id": bid(2),
        "rule": "proximity",
        "status": "auto_approved",
        "decided_by": "checks",
        "reason": None,
        "reason_id": None,
        "flag_id": None,
    }
    assert (by[fid(3)]["status"], by[fid(3)]["decided_by"], by[fid(3)]["rule"]) == (
        "approved",
        "person",
        "caption_ref",
    )
    assert (by[fid(4)]["status"], by[fid(4)]["rule"]) == ("approved", "human")
    assert (by[fid(5)]["status"], by[fid(5)]["decided_by"]) == ("overridden", "override")
    assert (by[fid(5)]["reason"], by[fid(5)]["reason_id"]) == (LONG, "r1")
    # the block categories do not change: figure blocks still count as blocks
    assert a.frontmatter.blocks == 6
    assert {e.placement for e in a.review.blocks if e.type == BlockType.figure} == {"figure"}


def test_f2b_the_figure_line_of_an_overridden_flagged_figure_carries_the_flag() -> None:
    blocks = [
        blk(1, "Text.", status=BlockStatus.approved),
        blk(2, type=BlockType.figure, status=BlockStatus.approved),
    ]
    res = run(
        synth_inputs(
            blocks,
            figures=[figure_data(2)],
            attach={ART: [att(fid(2))]},
            flags=[flag(3, bid(2))],
            overrides=[override(4, "figure ok", flag_id="flag-000003")],
        )
    )
    (a,) = res.articles
    (fl,) = a.review.figure_lines
    assert (fl.status, fl.flag_id, fl.reason_id) == ("overridden", "flag-000003", "r1")
    mk = next(m for m in markers(a.text) if m.group("block") == fid(2))
    assert mk.group(0) == f"<!-- ml: overridden; block: {fid(2)}; flag: flag-000003; reason: r1 -->"


def test_f2c_the_synthetic_figure_export_passes_z9(tmp_path: Path) -> None:
    assert z9(zip_problems(text_files(run(figure_inputs())), tmp_path)) == []


def test_f2c_a_bare_figure_line_fails(tmp_path: Path) -> None:
    files = text_files(run(figure_inputs()))
    mk = f"<!-- ml: auto-approved; block: {fid(2)} -->\n"
    edit_article(files, lambda t: t.replace(mk, "", 1))
    msgs = z9(zip_problems(files, tmp_path))
    assert any(fid(2) in m and "no marker" in m for m in msgs), msgs


def test_f2c_a_figure_marker_naming_another_figure_fails(tmp_path: Path) -> None:
    files = text_files(run(figure_inputs()))
    edit_article(
        files,
        lambda t: t.replace(
            f"<!-- ml: auto-approved; block: {fid(2)} -->",
            f"<!-- ml: auto-approved; block: {fid(9)} -->",
            1,
        ),
    )
    msgs = z9(zip_problems(files, tmp_path))
    assert any(fid(2) in m for m in msgs) and any(fid(9) in m for m in msgs), msgs


def test_f2c_a_tampered_figure_line_status_fails(tmp_path: Path) -> None:
    files = text_files(run(figure_inputs()))
    edit_article(
        files,
        lambda t: t.replace(
            f"<!-- ml: auto-approved; block: {fid(2)} -->",
            f"<!-- ml: approved; block: {fid(2)} -->",
            1,
        ),
    )
    msgs = z9(zip_problems(files, tmp_path))
    assert any(fid(2) in m and "approved" in m for m in msgs), msgs


def test_f2c_a_figure_line_missing_from_the_review_file_fails(tmp_path: Path) -> None:
    files = text_files(run(figure_inputs()))

    def drop(d: dict[str, Any]) -> None:
        d["figure_lines"] = [x for x in d["figure_lines"] if x["figure_id"] != fid(4)]

    edit_review(files, drop)
    msgs = z9(zip_problems(files, tmp_path))
    assert any(fid(4) in m for m in msgs), msgs


def test_f2c_a_figure_line_whose_status_disagrees_with_its_block_fails(tmp_path: Path) -> None:
    """The review file's figure line and marker both say approved, but the figure block says
    the checks decided and the checks attached it: the cross-check catches it."""
    files = text_files(run(figure_inputs()))
    edit_article(
        files,
        lambda t: t.replace(
            f"<!-- ml: auto-approved; block: {fid(2)} -->",
            f"<!-- ml: approved; block: {fid(2)} -->",
            1,
        ),
    )

    def t(d: dict[str, Any]) -> None:
        for x in d["figure_lines"]:
            if x["figure_id"] == fid(2):
                x.update(status="approved", decided_by="person")

    edit_review(files, t)
    msgs = z9(zip_problems(files, tmp_path))
    assert any(fid(2) in m and "auto_approved" in m for m in msgs), msgs


def test_f2d_the_readme_reconciles_blocks_paragraphs_and_figure_lines() -> None:
    res = run(figure_inputs())
    # 6 blocks = 2 paragraphs (1 auto-approved, 1 approved) + 4 figure blocks (2 auto-approved,
    # 1 approved, 1 overridden); 4 figure lines (1 auto-approved, 2 approved, 1 overridden)
    assert (
        "In this export: 6 blocks = 2 paragraphs (1 auto-approved, 1 approved, 0 edited, "
        "0 overridden) + 4 figure blocks (2 auto-approved, 1 approved, 0 edited, 1 overridden). "
        "Every paragraph has a marker, and so does every figure line: 4 figure lines "
        "(1 auto-approved, 2 approved, 1 overridden); a figure line's status is its placement's"
        in res.readme
    )


# -- F3 reason references (20.14) ----------------------------------------------------------------


def reason_inputs(**kw: Any) -> Any:
    blocks = [
        blk(1, "Queued one.", status=BlockStatus.queued),
        blk(2, "Approved.", status=BlockStatus.approved),
        blk(3, "Flagged.", status=BlockStatus.flagged),
        blk(4, "Queued two.", status=BlockStatus.queued),
    ]
    return synth_inputs(
        blocks,
        flags=[flag(1, bid(3))],
        overrides=[override(5, LONG), override(6, "flag looked at", flag_id="flag-000001")],
        **kw,
    )


def test_f3a_one_reason_is_one_short_reference_and_never_in_the_article() -> None:
    res = run(reason_inputs())
    (a,) = res.articles
    got = [(m.group("block"), m.group("reason"), m.group("flag")) for m in markers(a.text)]
    assert got == [
        (bid(1), "r1", None),
        (bid(2), None, None),
        (bid(3), "r2", "flag-000001"),
        (bid(4), "r1", None),
    ]
    assert LONG not in a.text and "flag looked at" not in a.text and "rev B" not in a.text
    rv = json.loads(str(res.files[REVP]))
    assert rv["reasons"] == [{"id": "r1", "reason": LONG}, {"id": "r2", "reason": "flag looked at"}]
    by = {e["block_id"]: e for e in rv["blocks"]}
    assert (by[bid(1)]["reason_id"], by[bid(1)]["reason"]) == ("r1", LONG)
    assert (by[bid(3)]["reason_id"], by[bid(3)]["reason"]) == ("r2", "flag looked at")
    assert by[bid(2)]["reason_id"] is None
    # the manifest keeps the full reason per block, as before
    assert [(o.target_id, o.reason) for o in res.manifest.overrides] == [
        (bid(1), LONG),
        (bid(3), "flag looked at"),
        (bid(4), LONG),
    ]


def test_f3b_ids_follow_first_use_in_the_body_figure_lines_included() -> None:
    """The overridden figure line (anchored on block 1) comes before the flagged paragraph."""
    blocks = [
        blk(1, "See Figure 1.", status=BlockStatus.approved),
        blk(2, type=BlockType.figure, status=BlockStatus.queued),
        blk(3, "Flagged.", status=BlockStatus.flagged),
    ]
    inp = synth_inputs(
        blocks,
        figures=[figure_data(2)],
        attach={ART: [att(fid(2), rule=AttachRule.caption_ref, anchor=bid(1))]},
        flags=[flag(1, bid(3))],
        overrides=[
            override(5, "figure reason", target=bid(2)),
            override(6, "flag reason", flag_id="flag-000001"),
        ],
    )
    res = run(inp)
    (a,) = res.articles
    got = [(m.group("block"), m.group("reason")) for m in markers(a.text)]
    assert got == [(bid(1), None), (fid(2), "r1"), (bid(3), "r2")]
    assert [(r.id, r.reason) for r in a.review.reasons] == [
        ("r1", "figure reason"),
        ("r2", "flag reason"),
    ]
    assert run(inp).files == res.files  # deterministic


def test_f3c_the_synthetic_reason_export_validates(tmp_path: Path) -> None:
    assert zip_problems(text_files(run(reason_inputs())), tmp_path) == []


def test_f3c_a_marker_naming_an_unknown_reason_fails(tmp_path: Path) -> None:
    files = text_files(run(reason_inputs()))
    edit_article(
        files, lambda t: t.replace(f"block: {bid(4)}; reason: r1", f"block: {bid(4)}; reason: r9")
    )
    msgs = z9(zip_problems(files, tmp_path))
    assert any(bid(4) in m and "r9" in m for m in msgs), msgs


def test_f3c_swapped_reason_references_fail(tmp_path: Path) -> None:
    files = text_files(run(reason_inputs()))

    def t(text: str) -> str:
        return text.replace(f"block: {bid(1)}; reason: r1", f"block: {bid(1)}; reason: r2").replace(
            "flag: flag-000001; reason: r2", "flag: flag-000001; reason: r1"
        )

    edit_article(files, t)
    msgs = z9(zip_problems(files, tmp_path))
    assert any(bid(1) in m and "reason" in m for m in msgs), msgs
    assert any("first use" in m for m in msgs), msgs


def test_f3c_an_unused_or_reordered_reason_row_fails(tmp_path: Path) -> None:
    files = text_files(run(reason_inputs()))
    edit_review(files, lambda d: d["reasons"].append({"id": "r3", "reason": "spare"}))
    msgs = z9(zip_problems(files, tmp_path))
    assert any("r3" in m for m in msgs), msgs


def test_f3c_a_table_reason_that_differs_from_the_manifest_fails(tmp_path: Path) -> None:
    files = text_files(run(reason_inputs()))

    def t(d: dict[str, Any]) -> None:
        d["reasons"][0]["reason"] = "another reason"
        for e in d["blocks"]:
            if e["reason_id"] == "r1":
                e["reason"] = "another reason"

    edit_review(files, t)
    msgs = z9(zip_problems(files, tmp_path))
    assert any(bid(1) in m and "manifest.overrides" in m for m in msgs), msgs


# -- F4 visible review marks (20.15) -------------------------------------------------------------


def every_status(**kw: Any) -> Any:
    blocks = [
        blk(1, "1 Intro", type=BlockType.heading, status=BlockStatus.auto_approved),
        blk(2, "Approved text.", status=BlockStatus.approved),
        blk(
            3,
            "| a | b |\n| --- | --- |\n| 1 | 2 |",
            type=BlockType.table,
            status=BlockStatus.auto_approved,
        ),
        blk(4, "raw list", type=BlockType.list, status=BlockStatus.edited, clean="• one\n• two"),
        blk(5, "Queued text.", status=BlockStatus.queued),
        blk(6, "Flagged text.", status=BlockStatus.flagged),
        blk(7, type=BlockType.figure, status=BlockStatus.auto_approved),
        blk(8, "2. second step", type=BlockType.list, status=BlockStatus.auto_approved),
        blk(9, "    indented code", status=BlockStatus.auto_approved),
    ]
    return synth_inputs(
        blocks,
        levels={bid(1): 1},
        sections={bid(1): "1"},
        figures=[figure_data(7)],
        attach={ART: [att(fid(7))]},
        flags=[flag(1, bid(6))],
        overrides=[override(5, LONG)],
        **kw,
    )


def tag_before(text: str) -> dict[str, str]:
    """Marker id -> the tag on the line two above it (after a blank line), when there is one."""
    lines = lines_of(text)
    out = {}
    for i, ln in enumerate(lines):
        m = MARKER_RE.match(ln)
        if m and i >= 2 and lines[i - 1] == "" and lines[i - 2] in ("[unchecked]", "[overridden]"):
            out[m.group("block")] = lines[i - 2]
    return out


def test_f4a_visible_marks_add_one_tag_above_each_unchecked_paragraph_and_nothing_else() -> None:
    inv = run(every_status()).articles[0].text
    vis = run(every_status(marks="visible")).articles[0].text
    assert tag_before(inv) == {}
    want = {
        m.group("block"): TAG[m.group("status")]
        for m in markers(vis)
        if m.group("status") in TAG and m.group("block").startswith("b-")
    }
    assert want == {
        bid(1): "[unchecked]",
        bid(3): "[unchecked]",
        bid(5): "[overridden]",
        bid(6): "[overridden]",
        bid(8): "[unchecked]",
        bid(9): "[unchecked]",
    }
    assert tag_before(vis) == want  # none above approved, edited or figure-line markers
    # the invisible article plus exactly those tag paragraphs, byte for byte
    rebuilt = inv
    for m in markers(inv):
        tag = want.get(m.group("block"))
        if tag is not None:
            rebuilt = rebuilt.replace(
                "\n\n" + m.group(0) + "\n", "\n\n" + tag + "\n\n" + m.group(0) + "\n", 1
            )
    assert vis == rebuilt
    # strip_visible_marks gives the invisible bytes back; it leaves an invisible export alone
    assert strip_visible_marks(vis, "visible") == inv
    assert strip_visible_marks(inv, "invisible") == inv
    # a rendered reader sees the tags; without them the text is the invisible article's
    assert visible(body_of(vis)).count("[unchecked]") == 4
    assert visible(body_of(vis)).count("[overridden]") == 2
    assert visible(body_of(strip_visible_marks(vis, "visible"))) == visible(body_of(inv))
    # the tags never change the structure of the paragraph below: heading, table, ordered list
    from markdown_it import MarkdownIt

    md = MarkdownIt("commonmark").enable(["table"])
    assert md.render(body_of(vis)).count("<h2>") == md.render(body_of(inv)).count("<h2>") == 1
    assert md.render(body_of(vis)).count("<table>") == 1
    assert md.render(body_of(vis)).count("<ol") == md.render(body_of(inv)).count("<ol")
    assert md.render(body_of(vis)).count("<pre>") == md.render(body_of(inv)).count("<pre>") == 1


def test_f4b_the_manifest_records_the_mode_and_the_review_files_do_not_change() -> None:
    inv, vis = run(every_status()), run(every_status(marks="visible"))
    assert inv.manifest.marks == "invisible" and vis.manifest.marks == "visible"
    assert json.loads(str(inv.files["manifest.json"]))["marks"] == "invisible"
    assert inv.files[REVP] == vis.files[REVP]  # text_sha256 and text hash the part, not the tag
    assert "This export was made with visible review marks" in vis.readme
    assert "This export was made with visible review marks" not in inv.readme
    assert "`marks: invisible`" in inv.readme


def test_f4c_a_visible_export_validates(tmp_path: Path) -> None:
    assert z9(zip_problems(text_files(run(every_status(marks="visible"))), tmp_path)) == []


@pytest.mark.parametrize(
    "case",
    ["missing", "before-approved", "before-figure", "wrong-word"],
)
def test_f4c_a_tag_out_of_place_fails(case: str, tmp_path: Path) -> None:
    files = text_files(run(every_status(marks="visible")))
    m3 = f"<!-- ml: auto-approved; block: {bid(3)} -->"
    m2 = f"<!-- ml: approved; block: {bid(2)} -->"
    mf = f"<!-- ml: auto-approved; block: {fid(7)} -->"
    m5 = f"<!-- ml: overridden; block: {bid(5)}; reason: r1 -->"
    edits = {
        "missing": (f"[unchecked]\n\n{m3}", m3, bid(3)),
        "before-approved": (m2, f"[unchecked]\n\n{m2}", bid(2)),
        "before-figure": (mf, f"[unchecked]\n\n{mf}", fid(7)),
        "wrong-word": (f"[overridden]\n\n{m5}", f"[unchecked]\n\n{m5}", bid(5)),
    }
    old, new, who = edits[case]
    edit_article(files, lambda t: t.replace(old, new, 1))
    msgs = z9(zip_problems(files, tmp_path))
    assert any(who in m and "tag" in m for m in msgs), (case, msgs)


def test_f4c_a_tag_in_an_invisible_export_fails(tmp_path: Path) -> None:
    files = text_files(run(every_status()))
    m3 = f"<!-- ml: auto-approved; block: {bid(3)} -->"
    edit_article(files, lambda t: t.replace(m3, f"[unchecked]\n\n{m3}", 1))
    msgs = z9(zip_problems(files, tmp_path))
    assert any(bid(3) in m and "tag" in m and "invisible" in m for m in msgs), msgs


def test_f4c_flipping_the_manifest_mode_fails(tmp_path: Path) -> None:
    files = text_files(run(every_status(marks="visible")))
    m = json.loads(files["manifest.json"])
    m["marks"] = "invisible"
    files["manifest.json"] = (json.dumps(m, sort_keys=True, indent=2) + "\n").encode()
    assert z9(zip_problems(files, tmp_path))


def test_f4d_a_link_definition_for_a_tag_label_is_refused_in_visible_mode_only() -> None:
    blocks = [
        blk(1, "[unchecked]: https://example.com", status=BlockStatus.approved),
        blk(2, "Auto.", status=BlockStatus.auto_approved),
    ]
    assert run(synth_inputs(blocks)).articles  # invisible: nothing to protect
    with pytest.raises(ExportError, match=bid(1)):
        run(synth_inputs(blocks, marks="visible"))


@pytest.mark.parametrize("marks", ["invisible", "visible"])
def test_f4e_a_source_line_that_reads_like_a_tag_is_left_alone(marks: str, tmp_path: Path) -> None:
    blocks = [
        blk(1, "Note\n\n[unchecked]", status=BlockStatus.approved),
        blk(2, "Auto.", status=BlockStatus.auto_approved),
        blk(3, "[overridden]", status=BlockStatus.approved),
        blk(4, "Queued.", status=BlockStatus.queued),
    ]
    res = run(synth_inputs(blocks, overrides=[override(5, "ok")], marks=marks))
    (a,) = res.articles
    inv = run(synth_inputs(blocks, overrides=[override(5, "ok")])).articles[0].text
    assert strip_visible_marks(a.text, marks) == inv
    assert "Note\n\n[unchecked]\n\n" in inv
    assert z9(zip_problems(text_files(res), tmp_path)) == []


# -- F4f the option through the pipeline, the CLI and the API -----------------------------------


def _read_all(zp: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(zp) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def test_f4f_visible_marks_through_the_pipeline_rebuild_and_strip_back(work: Any) -> None:
    from manuallabor.contracts.manifest import Manifest
    from manuallabor.export.pipeline import read_state, resolve_clock, run_export
    from manuallabor.state.store import Store
    from tests.export.helpers import CLOCK as HCLOCK

    store = Store.open(work)
    try:
        r1 = run_export(work, store, clock=resolve_clock(HCLOCK), emit=lambda _o: None)
        inv = _read_all(Path(r1.zip_path))
        events: list[dict[str, Any]] = []
        r2 = run_export(
            work, store, clock=resolve_clock(HCLOCK), emit=events.append, marks="visible"
        )
        vis = _read_all(Path(r2.zip_path))
    finally:
        store.close()
    assert ("assemble", "built") in [(e.get("stage"), e.get("status")) for e in events]
    assert r1.summary.marks == "invisible" and r2.summary.marks == "visible"
    st = read_state(work)
    assert st.export is not None and st.export.summary.marks == "visible"
    assert validate_zip(Path(r2.zip_path)) == []
    m = Manifest.model_validate_json(vis["manifest.json"])
    assert m.marks == "visible"
    n_tags = 0
    for a in m.articles:
        v, i = vis[a.path].decode(), inv[a.path].decode()
        assert strip_visible_marks(v, "visible") == i, a.id
        n_tags += v.count("\n[unchecked]\n")
        assert vis[a.review_sidecar] == inv[a.review_sidecar]
    assert n_tags > 0  # project-a has auto-approved paragraphs


def test_f4f_the_export_route_takes_the_mode_and_queues_one_job_per_mode(unreviewed: Any) -> None:
    import os

    from manuallabor.jobs.worker import run_job
    from tests.export.test_api import NOW, Env, approve_everything

    env = Env(unreviewed)
    try:
        c = env.client
        approve_everything(env)
        j1 = c.post("/api/export", json={"request_id": "e-1", "marks": "visible"}).json()
        assert j1["kind"] == "export" and j1["plan"]["marks"] == "visible"
        same = c.post("/api/export", json={"request_id": "e-2", "marks": "visible"}).json()
        assert same["id"] == j1["id"]
        other = c.post("/api/export", json={"request_id": "e-3"}).json()
        assert other["id"] != j1["id"] and other["plan"]["marks"] == "invisible"
        assert c.post("/api/export", json={"marks": "loud"}).status_code == 422
        os.environ["MANUALLABOR_NOW"] = NOW
        try:
            assert run_job(env.paths.root, j1["id"]) == 0
        finally:
            del os.environ["MANUALLABOR_NOW"]
        from manuallabor.export.pipeline import read_state

        st = read_state(env.paths)
        assert st.export is not None and st.export.summary.marks == "visible"
        with zipfile.ZipFile(st.export.zip_path) as zf:
            assert json.loads(zf.read("manifest.json"))["marks"] == "visible"
    finally:
        env.close()


def test_f4f_labor_export_marks_visible(work: Any) -> None:
    from tests.export.test_pipeline import labor

    r = labor(
        "export", str(work.root), "--marks", "visible", "--json", "--now", "2026-10-29T12:00:00Z"
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["marks"] == "visible"
    with zipfile.ZipFile(work.zip_path) as zf:
        assert json.loads(zf.read("manifest.json"))["marks"] == "visible"
    assert labor("export", str(work.root), "--marks", "loud").returncode != 0


def test_f4f_an_unchanged_mode_still_skips(work: Any) -> None:
    from manuallabor.export.pipeline import resolve_clock, run_export
    from manuallabor.state.store import Store
    from tests.export.helpers import CLOCK as HCLOCK

    store = Store.open(work)
    try:
        run_export(work, store, clock=resolve_clock(HCLOCK), emit=lambda _o: None, marks="visible")
        ev: list[dict[str, Any]] = []
        run_export(work, store, clock=resolve_clock(HCLOCK), emit=ev.append, marks="visible")
    finally:
        store.close()
    assert ("assemble", "skip") in [(e.get("stage"), e.get("status")) for e in ev]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_review_file_round_trips_as_the_contract() -> None:
    res = run(figure_inputs())
    (a,) = res.articles
    assert ArticleReview.model_validate_json(str(res.files[REVP])) == a.review


# -- review fixes (fresh Opus reviewer, 2026-11-02) ----------------------------------------------


@pytest.mark.parametrize("status", [BlockStatus.auto_approved, BlockStatus.approved])
def test_rf1_a_flag_override_on_a_figure_shown_from_no_article_validates(
    status: BlockStatus, tmp_path: Path
) -> None:
    """Minor 1: the figure's block is in no article (a caption reference pulls the figure in)
    and an open flag on it is covered by a flag override; its status is not `flagged` (the newer
    of two flags was resolved). Assembly marks the line overridden; the validator agrees."""
    blocks = [
        blk(1, "See Figure 1.", status=BlockStatus.approved),
        blk(2, type=BlockType.figure, status=status),
        blk(3, "Last.", status=BlockStatus.approved),
    ]
    res = run(
        synth_inputs(
            blocks,
            figures=[figure_data(2)],
            attach={ART: [att(fid(2), rule=AttachRule.caption_ref, anchor=bid(1))]},
            selected={bid(1), bid(3)},
            scope_extra={bid(2)},
            flags=[flag(9, bid(2))],
            overrides=[override(10, "fig ok", flag_id="flag-000009")],
        )
    )
    (fl,) = res.articles[0].review.figure_lines
    assert (fl.status, fl.flag_id) == ("overridden", "flag-000009")
    assert z9(zip_problems(text_files(res), tmp_path)) == []


@pytest.mark.parametrize(
    "text",
    [
        "> [unchecked]: https://example.com",
        "- [unchecked]: https://example.com",
        "1. [Overridden]: <https://x>",
        "[ unchecked ]: /x",
    ],
)
def test_rf2_a_tag_link_definition_inside_a_container_is_refused(text: str) -> None:
    """Minor 2: CommonMark link definitions inside block quotes and list items apply to the
    whole document; the refusal uses the parser's own reference list, not a line regex."""
    blocks = [
        blk(1, text, status=BlockStatus.approved),
        blk(2, "Auto.", status=BlockStatus.auto_approved),
    ]
    with pytest.raises(ExportError, match=bid(1)):
        run(synth_inputs(blocks, marks="visible"))
    assert run(synth_inputs(blocks)).articles  # invisible: no tag to turn into a link


def test_rf2_the_validator_reports_a_tag_link_definition(tmp_path: Path) -> None:
    files = text_files(run(every_status(marks="visible")))
    edit_article(files, lambda t: t + "\n> [unchecked]: https://example.com\n")
    msgs = z9(zip_problems(files, tmp_path))
    assert any("link" in m and "[unchecked]" in m for m in msgs), msgs


def test_rf3_a_tag_line_inside_the_paragraph_above_is_not_a_tag(tmp_path: Path) -> None:
    """Minor 3: block 1's own text ends in a line `[unchecked]` (no blank line before it);
    block 2's real tag removed: the validator names block 2."""
    blocks = [
        blk(1, "Note\n[unchecked]", status=BlockStatus.approved),
        blk(2, "Auto.", status=BlockStatus.auto_approved),
    ]
    files = text_files(run(synth_inputs(blocks, marks="visible")))
    assert z9(zip_problems(files, tmp_path, "ok.zip")) == []
    mk = f"<!-- ml: auto-approved; block: {bid(2)} -->"
    edit_article(files, lambda t: t.replace("[unchecked]\n\n" + mk, mk, 1))
    msgs = z9(zip_problems(files, tmp_path))
    assert any(bid(2) in m and "tag" in m for m in msgs), msgs


def test_rf4_reasons_only_figure_blocks_use_are_numbered_in_block_order(tmp_path: Path) -> None:
    blocks = [
        blk(1, "1 A", type=BlockType.heading, status=BlockStatus.approved),
        blk(2, type=BlockType.figure, status=BlockStatus.queued),
        blk(3, type=BlockType.figure, status=BlockStatus.queued),
        blk(4, "text", status=BlockStatus.approved),
    ]
    res = run(
        synth_inputs(
            blocks,
            figures=[figure_data(2), figure_data(3)],
            overrides=[
                override(10, "reason X", target=bid(2)),
                override(11, "reason Y", target=bid(3)),
            ],
        )
    )
    (a,) = res.articles
    assert [(r.id, r.reason) for r in a.review.reasons] == [("r1", "reason X"), ("r2", "reason Y")]
    files = text_files(res)
    assert z9(zip_problems(files, tmp_path, "ok.zip")) == []

    def swap(d: dict[str, Any]) -> None:
        d["reasons"][0]["reason"], d["reasons"][1]["reason"] = "reason Y", "reason X"
        for e in d["blocks"]:
            if e["reason_id"] in ("r1", "r2"):
                e["reason_id"] = {"r1": "r2", "r2": "r1"}[e["reason_id"]]

    edit_review(files, swap)
    msgs = z9(zip_problems(files, tmp_path))
    assert any("order" in m for m in msgs), msgs


def test_rf5_the_readme_states_the_manifest_s_marks_mode(tmp_path: Path) -> None:
    files = text_files(run(every_status(marks="visible")))
    r = files["README.md"].decode()
    assert "This export was made with visible review marks" in r
    files["README.md"] = r.replace(
        "This export was made with visible review marks", "Visible marks"
    ).encode()
    problems = zip_problems(files, tmp_path)
    assert any(p.code == "Z8" and "marks" in p.detail for p in problems), problems
