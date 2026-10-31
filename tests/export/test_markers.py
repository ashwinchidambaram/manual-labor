"""Design 11 section 20: review markers in the article body and the per-article review sidecar.

M1-M6 run on hand-built inputs (no parser); the real-fixture tests use project-a (clean.pdf and
figures.pdf) and, marked slow, scanned.pdf. Every check here re-derives what it expects without
calling the code under test (markers are matched with a test-local regex, rendered with
markdown-it, reasons decoded with `json.loads`)."""

from __future__ import annotations

import html as htmlmod
import json
import re
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from manuallabor.contracts.article import ArticleReview
from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.contracts.manifest import Manifest
from manuallabor.export.markers import encode_reason
from manuallabor.export.types import ExportError, Problem
from manuallabor.export.validate import split_article, validate_zip
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
REASON = "paper -- rev B > A"
ENC = r'"paper -\u002d rev B \u003e A"'
# the grammar of design 11 section 20.2, written out again here (not imported)
MARKER_RE = re.compile(
    r"^<!-- ml: (?P<status>approved|edited|auto-approved|overridden); "
    r"block: (?P<block>b-[a-z0-9-]+-p\d{3,}-\d{2,})"
    r"(?:; flag: (?P<flag>flag-\d{6}))?(?:; reason: (?P<reason>\"(?:[^\"\\]|\\.)*\"))? -->$"
)
# section 20.11: a marker is the first line of its unit, right after a blank line
_STRIP_RE = re.compile(r"(?<=\n\n)<!-- ml: [^\n]* -->\n")


def strip_markers(text: str) -> str:
    return _STRIP_RE.sub("", text)


def body_of(text: str) -> str:
    return text[text.index("\n---\n", 3) + 5 :]


def parts(text: str) -> list[str]:
    """The units of the body: a text block's unit is its marker line, "\n", its part."""
    return body_of(text).split("\n", 3)[3].rstrip("\n").split("\n\n")


def unmarked(unit: str) -> str:
    """A unit without its leading marker line (a figure line is returned as it is)."""
    first, _, rest = unit.partition("\n")
    return rest if MARKER_RE.match(first) else unit


_LIKE = re.compile(r"(?<!\\)<!--\s*ml\s*:", re.I)  # an unescaped comment opening "ml:"


def marker_lines(text: str) -> list[re.Match[str]]:
    out = []
    for ln in body_of(text).split("\n"):
        if _LIKE.search(ln):
            m = MARKER_RE.match(ln)
            assert m is not None, f"malformed marker {ln!r}"
            out.append(m)
    return out


def visible(md_text: str) -> str:
    """What a reader sees: the rendered HTML without comments and tags, whitespace collapsed."""
    from markdown_it import MarkdownIt

    out = MarkdownIt("commonmark").enable(["table", "strikethrough"]).render(md_text)
    out = re.sub(r"<!--.*?-->", " ", out, flags=re.S)
    out = re.sub(r"<[^>]+>", " ", out)
    return " ".join(htmlmod.unescape(out).split())


def sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def every_status() -> Any:
    blocks = [
        blk(
            1, "1 Intro", type=BlockType.heading, status=BlockStatus.auto_approved, confidence=0.97
        ),
        blk(2, "Approved text.", status=BlockStatus.approved),
        blk(
            3,
            "| a | b |\n| --- | --- |\n| 1 | 2 |",
            type=BlockType.table,
            status=BlockStatus.auto_approved,
            confidence=0.91,
        ),
        blk(4, "raw list", type=BlockType.list, status=BlockStatus.edited, clean="• one\n• two"),
        blk(5, "Queued text.", status=BlockStatus.queued),
        blk(6, "Flagged text.", status=BlockStatus.flagged),
        blk(7, type=BlockType.figure, status=BlockStatus.auto_approved, confidence=0.99),
        blk(8, "Last.", status=BlockStatus.auto_approved, confidence=0.9),
    ]
    return synth_inputs(
        blocks,
        levels={bid(1): 1},
        sections={bid(1): "1"},
        figures=[figure_data(7)],
        attach={ART: [att(fid(7))]},
        flags=[flag(1, bid(6))],
        overrides=[override(5, REASON)],
    )


# -- M1 reason escaping ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "",
        "plain",
        "a -- b",
        "---",
        "----",
        "end -->",
        "<!-- nested -->",
        "x > y < z",
        'quote " and back\\slash',
        "line\nbreak\r\n",
        "sep\u2028and\u2029nel\x85",
        "naïve – en dash — em dash",
        "-",
        "--!>",
    ],
)
def test_m1_reason_escaping_round_trips_and_never_ends_the_comment(reason: str) -> None:
    enc = encode_reason(reason)
    assert json.loads(enc) == reason
    assert "--" not in enc and ">" not in enc and "<" not in enc
    assert len(enc.splitlines()) == 1 and "\n" not in enc
    line = f"<!-- ml: overridden; block: b-doc-p001-01; reason: {enc} -->"
    m = MARKER_RE.match(line)
    assert m is not None and json.loads(m.group("reason")) == reason
    assert "--" not in line[4:-3]


@settings(max_examples=300, deadline=None)
@given(st.text())
def test_m1_reason_escaping_property(reason: str) -> None:
    enc = encode_reason(reason)
    assert json.loads(enc) == reason
    assert "--" not in enc and ">" not in enc and "<" not in enc
    assert len(enc.splitlines()) == 1


def test_m1_the_worked_example_reason() -> None:
    assert encode_reason(REASON) == ENC


# -- M2 markers and sidecar on every status ----------------------------------------------------


def test_m2_n1_every_paragraph_starts_with_its_marker() -> None:
    """Section 20.11: the marker is on the line before its paragraph (a blank line above it, the
    paragraph directly below), and every text block has one, a person's decisions included."""
    res = run(every_status())
    (a,) = res.articles
    m1 = f"<!-- ml: auto-approved; block: {bid(1)} -->"
    m2 = f"<!-- ml: approved; block: {bid(2)} -->"
    m3 = f"<!-- ml: auto-approved; block: {bid(3)} -->"
    m4 = f"<!-- ml: edited; block: {bid(4)} -->"
    m5 = f"<!-- ml: overridden; block: {bid(5)}; reason: {ENC} -->"
    m6 = f"<!-- ml: overridden; block: {bid(6)}; flag: flag-000001; reason: {ENC} -->"
    m8 = f"<!-- ml: auto-approved; block: {bid(8)} -->"
    fig = next(p for p in parts(a.text) if p.startswith("![FIG-"))
    assert parts(a.text) == [
        m1 + "\n## 1 Intro",
        m2 + "\nApproved text.",
        m3 + "\n| a | b |\n| --- | --- |\n| 1 | 2 |",  # the whole table is one unit
        m4 + "\n* one\n* two",
        m5 + "\nQueued text.",
        m6 + "\nFlagged text.",
        fig,  # a figure block has no marker
        m8 + "\nLast.",
    ]
    assert [m.group("block") for m in marker_lines(a.text)] == [
        bid(n) for n in (1, 2, 3, 4, 5, 6, 8)
    ]
    assert "\n# Main topic\n\n" + m1 + "\n## 1 Intro\n" in a.text  # the title, a blank line


def test_m2_the_sidecar_lists_every_block_with_who_decided_it() -> None:
    res = run(every_status())
    (a,) = res.articles
    rv = a.review
    assert isinstance(rv, ArticleReview)
    assert a.review_path == f"articles/{ART}.review.json"
    assert rv.article_id == ART and rv.article == f"articles/{ART}.md"
    assert rv.generated_at == CLOCK
    assert [b.block_id for b in rv.blocks] == a.block_ids == [bid(n) for n in range(1, 9)]
    by = {b.block_id: b for b in rv.blocks}

    def row(n: int) -> dict[str, Any]:
        return by[bid(n)].model_dump(mode="json")

    assert [row(n)["placement"] for n in range(1, 9)] == ["paragraph"] * 6 + [
        "figure",
        "paragraph",
    ]
    assert row(3)["text"] == "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert row(4)["text"] == "* one\n* two" and row(7)["text"] is None
    assert row(1) == {
        "block_id": bid(1),
        "type": "heading",
        "page": 1,
        "status": "auto_approved",
        "decided_by": "checks",
        "at": None,
        "confidence": 0.97,
        "edited_by": None,
        "reason": None,
        "flag_id": None,
        "figure": None,
        "text_sha256": sha("## 1 Intro"),
        "text": "## 1 Intro",
        "placement": "paragraph",
    }
    assert (row(2)["status"], row(2)["decided_by"], row(2)["at"]) == (
        "approved",
        "person",
        "2026-10-29T12:00:00Z",
    )
    assert row(2)["confidence"] is None and row(2)["edited_by"] is None
    assert (row(3)["type"], row(3)["status"], row(3)["confidence"]) == (
        "table",
        "auto_approved",
        0.91,
    )
    assert (row(4)["status"], row(4)["decided_by"], row(4)["edited_by"]) == (
        "edited",
        "person",
        "person",
    )
    assert row(5) == {
        "block_id": bid(5),
        "type": "paragraph",
        "page": 1,
        "status": "overridden",
        "decided_by": "override",
        "at": "2026-10-29T12:00:00Z",
        "confidence": None,
        "edited_by": None,
        "reason": REASON,
        "flag_id": None,
        "figure": None,
        "text_sha256": sha("Queued text."),
        "text": "Queued text.",
        "placement": "paragraph",
    }
    assert (row(6)["status"], row(6)["flag_id"], row(6)["reason"]) == (
        "overridden",
        "flag-000001",
        REASON,
    )
    assert row(7)["type"] == "figure" and row(7)["status"] == "auto_approved"
    assert row(7)["figure"] == {
        "figure_id": fid(7),
        "placements": [{"article_id": ART, "rule": "proximity", "confidence": 0.9}],
    }
    assert rv.counts.model_dump() == {
        "auto_approved": 4,
        "approved": 1,
        "edited": 1,
        "overridden": 2,
    }
    fm = a.frontmatter
    assert fm.blocks == len(rv.blocks) == 8
    # section 20.11: the front matter counts are the sidecar's, category for category
    assert fm.review.model_dump() == rv.counts.model_dump()
    assert "\nreview: { auto_approved: 4, approved: 1, edited: 1, overridden: 2 }\n" in a.text
    # the sidecar is in the zip next to its article and the manifest points at it
    assert ArticleReview.model_validate_json(str(res.files[a.review_path])) == rv
    (ma,) = res.manifest.articles
    assert ma.review_sidecar == a.review_path
    # the overridden entries are the manifest's overrides
    assert [(o.target_id, o.reason, o.flag_id) for o in res.manifest.overrides] == [
        (bid(5), REASON, None),
        (bid(6), REASON, "flag-000001"),
    ]


def test_m2_a_figure_block_shown_in_no_article_has_empty_placements() -> None:
    blocks = [
        blk(1, "Text.", status=BlockStatus.approved),
        blk(2, type=BlockType.figure, status=BlockStatus.approved),
    ]
    res = run(synth_inputs(blocks, figures=[figure_data(2)]))  # not attached anywhere
    (a,) = res.articles
    (entry,) = [b for b in a.review.blocks if b.type == BlockType.figure]
    assert entry.figure is not None and entry.figure.placements == []
    assert entry.status == "approved" and entry.decided_by == "person"
    assert entry.placement == "figure" and entry.text is None
    assert [m.group(0) for m in marker_lines(a.text)] == [f"<!-- ml: approved; block: {bid(1)} -->"]


def test_m2_a_covered_approved_block_with_an_open_flag_is_overridden() -> None:
    blocks = [blk(1, "A.", status=BlockStatus.approved), blk(2, "B.", status=BlockStatus.approved)]
    res = run(
        synth_inputs(
            blocks, flags=[flag(3, bid(2))], overrides=[override(4, "ok", flag_id="flag-000003")]
        )
    )
    (a,) = res.articles
    e = {b.block_id: b for b in a.review.blocks}[bid(2)]
    assert (e.status, e.decided_by, e.flag_id, e.reason) == (
        "overridden",
        "override",
        "flag-000003",
        "ok",
    )
    assert (
        parts(a.text)[-1]
        == f'<!-- ml: overridden; block: {bid(2)}; flag: flag-000003; reason: "ok" -->\nB.'
    )


# -- M3 markers are not text -------------------------------------------------------------------


def test_m3_stripping_markers_gives_the_previous_output_and_the_same_visible_text() -> None:
    res = run(every_status())
    (a,) = res.articles
    stripped = strip_markers(a.text)
    # the pre-section-20 body: the same parts, no markers
    want_parts = [unmarked(p) for p in parts(a.text)]
    assert want_parts != parts(a.text)
    assert (
        stripped
        == a.text[: a.text.index("\n# ")] + "\n# Main topic\n\n" + "\n\n".join(want_parts) + "\n"
    )
    assert visible(body_of(a.text)) == visible(body_of(stripped))
    assert "ml:" not in visible(body_of(a.text))


@pytest.mark.parametrize(
    "text,type_",
    [
        ("| h | i |\n| --- | --- |\n| 1 | 2 |", BlockType.table),
        ("• a\n• b", BlockType.list),
        ("    indented code", BlockType.paragraph),
        ("> quoted", BlockType.paragraph),
        ("ends with a backslash \\", BlockType.paragraph),
        ("<div>raw html</div>", BlockType.paragraph),
        ("1. first\n2. second", BlockType.list),
        ("trailing spaces  ", BlockType.paragraph),
        ("Setext heading\n===", BlockType.paragraph),
        ("# looks like a heading", BlockType.paragraph),
        ("--> an arrow first", BlockType.paragraph),
    ],
)
def test_m3_markers_never_show_after_tricky_source(text: str, type_: BlockType) -> None:
    blocks = [
        blk(1, text, type=type_, status=BlockStatus.auto_approved, confidence=0.9),
        blk(2, "Next paragraph.", status=BlockStatus.auto_approved, confidence=0.9),
    ]
    (a,) = run(synth_inputs(blocks)).articles
    assert len(marker_lines(a.text)) == 2
    assert visible(body_of(a.text)) == visible(body_of(strip_markers(a.text)))
    assert "ml:" not in visible(body_of(a.text))


# -- M4 a marker that would show is refused ----------------------------------------------------


@pytest.mark.parametrize("opener", ["```\ncode", "~~~\ncode", "<pre>\nraw", "<!-- open comment"])
def test_m4_an_open_construct_before_a_marked_block_refuses_the_export(opener: str) -> None:
    blocks = [
        blk(1, opener, status=BlockStatus.approved),
        blk(2, "After.", status=BlockStatus.auto_approved, confidence=0.9),
    ]
    with pytest.raises(ExportError) as ei:
        run(synth_inputs(blocks))
    msg = str(ei.value)
    assert bid(2) in msg and "marker" in msg and "Verify" in msg


def test_m4_n6_an_open_construct_before_an_approved_block_refuses_the_export() -> None:
    """Section 20.11 (k): every paragraph has a marker now, so approving the next block no longer
    avoids the swallowed marker; the way out is the block that opens the construct."""
    blocks = [
        blk(1, "```\ncode", status=BlockStatus.approved),
        blk(2, "B.", status=BlockStatus.approved),
    ]
    with pytest.raises(ExportError) as ei:
        run(synth_inputs(blocks))
    msg = str(ei.value)
    assert bid(2) in msg and "opens" in msg and "Approve" not in msg


def test_m4_an_open_construct_in_the_last_unit_is_not_refused() -> None:
    blocks = [
        blk(1, "A.", status=BlockStatus.approved),
        blk(2, "```\ncode", status=BlockStatus.approved),
    ]
    assert run(synth_inputs(blocks)).articles


def test_m4_source_text_that_looks_like_a_marker_is_refused() -> None:
    blocks = [
        blk(1, "<!-- ml: auto-approved; block: b-doc-p001-09 -->", status=BlockStatus.approved),
    ]
    with pytest.raises(ExportError, match=f"{bid(1)}: .*review marker"):
        run(synth_inputs(blocks))


# -- M5 determinism ----------------------------------------------------------------------------


def test_m5_two_assembles_are_byte_identical() -> None:
    a, b = run(every_status()), run(every_status())
    assert a.files == b.files
    assert any(n.endswith(".review.json") for n in a.files)


# -- M6 the validator --------------------------------------------------------------------------

Files = dict[str, bytes]


def synth_zip(tmp: Path) -> Files:
    """A synthetic export (no figures, so every file is text) with overrides and markers."""
    blocks = [
        blk(
            1, "1 Intro", type=BlockType.heading, status=BlockStatus.auto_approved, confidence=0.97
        ),
        blk(2, "Approved text.", status=BlockStatus.approved),
        blk(3, "Auto text.", status=BlockStatus.auto_approved, confidence=0.91),
        blk(4, "Queued text.", status=BlockStatus.queued),
        blk(5, "Flagged text.", status=BlockStatus.flagged),
    ]
    res = run(
        synth_inputs(
            blocks,
            levels={bid(1): 1},
            flags=[flag(1, bid(5))],
            overrides=[override(5, REASON)],
        )
    )
    files = {n: v.encode("utf-8") for n, v in res.files.items() if isinstance(v, str)}
    assert len(files) == len(res.files)
    return files


def check(tmp: Path, fn: Callable[[Files], None]) -> list[Problem]:
    files = synth_zip(tmp)
    fn(files)
    out = tmp / "m.zip"
    write_zip(files, out)
    return validate_zip(out)


def z9(problems: list[Problem]) -> list[str]:
    return [f"{p.where}: {p.detail}" for p in problems if p.code == "Z9"]


ARTP = f"articles/{ART}.md"
REVP = f"articles/{ART}.review.json"


def edit_review(files: Files, fn: Callable[[dict[str, Any]], None]) -> None:
    d = json.loads(files[REVP])
    fn(d)
    files[REVP] = (json.dumps(d, sort_keys=True, indent=2) + "\n").encode()


def edit_article(files: Files, fn: Callable[[str], str]) -> None:
    files[ARTP] = fn(files[ARTP].decode()).encode()


def test_m6_the_synthetic_export_validates(tmp_path: Path) -> None:
    assert check(tmp_path, lambda f: None) == []


def test_m6_a_tampered_status_fails(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        def t(d: dict[str, Any]) -> None:
            e = d["blocks"][2]
            assert e["block_id"] == bid(3)
            e.update(
                status="approved", decided_by="person", confidence=None, at="2026-10-29T12:00:00Z"
            )
            d["counts"]["auto_approved"] -= 1
            d["counts"]["approved"] += 1

        edit_review(f, t)

    msgs = z9(check(tmp_path, fn))
    assert any(bid(3) in m and "auto-approved" in m and "approved" in m for m in msgs), msgs


def test_m6_a_missing_marker_fails(tmp_path: Path) -> None:
    gone = f"<!-- ml: auto-approved; block: {bid(3)} -->\n"

    def fn(f: Files) -> None:
        edit_article(f, lambda t: t.replace(gone, "", 1) if gone in t else pytest.fail("no marker"))

    msgs = z9(check(tmp_path, fn))
    assert any(bid(3) in m and "no marker" in m for m in msgs), msgs


def test_m6_a_marker_moved_into_the_paragraph_fails(tmp_path: Path) -> None:
    mk = f"<!-- ml: auto-approved; block: {bid(3)} -->"

    def fn(f: Files) -> None:
        edit_article(f, lambda t: t.replace(mk + "\nAuto text.", "Auto text. " + mk, 1))

    msgs = z9(check(tmp_path, fn))
    assert any(bid(3) in m and "own" in m for m in msgs), msgs


def test_m6_a_marker_swallowed_by_a_fence_fails(tmp_path: Path) -> None:
    mk = f"<!-- ml: auto-approved; block: {bid(3)} -->"

    def fn(f: Files) -> None:
        edit_article(f, lambda t: t.replace("\n\n" + mk, "\n\n```\n" + mk, 1))
        assert mk in f[ARTP].decode()

    msgs = z9(check(tmp_path, fn))
    assert any(bid(3) in m and "fence" in m for m in msgs), msgs


def test_m6_a_changed_reason_fails(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        edit_article(f, lambda t: t.replace(ENC, '"something else"', 1))

    msgs = z9(check(tmp_path, fn))
    assert any(bid(4) in m and "reason" in m for m in msgs), msgs


def test_m6_a_dropped_sidecar_entry_fails(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        def t(d: dict[str, Any]) -> None:
            e = d["blocks"].pop(1)
            assert e["status"] == "approved"
            d["counts"]["approved"] -= 1

        edit_review(f, t)

    msgs = z9(check(tmp_path, fn))
    assert any(bid(2) in m and "missing" in m for m in msgs), msgs
    assert any("blocks" in m for m in msgs), msgs  # the front matter count no longer agrees


def test_m6_a_duplicated_sidecar_entry_fails(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        edit_review(f, lambda d: d["blocks"].append(d["blocks"][1]))

    msgs = z9(check(tmp_path, fn))
    assert any("does not validate" in m for m in msgs), msgs


def test_m6_counts_out_of_tally_fail(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        edit_review(f, lambda d: d["counts"].update(approved=d["counts"]["approved"] + 1))

    assert any("does not validate" in m for m in z9(check(tmp_path, fn)))


def test_m6_front_matter_counts_must_equal_the_sidecar(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        def t(text: str) -> str:
            # the sidecar says auto_approved 2, approved 1: swap them in the front matter only
            old = "review: { auto_approved: 2, approved: 1, edited: 0, overridden: 2 }"
            assert old in text
            return text.replace(
                old, "review: { auto_approved: 1, approved: 2, edited: 0, overridden: 2 }", 1
            )

        edit_article(f, t)

    msgs = z9(check(tmp_path, fn))
    assert any("review.approved 2 != review sidecar 1" in m for m in msgs), msgs
    assert any("review.auto_approved 1 != review sidecar 2" in m for m in msgs), msgs


def test_m6_a_missing_or_stray_sidecar_file_fails(tmp_path: Path) -> None:
    msgs = z9(check(tmp_path, lambda f: f.pop(REVP)))
    assert any(REVP in m and "missing" in m for m in msgs), msgs

    def stray(f: Files) -> None:
        f["articles/doc--other.review.json"] = f[REVP]

    problems = check(tmp_path, stray)
    assert any("doc--other.review.json" in m for m in z9(problems)), problems


def test_m6_manifest_overrides_must_match_the_sidecar(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        m = json.loads(f["manifest.json"])
        m["overrides"][0]["reason"] = "another reason"
        f["manifest.json"] = (json.dumps(m, sort_keys=True, indent=2) + "\n").encode()

    msgs = z9(check(tmp_path, fn))
    assert any(bid(4) in m and "manifest.overrides" in m for m in msgs), msgs


def test_m6_an_unchecked_marker_on_a_person_checked_block_fails(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        old = f"<!-- ml: approved; block: {bid(2)} -->"
        edit_article(
            f,
            lambda t: (
                t.replace(old, f"<!-- ml: auto-approved; block: {bid(2)} -->", 1)
                if old in t
                else pytest.fail("no approved marker")
            ),
        )

    msgs = z9(check(tmp_path, fn))
    assert any(
        bid(2) in m and "marker says auto-approved, sidecar says approved" in m for m in msgs
    ), msgs


def test_m6_the_manifest_must_point_at_the_sidecar(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        m = json.loads(f["manifest.json"])
        m["articles"][0]["review_sidecar"] = "articles/x.review.json"
        f["manifest.json"] = (json.dumps(m, sort_keys=True, indent=2) + "\n").encode()

    assert "Z2" in {p.code for p in check(tmp_path, fn)}


# -- real fixtures -----------------------------------------------------------------------------


def _check_markers_and_sidecars(zf: zipfile.ZipFile) -> dict[str, int]:
    """Every article of a real export against its sidecar and the manifest, independently of
    validate.py. Returns tallies for the caller's assertions."""
    m = Manifest.model_validate_json(zf.read("manifest.json"))
    names = set(zf.namelist())
    seen = {"auto": 0, "person": 0, "override": 0, "figure": 0, "markers": 0}
    by_place: dict[tuple[str, str], int] = {}
    overrides = {o.target_id: o for o in m.overrides}
    for a in m.articles:
        assert a.review_sidecar == f"articles/{a.id}.review.json" and a.review_sidecar in names
        rv = ArticleReview.model_validate_json(zf.read(a.review_sidecar))
        assert [b.block_id for b in rv.blocks] == a.block_ids
        text = zf.read(a.path).decode("utf-8")
        fm, _ = split_article(text)
        assert fm["blocks"] == len(rv.blocks)
        # section 20.11: the front matter counts are the sidecar's categories, key for key
        assert fm["review"] == rv.counts.model_dump(), a.id
        want = []
        for b in rv.blocks:
            key = (b.placement, b.status)
            by_place[key] = by_place.get(key, 0) + 1
            assert (b.placement == "figure") == (b.type == BlockType.figure)
            if b.type == BlockType.figure:
                seen["figure"] += 1
                assert b.figure is not None
                shown = sorted(x.id for x in m.articles if b.figure.figure_id in x.figures)
                assert [p.article_id for p in b.figure.placements] == shown
            if b.status == "auto_approved":
                seen["auto"] += 1
                assert b.confidence is not None and b.at is None
            elif b.status in ("approved", "edited"):
                seen["person"] += 1
                assert b.at is not None and b.decided_by == "person"
            else:
                seen["override"] += 1
                o = overrides[b.block_id]
                assert (o.reason, o.flag_id, o.at) == (b.reason, b.flag_id, b.at)
            if b.type != BlockType.figure:  # every paragraph has a marker (20.11)
                want.append(b)
        got = marker_lines(text)
        seen["markers"] += len(got)
        assert [g.group("block") for g in got] == [b.block_id for b in want], a.id
        for g, b in zip(got, want, strict=True):
            assert g.group("status") == b.status.replace("_", "-")
            assert g.group("flag") == b.flag_id
            assert (json.loads(g.group("reason")) if g.group("reason") else None) == b.reason
            # on its own line after a blank line, its paragraph's first characters right below
            assert b.text is not None and len(b.text) <= 80
            assert "\n\n" + g.group(0) + "\n" + b.text in text, b.block_id
        assert visible(body_of(text)) == visible(body_of(strip_markers(text))), a.id
        assert "ml:" not in visible(body_of(text))
    for (place, status), n in by_place.items():
        seen[f"{place}:{status}"] = n
    return seen


def test_markers_and_sidecars_on_project_a(exported_a: Any) -> None:
    with zipfile.ZipFile(exported_a.zip) as zf:
        seen = _check_markers_and_sidecars(zf)
    assert seen["auto"] > 20 and seen["person"] > 0 and seen["figure"] >= 10
    assert seen["override"] == 0 and seen["markers"] > 0
    assert validate_zip(exported_a.zip) == []


def read_all(zp: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(zp) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def test_export_twice_gives_byte_identical_articles_and_sidecars(work: Any, tmp_path: Path) -> None:
    from manuallabor.export.pipeline import resolve_clock, run_export
    from manuallabor.state.store import Store
    from tests.export.helpers import CLOCK as HCLOCK

    store = Store.open(work)
    try:
        r1 = run_export(work, store, clock=resolve_clock(HCLOCK), emit=lambda _o: None)
        first = read_all(Path(r1.zip_path))
        r2 = run_export(work, store, clock=resolve_clock(HCLOCK), emit=lambda _o: None, force=True)
        second = read_all(Path(r2.zip_path))
    finally:
        store.close()
    assert [n for n in first if n.endswith(".review.json")]
    for n in first:
        if n.startswith("articles/"):
            assert first[n] == second[n], n
    assert first == second


@pytest.mark.slow
def test_export_markers_on_scanned_pdf(requires_docling: None, tmp_path: Path) -> None:
    """The scanned case (SPEC: exercise every feature on scanned.pdf): a person approves one
    block, an override with `--` and `>` in its reason covers the rest; the export validates,
    each overridden paragraph's marker decodes to the reason, the approved one has none."""
    from manuallabor.export.pipeline import record_override, resolve_clock, run_export
    from manuallabor.state.data import ProjectData
    from manuallabor.state.models import ReviewActionIn
    from manuallabor.state.review import load_review_blocks
    from manuallabor.state.store import Store
    from tests.conftest import FIXTURES
    from tests.export.helpers import CLOCK as HCLOCK
    from tests.export.helpers import build_scored, reviewer

    paths = build_scored(tmp_path / "proj", [FIXTURES / "scanned.pdf"])
    store = Store.open(paths)
    try:
        data = ProjectData(paths, store)
        scope = data.scope_ids("scanned", set(data.selection().block_ids))
        queued = [
            b
            for b in load_review_blocks(paths, store, "scanned")
            if b.id in scope and b.status == BlockStatus.queued and b.type != BlockType.figure
        ]
        assert len(queued) >= 2, "scanned.pdf queues blocks for a person"
        approved = queued[0].id
        reviewer(paths, store).act(
            ReviewActionIn(kind="approve", block_id=approved, request_id="t-scan-approve")
        )
        reason = "checked on paper -- rev B > rev A"
        record_override(paths, store, reason, request_id="t-scan-override")
        rec = run_export(paths, store, clock=resolve_clock(HCLOCK), emit=lambda _o: None)
    finally:
        store.close()
    zp = Path(rec.zip_path)
    assert validate_zip(zp) == []
    with zipfile.ZipFile(zp) as zf:
        seen = _check_markers_and_sidecars(zf)
        m = Manifest.model_validate_json(zf.read("manifest.json"))
        bodies = "\n".join(zf.read(a.path).decode() for a in m.articles)
        reviews = [ArticleReview.model_validate_json(zf.read(a.review_sidecar)) for a in m.articles]
    assert seen["override"] >= 1 and seen["person"] >= 1
    entry = next(b for r in reviews for b in r.blocks if b.block_id == approved)
    assert entry.status == "approved" and entry.at is not None
    assert f"\n\n<!-- ml: approved; block: {approved} -->\n" in bodies
    decoded = [
        json.loads(mm.group("reason"))
        for ln in bodies.split("\n")
        if (mm := MARKER_RE.match(ln)) and mm.group("status") == "overridden"
    ]
    assert decoded and set(decoded) == {reason}
    assert "-- rev B" not in bodies  # the reason never appears unescaped in a comment


# -- review fixes (fresh reviewer, 2026-10-31) -------------------------------------------------


def test_r1_a_marker_moved_before_another_paragraph_fails(tmp_path: Path) -> None:
    """Reviewer major (20.10), in the 20.11 layout: block 03's marker moved to stand above the
    approved block 02 in place of its own marker."""
    mk = f"<!-- ml: auto-approved; block: {bid(3)} -->"
    m2 = f"<!-- ml: approved; block: {bid(2)} -->"

    def fn(f: Files) -> None:
        def t(text: str) -> str:
            new = text.replace(mk + "\n", "", 1).replace(m2, mk, 1)
            assert new != text
            return new

        edit_article(f, t)

    msgs = z9(check(tmp_path, fn))
    assert any(bid(2) in m and "no marker directly before" in m for m in msgs), msgs


def test_r1_n1_a_marker_after_its_paragraph_fails(tmp_path: Path) -> None:
    """The first version's layout (marker after its paragraph) is what misled the reader: it
    fails Z9 naming the block."""
    mk = f"<!-- ml: auto-approved; block: {bid(3)} -->"

    def fn(f: Files) -> None:
        def t(text: str) -> str:
            new = text.replace(mk + "\nAuto text.", "Auto text.\n\n" + mk, 1)
            assert new != text
            return new

        edit_article(f, t)

    msgs = z9(check(tmp_path, fn))
    assert any(bid(3) in m and "no marker directly before" in m for m in msgs), msgs
    assert any(bid(3) in m and "not directly before its paragraph" in m for m in msgs), msgs


def test_r1_two_markers_in_a_row_fail(tmp_path: Path) -> None:
    m1 = f"<!-- ml: auto-approved; block: {bid(1)} -->"
    m3 = f"<!-- ml: auto-approved; block: {bid(3)} -->"

    def fn(f: Files) -> None:
        edit_article(f, lambda t: t.replace(m3 + "\n", "", 1).replace(m1, m3 + "\n\n" + m1, 1))

    msgs = z9(check(tmp_path, fn))
    assert any(bid(3) in m and "not directly before its paragraph" in m for m in msgs), msgs


def test_r1_a_changed_paragraph_text_fails(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        edit_article(f, lambda t: t.replace("Auto text.", "Auto text, changed.", 1))

    msgs = z9(check(tmp_path, fn))
    assert any(bid(3) in m and "text" in m for m in msgs), msgs


def test_r1_every_text_entry_carries_the_sha256_of_its_part() -> None:
    import hashlib

    res = run(every_status())
    (a,) = res.articles
    texts = {p.block_id: p.text for p in a.body_parts if p.kind == "block"}
    for e in a.review.blocks:
        if e.type == BlockType.figure:
            assert e.text_sha256 is None
        else:
            assert e.text_sha256 == hashlib.sha256(texts[e.block_id].encode()).hexdigest()


def test_r2_a_lookalike_marker_without_the_space_fails(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        edit_article(
            f,
            lambda t: t.replace(
                f"<!-- ml: approved; block: {bid(2)} -->",
                f"<!--ml: approved; block: {bid(2)} -->",
                1,
            ),
        )

    msgs = z9(check(tmp_path, fn))
    assert any("<!--ml:" in m for m in msgs), msgs


def test_r2_source_text_with_a_lookalike_marker_is_refused() -> None:
    blocks = [blk(1, "see <!--ML : x -->", status=BlockStatus.approved)]
    with pytest.raises(ExportError, match=bid(1)):
        run(synth_inputs(blocks))


def test_r3_a_caption_that_looks_like_a_marker_is_escaped_not_blamed_on_a_block() -> None:
    """Reviewer minor: a marker-shaped figure caption or generated description was blamed on
    another block. Alt text escapes `<` (a CommonMark punctuation escape), so it is never a
    comment and never a marker."""
    blocks = [
        blk(1, "Text.", status=BlockStatus.approved),
        blk(2, type=BlockType.figure, status=BlockStatus.approved),
    ]
    cap = f"see <!-- ml: auto-approved; block: {bid(1)} -->"
    res = run(
        synth_inputs(blocks, figures=[figure_data(2, caption=cap)], attach={ART: [att(fid(2))]})
    )
    (a,) = res.articles
    line = next(p for p in parts(a.text) if p.startswith("![FIG-"))
    assert "\\<!-- ml:" in line
    assert [m.group("block") for m in marker_lines(a.text)] == [bid(1)]
    assert res.manifest.articles[0].figures == [fid(2)]


def test_r3_a_title_that_looks_like_a_marker_is_refused_by_name() -> None:
    blocks = [blk(1, "Text.", status=BlockStatus.auto_approved, confidence=0.9)]
    inp = synth_inputs(blocks, topics={"main": ("Main <!-- ml: x", [bid(1)])})
    with pytest.raises(ExportError, match="title"):
        run(inp)


def test_r4_two_flags_with_their_own_overrides_pair_flag_and_reason() -> None:
    """Reviewer minor: a block with two open flags, each covered by its own flag override, got
    the first flag's id and the latest override's reason."""
    blocks = [blk(1, "A.", status=BlockStatus.approved)]
    res = run(
        synth_inputs(
            blocks,
            flags=[flag(1, bid(1)), flag(2, bid(1))],
            overrides=[
                override(5, "ok for flag one", flag_id="flag-000001"),
                override(6, "ok for flag two", flag_id="flag-000002"),
            ],
        )
    )
    (a,) = res.articles
    (e,) = a.review.blocks
    assert (e.flag_id, e.reason) == ("flag-000002", "ok for flag two")
    (o,) = res.manifest.overrides
    assert (o.flag_id, o.reason) == ("flag-000002", "ok for flag two")
    (mk,) = marker_lines(a.text)
    assert mk.group("flag") == "flag-000002" and mk.group("status") == "overridden"


# -- re-review fixes (2026-10-31) --------------------------------------------------------------


@pytest.mark.parametrize(
    "texts",
    [
        ("a\n", "b"),  # a person's edit ending in Enter
        ("a", "b\n"),
        ("a\n\n", "b"),
        ("\na", "b"),
        ("a\n\n\nb", "c"),
        ("", "b"),
        ("a", "a"),
    ],
)
def test_rr1_parts_with_newlines_at_their_edges_validate(
    texts: tuple[str, str], tmp_path: Path
) -> None:
    blocks = [
        blk(1, "x", status=BlockStatus.edited, clean=texts[0])
        if texts[0].strip()
        else blk(1, "x", status=BlockStatus.auto_approved, clean=texts[0]),
        blk(2, "y", status=BlockStatus.auto_approved, clean=texts[1]),
        blk(3, "z", status=BlockStatus.approved, clean=texts[1]),
    ]
    res = run(synth_inputs(blocks))
    files = {n: v.encode() for n, v in res.files.items() if isinstance(v, str)}
    write_zip(files, tmp_path / "e.zip")
    assert validate_zip(tmp_path / "e.zip") == []


def test_rr2_an_override_naming_a_flag_not_open_on_the_block_records_the_block_s_own_flag() -> None:
    blocks = [blk(1, "A.", status=BlockStatus.queued), blk(2, "B.", status=BlockStatus.approved)]
    # flag 1 is on block 2; the override targets block 1 and (wrongly) names block 2's flag
    res = run(
        synth_inputs(
            blocks,
            flags=[flag(1, bid(2))],
            overrides=[
                override(5, "for b1", target=bid(1), flag_id="flag-000001"),
            ],
        )
    )
    (a,) = res.articles
    e = {b.block_id: b for b in a.review.blocks}
    assert e[bid(1)].flag_id is None  # flag-000001 is not a flag on block 1
    assert (e[bid(2)].status, e[bid(2)].flag_id) == ("overridden", "flag-000001")


def test_rr2_a_blanket_then_block_override_records_the_decision_about_the_flag() -> None:
    blocks = [blk(1, "A.", status=BlockStatus.queued)]
    res = run(
        synth_inputs(
            blocks,
            flags=[flag(1, bid(1))],
            overrides=[override(5, "blanket reason"), override(6, "block reason", target=bid(1))],
        )
    )
    (e,) = res.articles[0].review.blocks
    assert (e.flag_id, e.reason) == ("flag-000001", "blanket reason")


@pytest.mark.parametrize("text", ["a \\\\<!-- ml: x -->", "a \\<!-- ml: x -->"])
def test_rr3_backslashes_never_hide_a_marker_in_source_text(text: str) -> None:
    with pytest.raises(ExportError, match="review marker"):
        run(synth_inputs([blk(1, text, status=BlockStatus.approved)]))


def test_rr3_an_even_run_of_backslashes_does_not_escape_a_marker_for_the_validator(
    tmp_path: Path,
) -> None:
    def fn(f: Files) -> None:
        edit_article(
            f,
            lambda t: t.replace(
                "Approved text.",
                f"Approved text. \\\\<!-- ml: auto-approved; block: {bid(2)} -->",
                1,
            ),
        )

    assert z9(check(tmp_path, fn))


def test_rr4_a_block_with_an_external_image_link_validates(tmp_path: Path) -> None:
    """Re-review: source text holding an image link outside images/ is left alone (no Z4) and,
    being a block of the article, passes Z9."""
    blocks = [
        blk(
            1,
            "Source text with ![logo](https://example.com/logo.png) in it.",
            status=BlockStatus.auto_approved,
        ),
        blk(2, "Next.", status=BlockStatus.approved),
    ]
    res = run(synth_inputs(blocks))
    files = {n: v.encode() for n, v in res.files.items() if isinstance(v, str)}
    write_zip(files, tmp_path / "e.zip")
    assert validate_zip(tmp_path / "e.zip") == []


# -- third first-use report (design 11 section 20.11) ------------------------------------------


def _zip_of(res: Any, tmp: Path, name: str = "e.zip") -> Path:
    files = {
        n: v.encode() if isinstance(v, str) else Path(v).read_bytes() for n, v in res.files.items()
    }
    write_zip(files, tmp / name)
    return tmp / name


def test_n1_a_paragraph_without_its_approved_marker_fails(tmp_path: Path) -> None:
    """A missing marker never means "a person checked it": an approved paragraph whose marker
    was stripped is a problem, like any other."""
    gone = f"<!-- ml: approved; block: {bid(2)} -->\n"

    def fn(f: Files) -> None:
        edit_article(f, lambda t: t.replace(gone, "", 1) if gone in t else pytest.fail("none"))

    msgs = z9(check(tmp_path, fn))
    assert any(bid(2) in m and "no marker directly before" in m for m in msgs), msgs


def test_n1_stripping_every_marker_fails_for_every_paragraph(tmp_path: Path) -> None:
    """An export whose comments a converter removed reads as broken, not as all checked."""
    msgs = z9(check(tmp_path, lambda f: edit_article(f, strip_markers)))
    for n in (1, 2, 3, 4, 5):
        assert any(bid(n) in m and "no marker" in m for m in msgs), (n, msgs)


def test_n2_the_sidecar_carries_the_first_80_characters_of_each_paragraph(
    tmp_path: Path,
) -> None:
    long = "Torque the cover plate bolts to 35 N·m in a cross pattern, then check " * 3
    blocks = [
        blk(1, "Short.", status=BlockStatus.approved),
        blk(2, long, status=BlockStatus.auto_approved, confidence=0.9),
        blk(3, "• one\n• two", type=BlockType.list, status=BlockStatus.approved),
        blk(4, type=BlockType.figure, status=BlockStatus.approved),
    ]
    res = run(synth_inputs(blocks, figures=[figure_data(4)], attach={ART: [att(fid(4))]}))
    (a,) = res.articles
    by = {e.block_id: e for e in a.review.blocks}
    assert by[bid(1)].text == "Short."
    assert by[bid(2)].text == long[:80] and len(long) > 80
    assert by[bid(3)].text == "* one\n* two"
    assert by[bid(4)].text is None and by[bid(4)].placement == "figure"
    # written by dump_json right before the hash
    raw = str(res.files[a.review_path])
    assert raw.index('"text": "Short."') < raw.index('"text_sha256"')
    no_figure = run(synth_inputs(blocks[:3]))  # synthetic figures have no image file
    assert validate_zip(_zip_of(no_figure, tmp_path)) == []


def test_n2_a_tampered_text_fails(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        def t(d: dict[str, Any]) -> None:
            assert d["blocks"][2]["text"] == "Auto text."
            d["blocks"][2]["text"] = "Approved text."

        edit_review(f, t)

    msgs = z9(check(tmp_path, fn))
    assert any(bid(3) in m and "text" in m for m in msgs), msgs


def dana_torque() -> Any:
    """Dana's torque article: 2 approved by her, 2 auto-approved, 7 exported under an override."""
    blocks = [
        blk(1, "Torque Data", type=BlockType.heading, status=BlockStatus.auto_approved),
        blk(2, "Table 1. Torque values", type=BlockType.caption, status=BlockStatus.auto_approved),
        blk(
            3,
            "| Bolt | N·m |\n| --- | --- |\n| M8 | 35 |",
            type=BlockType.table,
            status=BlockStatus.approved,
        ),
        *[blk(n, f"Queued {n}.", status=BlockStatus.queued) for n in range(4, 9)],
        blk(9, "Tighten the cover plate bolts to 35 N·m.", status=BlockStatus.approved),
        *[blk(n, f"Queued {n}.", status=BlockStatus.queued) for n in range(10, 12)],
    ]
    return synth_inputs(blocks, levels={bid(1): 1}, overrides=[override(5, "Pilot export")])


def test_n3_front_matter_counts_use_the_sidecar_categories_on_dana_s_numbers() -> None:
    (a,) = run(dana_torque()).articles
    assert a.review.counts.model_dump() == {
        "auto_approved": 2,
        "approved": 2,
        "edited": 0,
        "overridden": 7,
    }
    assert "\nreview: { auto_approved: 2, approved: 2, edited: 0, overridden: 7 }\n" in a.text
    assert a.frontmatter.review == a.review.counts


def test_n3_dana_s_old_front_matter_line_fails_z9(tmp_path: Path) -> None:
    """Her zip said `approved: 4` where the review file said approved 2 and auto-approved 2. The
    first version's Z9 compared `approved` with auto_approved + approved + edited, so it passed."""
    res = run(dana_torque())
    (a,) = res.articles
    files = {n: v.encode() for n, v in res.files.items() if isinstance(v, str)}
    new = "review: { auto_approved: 2, approved: 2, edited: 0, overridden: 7 }"
    files[a.path] = files[a.path].replace(
        new.encode(), b"review: { approved: 4, edited: 0, overrides: 7 }"
    )
    write_zip(files, tmp_path / "d.zip")
    msgs = z9(validate_zip(tmp_path / "d.zip"))
    assert any("review.approved 4 != review sidecar 2" in m for m in msgs), msgs
    assert any("review.auto_approved missing != review sidecar 2" in m for m in msgs), msgs
    assert any("review.overrides 7 != review sidecar missing" in m for m in msgs), msgs


def test_n4_every_entry_says_where_its_block_went_and_the_readme_reconciles() -> None:
    res = run(every_status())
    (a,) = res.articles
    assert {e.placement for e in a.review.blocks if e.type == BlockType.figure} == {"figure"}
    assert {e.placement for e in a.review.blocks if e.type != BlockType.figure} == {"paragraph"}
    # 8 blocks: 7 paragraphs (3 auto-approved, 1 approved, 1 edited, 2 overridden) + 1 figure
    readme = res.readme
    assert (
        "In this export: 8 blocks = 7 paragraphs with a marker (3 auto-approved, 1 approved, "
        "1 edited, 2 overridden) + 1 figure block without one (1 auto-approved, 0 approved, "
        "0 edited, 0 overridden)." in readme
    )
    assert "no user accounts" in readme and "`person`" in readme
    assert "blocks = paragraphs with that marker + figure blocks with that status" in readme
    assert "grep -rnE '^<!-- ml: (auto-approved|overridden);' articles/" in readme


def test_n4_a_stale_readme_tally_fails_z8(tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        r = f["README.md"].decode()
        assert "In this export: 5 blocks = 5 paragraphs" in r
        f["README.md"] = r.replace("5 blocks = 5 paragraphs", "5 blocks = 4 paragraphs").encode()

    problems = check(tmp_path, fn)
    assert any(p.code == "Z8" and "In this export" in p.detail for p in problems), problems


def test_n4_the_export_summary_counts_markers_and_figure_blocks(exported_a: Any) -> None:
    """The Export screen's blocks reconcile with the zip: per status, the exported blocks are
    the paragraphs with that marker plus the figure blocks with that status."""
    from manuallabor.export.pipeline import read_state

    st = read_state(exported_a.paths)
    assert st.export is not None
    s = st.export.summary
    assert s.markers is not None
    with zipfile.ZipFile(exported_a.zip) as zf:
        seen = _check_markers_and_sidecars(zf)
        readme = zf.read("README.md").decode()
    r = s.review
    buckets = {
        "auto_approved": r.auto_approved,
        "approved": r.approved,
        "edited": r.edited,
        "overridden": r.overrides,
    }
    for status, n in buckets.items():
        para = getattr(s.markers.paragraphs, status)
        figs = getattr(s.markers.figures, status)
        assert para == seen.get(f"paragraph:{status}", 0), status
        assert figs == seen.get(f"figure:{status}", 0), status
        assert para + figs == n, status
    total_markers = sum(s.markers.paragraphs.model_dump().values())
    assert total_markers == seen["markers"] and seen["figure"] > 0
    figs_total = sum(s.markers.figures.model_dump().values())
    assert f"In this export: {r.blocks} blocks = {total_markers} paragraphs" in readme
    assert f"+ {figs_total} figure blocks without one" in readme


# -- review fixes of 20.11 (fresh Opus reviewer, 2026-10-31) -----------------------------------


def test_rv1_a_paragraph_whose_text_is_the_figure_line_before_it_validates(tmp_path: Path) -> None:
    """Reviewer minor 1: the figure-line skip still let a part equal to the figure line before
    it through unskipped (a 20.10 leftover), so a valid export failed Z9. Every unit starts with
    its marker now; a figure line is always skipped."""
    from manuallabor.contracts.enums import AttachRule

    line = f"![{fid(2)} — Figure 1. A pump.](images/doc/{fid(2)}.png)"
    blocks = [
        blk(1, "One.", status=BlockStatus.approved),
        blk(2, type=BlockType.figure, status=BlockStatus.approved),
        blk(3, line, status=BlockStatus.approved),
    ]
    caption = "Figure 1. A pump."
    res = run(
        synth_inputs(
            blocks,
            figures=[figure_data(2, caption=caption)],
            attach={ART: [att(fid(2), rule=AttachRule.caption_ref, anchor=bid(1))]},
        )
    )
    (a,) = res.articles
    assert "\n\n" + line + "\n\n<!-- ml: approved; block: " + bid(3) + " -->\n" + line in a.text
    files = {n: v.encode() if isinstance(v, str) else b"" for n, v in res.files.items()}
    write_zip(files, tmp_path / "f.zip")
    assert z9(validate_zip(tmp_path / "f.zip")) == []


def test_rv2_a_blank_line_between_marker_and_paragraph_fails(tmp_path: Path) -> None:
    m2 = f"<!-- ml: approved; block: {bid(2)} -->"

    def fn(f: Files) -> None:
        edit_article(f, lambda t: t.replace(m2 + "\n", m2 + "\n\n", 1))

    msgs = z9(check(tmp_path, fn))
    assert any(bid(2) in m and "not directly before its paragraph" in m for m in msgs), msgs


@pytest.mark.parametrize(
    "tail,want",
    [
        (f"\n<!-- ml: approved; block: {bid(2)} -->\n", "after the last paragraph"),
        ("\njunk\n", "after the last paragraph is not a figure line"),
    ],
)
def test_rv2_anything_but_figure_lines_after_the_last_paragraph_fails(
    tmp_path: Path, tail: str, want: str
) -> None:
    msgs = z9(check(tmp_path, lambda f: edit_article(f, lambda t: t + tail)))
    assert any(want in m for m in msgs), msgs


def test_rv2_a_body_without_the_final_newline_fails(tmp_path: Path) -> None:
    msgs = z9(check(tmp_path, lambda f: edit_article(f, lambda t: t.removesuffix("\n"))))
    assert any("not a blank-line separated sequence" in m for m in msgs), msgs


def test_rv7_front_matter_counts_of_another_type_are_reported_with_their_type(
    tmp_path: Path,
) -> None:
    def fn(f: Files) -> None:
        edit_article(
            f,
            lambda t: t.replace("approved: 1, edited: 0", "approved: '1', edited: 0", 1).replace(
                "\nblocks: 5\n", "\nblocks: 5.0\n", 1
            ),
        )

    msgs = z9(check(tmp_path, fn))
    assert any("review.approved '1' != review sidecar 1" in m for m in msgs), msgs
    assert any("front matter blocks 5.0 != review sidecar 5" in m for m in msgs), msgs
