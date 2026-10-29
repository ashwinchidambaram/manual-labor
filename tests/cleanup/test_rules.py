"""Tests 1-8, 10, 39: the deterministic passes, one by one and composed."""

from __future__ import annotations

import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from manuallabor.cleanup.lexicon import Lexicon, doc_lexicon
from manuallabor.cleanup.pipeline import clean_document
from manuallabor.cleanup.rules import (
    PassCtx,
    bullets,
    compose,
    crlf,
    dehyphenate_ex,
    join_lines,
    plan_passes,
    strip_hf,
    unicode_pass,
    whitespace,
)
from manuallabor.contracts.enums import BlockType
from manuallabor.scoring.faithfulness import check_faithfulness, glyph_identity, hf_tables
from manuallabor.scoring.numeric import FAITH_NUM_RE
from tests.cleanup.conftest import det, doc_of, mk

P = BlockType.paragraph
L = BlockType.list


def ctx(type: BlockType = P, **kw: Any) -> PassCtx:
    return PassCtx(block_type=type, **kw)


def faithful(
    raw: str,
    clean: str,
    type: BlockType = P,
    hf: Sequence[str] = (),
    page: int | None = None,
    hf_pages: Mapping[str, Sequence[int]] | None = None,
) -> bool:
    r = check_faithfulness(raw, clean, block_type=type, hf_strings=hf, page=page, hf_pages=hf_pages)
    return r.passed


# -- 1 crlf ---------------------------------------------------------------------------------


def test_01_crlf() -> None:
    c = ctx()
    assert crlf("a\r\nb", c) == "a\nb"  # perfect
    assert crlf("a\rb\r\n\rc", c) == "a\nb\n\nc"  # degraded: lone CRs mixed in
    assert crlf("", c) == "" and crlf("no breaks", c) == "no breaks"  # edge
    for s in ("a\r\nb", "a\rb\r\n\rc", "x\r"):
        once = crlf(s, c)
        assert crlf(once, c) == once
        assert faithful(s, once)


# -- 2 unicode ------------------------------------------------------------------------------


def test_02_unicode() -> None:
    c = ctx()
    assert unicode_pass("ﬁlter ﬂow", c) == "filter flow"
    assert unicode_pass("lubri­cation", c) == "lubrication"
    assert unicode_pass("a b c d", c) == "a b c d"
    assert unicode_pass("Café", c) == "Café"  # NFD -> NFC
    for keep in ("mm²", "½ turn", "5 µm", "35 N·m", "±0.05"):  # never NFKC
        assert unicode_pass(keep, c) == keep
    assert unicode_pass("", c) == ""
    for s in ("ﬁlter ﬂow", "re­enter 10 mm"):
        assert faithful(s, unicode_pass(s, c))
        assert unicode_pass(unicode_pass(s, c), c) == unicode_pass(s, c)


# -- 3 strip_hf -----------------------------------------------------------------------------


def test_03_strip_hf() -> None:
    hdr = "Acme X200 Service Manual"
    pages = {hdr: [1, 2], "Page 3": [3], "Page 4": [4]}
    c7 = ctx(hf=hf_tables([], pages), page=7)
    c8 = ctx(hf=hf_tables([], pages), page=8)
    raw = f"{hdr}\nCheck the belt.\nPage 7"
    out = strip_hf(raw, c7)
    assert out == "Check the belt."
    assert faithful(raw, out, hf_pages=pages, page=7)
    assert strip_hf("Check the belt.\nPage 7", c8) == "Check the belt.\nPage 7"  # other page
    # Page {n} of 60 template
    tpl = {"Page 1 of 60": [1], "Page 2 of 60": [2]}
    c35 = ctx(hf=hf_tables([], tpl), page=35)
    assert strip_hf("Torque it.\nPage 35 of 60", c35) == "Torque it."
    assert strip_hf("Torque it.\nPage 35 of 35", c35) == "Torque it.\nPage 35 of 35"
    assert strip_hf("Torque it.\nPage 34 of 60", c35) == "Torque it.\nPage 34 of 60"
    # a numeric body line with another header's template stays
    tm = {"TM 5-3895-332-12": [1, 2, 3]}
    ctm = ctx(hf=hf_tables([], tm), page=2)
    assert (
        strip_hf("See TM 9-2320-280-20\nfor details.", ctm) == "See TM 9-2320-280-20\nfor details."
    )
    assert strip_hf("TM 9-2320-280-20", ctm) == "TM 9-2320-280-20"
    assert strip_hf("TM 5-3895-332-12\nbody", ctm) == "body"
    # a bare number line is never a header; a recorded string inside a sentence stays
    cnum = ctx(hf=hf_tables(["12", hdr]), page=1)
    assert strip_hf("12\nbody", cnum) == "12\nbody"
    s = f"Read the {hdr} first."
    assert strip_hf(s, cnum) == s
    assert strip_hf("", cnum) == ""
    # the document title as a heading equals the running header: never emptied
    hc = PassCtx(block_type=BlockType.heading, hf=hf_tables([], {hdr: [1, 2]}), page=1)
    assert strip_hf(hdr, hc) == hdr
    assert faithful(hdr, hdr, BlockType.heading, hf_pages={hdr: [1, 2]}, page=1)
    assert strip_hf(f"{hdr}\n2 Removal", hc) == "2 Removal"


HF_EDGE_PAGES = {"Acme X200 Service Manual": [1, 2, 3], "Page 3": [3]}
INTERIOR_HF = [
    # (raw, the header/footer-stripped version that must be rejected)
    (
        "Refer to the\nAcme X200 Service Manual\nbefore you start.",
        "Refer to the\nbefore you start.",
    ),
    ("Torque table on\nPage 3\napplies to M8.", "Torque table on\napplies to M8."),
    ("Page 3", ""),  # a paragraph that is only the footer string: never emptied
    ("Acme X200 Service Manual\nPage 3", ""),  # two edge lines, nothing else
]


@pytest.mark.parametrize(("raw", "stripped"), INTERIOR_HF)
def test_03_hf_never_removed_from_the_interior_or_emptying(raw: str, stripped: str) -> None:
    c = ctx(hf=hf_tables([], HF_EDGE_PAGES), page=3)
    assert strip_hf(raw, c) == raw
    for t in (P, L, BlockType.other, BlockType.heading):
        out = compose(raw, plan_passes(t, False), ctx(t, hf=c.hf, page=3)).text
        assert " ".join(out.split()) == " ".join(raw.split()), (t, out)
        assert faithful(raw, out, t, hf_pages=HF_EDGE_PAGES, page=3)
    r = check_faithfulness(raw, stripped, hf_pages=HF_EDGE_PAGES, page=3)
    assert not r.passed
    assert "deletion" in {v.kind.value for v in r.violations}


def test_03_hf_leading_and_trailing_remnants_still_removed() -> None:
    c = ctx(hf=hf_tables([], HF_EDGE_PAGES), page=3)
    for raw, want in (
        ("Acme X200 Service Manual\nCheck the belt.", "Check the belt."),
        ("Check the belt.\nPage 3", "Check the belt."),
        ("Acme X200 Service Manual\nCheck the belt.\nPage 3", "Check the belt."),
        ("\nAcme X200 Service Manual\n\nCheck the belt.\n", "\n\nCheck the belt.\n"),
    ):
        assert strip_hf(raw, c) == want
        assert faithful(raw, want.strip(), hf_pages=HF_EDGE_PAGES, page=3)
        assert faithful(raw, raw, hf_pages=HF_EDGE_PAGES, page=3)  # keeping it is allowed
    # a two-line remnant run at an edge goes; the same strings with body on both sides stay
    raw = "Check the belt.\nAcme X200 Service Manual\nPage 3"
    assert strip_hf(raw, c) == "Check the belt."
    assert faithful(raw, "Check the belt.", hf_pages=HF_EDGE_PAGES, page=3)
    raw = "Check the\nAcme X200 Service Manual\nPage 3\nbelt."
    assert strip_hf(raw, c) == raw
    assert not faithful(raw, "Check the belt.", hf_pages=HF_EDGE_PAGES, page=3)
    assert not faithful(raw, "Check the\nPage 3\nbelt.", hf_pages=HF_EDGE_PAGES, page=3)


# -- 4 bullets ------------------------------------------------------------------------------


def test_04_bullets() -> None:
    lst = ctx(L)
    raw = "¢ one\n« two\no three\n+ four\n- five\n* six\n– seven"
    out = bullets(raw, lst)
    assert out == "\n".join(
        f"• {w}" for w in ["one", "two", "three", "four", "five", "six", "seven"]
    )
    assert faithful(raw, out, L)
    par = ctx(P)
    for keep in ("* note this", "– 40 °C is the limit", "+5 V supply", "o-ring seal"):
        assert bullets(keep, par) == keep
    assert bullets("● x\n▪ y", par) == "• x\n• y"
    assert faithful("● x\n▪ y", "• x\n• y")
    assert bullets("+5 V\no-ring", lst) == "+5 V\no-ring"  # no space after the glyph
    assert bullets("•", lst) == "•" and bullets("", lst) == ""


# -- 5 dehyphenate --------------------------------------------------------------------------


def _dh(text: str, lexicon: Lexicon | None = None) -> tuple[str, list[str]]:
    return dehyphenate_ex(text, ctx(lexicon=lexicon or Lexicon()))


def test_05_dehyphenate() -> None:
    assert _dh("adjust-\nment") == ("adjustment", ["drop_default:adjustment"])
    lex = doc_lexicon(["A self-contained unit.", "The assembly is heavy."])
    assert _dh("self-\ncontained", lex) == ("self-contained", ["keep_lexicon:self-contained"])
    assert _dh("assem-\nbly", lex) == ("assembly", ["drop_lexicon:assembly"])
    assert _dh("Anti-\nLock") == ("Anti-Lock", ["keep_upper:Anti-Lock"])
    out, d = _dh("re-\nenter")
    assert out == "reenter" and d == ["drop_ambiguous:reenter"]
    # degraded: spaces around the break; edge: digits never dehyphenated, a chain resolves fully
    assert _dh("lubri-  \n  cation")[0] == "lubrication"
    for keep in ("M8-\nbolt", "4471A-\nB", "10-\n20"):
        assert _dh(keep)[0] == keep
    assert _dh("a-\nb-\nc")[0] == "abc"
    for s in ("adjust-\nment", "Anti-\nLock", "re-\nenter", "a-\nb-\nc"):
        assert faithful(s, _dh(s)[0])


def test_05_lexicon_ignores_its_own_break() -> None:
    lex = doc_lexicon(["The assem-\nbly.", "self-\ncontained"])
    assert not lex.has_word("assembly") and not lex.has_compound("self", "contained")


# -- 6 part numbers and tolerances ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("Fit P/N 4471-\nA now.", "Fit P/N 4471-A now."),
        ("Fit P/N 4471-A now.", "Fit P/N 4471-A now."),
        ("Gap 0.25 mm ±0.05 max.", "Gap 0.25 mm ±0.05 max."),
        ("±0.05", "±0.05"),
        ("Torque to 35 N·m.", "Torque to 35 N·m."),
        ("Use 10 to 60 N·m.", "Use 10 to 60 N·m."),
        ("Range 10-\n20 mm.", "Range 10-20 mm."),
        ("Remove the items -\nbolts first.", "Remove the items - bolts first."),
        ("Fit an M-\n8 bolt.", "Fit an M-8 bolt."),
    ],
)
@pytest.mark.parametrize("type", [P, L, BlockType.other, BlockType.heading])
def test_06_numbers_untouched(raw: str, want: str, type: BlockType) -> None:
    out = det(raw, type)
    if type == P:
        assert out == want
    if type == L:  # a list item with a continuation line
        assert det("• " + raw, L) == "• " + want
    assert Counter(FAITH_NUM_RE.findall(out)) == Counter(FAITH_NUM_RE.findall(raw))
    assert faithful(raw, out, type)


# -- 7 join_lines ---------------------------------------------------------------------------


def test_07_join_lines() -> None:
    assert (
        join_lines("Check the\nbelt and\n  the pulley.", ctx(P)) == "Check the belt and the pulley."
    )
    raw = "Steps:\n• one\n1) two\na. three\ncontinued"
    assert join_lines(raw, ctx(P)) == "Steps:\n• one\n1) two\na. three continued"
    assert join_lines("• Torque wrench,\n10 to 60 N·m\n• Gauge", ctx(L)) == (
        "• Torque wrench, 10 to 60 N·m\n• Gauge"
    )
    docx = "Torque wrench, 10 to 60 N·m\nFeeler gauge set\nClean rags"
    assert join_lines(docx, ctx(L)) == docx
    assert join_lines("2.1 Removing the\nidler pulley", ctx(BlockType.heading)) == (
        "2.1 Removing the idler pulley"
    )
    fused = "Figure 3. Cover plate\nand bracket layout. The bracket is shown"
    out = join_lines(fused, ctx(BlockType.caption))
    assert out == "Figure 3. Cover plate and bracket layout. The bracket is shown"
    assert re.sub(r"\s", "", out) == re.sub(r"\s", "", fused)
    assert join_lines("", ctx(P)) == "" and join_lines("\n\n", ctx(P)) == "\n\n"
    for t, s in ((P, raw), (L, docx), (BlockType.caption, fused)):
        assert faithful(s, join_lines(s, ctx(t)), t)


# -- 8 whitespace ---------------------------------------------------------------------------


def test_08_whitespace() -> None:
    c = ctx()
    assert whitespace("a \t b", c) == "a b"
    assert whitespace("  a  \n\n\n  b  \n", c) == "a\nb"
    assert whitespace(" \n \t ", c) == ""
    assert whitespace("a\n \nb", c) == "a\nb"
    for s in ("a \t b", "  a  \n\n\n  b  \n"):
        assert faithful(s, whitespace(s, c))
        assert whitespace(whitespace(s, c), c) == whitespace(s, c)


def test_caption_and_heading_get_whitespace_only() -> None:
    for t in (BlockType.caption, BlockType.heading):
        names = [p.name for p in plan_passes(t, False)]
        assert "dehyphenate" not in names and "bullets" not in names
    assert [p.name for p in plan_passes(BlockType.caption, False)] == [
        "crlf",
        "join_lines",
        "whitespace",
    ]
    assert det("Figure 2. Lubri-\ncation ﬁ  points", BlockType.caption) == (
        "Figure 2. Lubri- cation ﬁ points"
    )


# -- 10 property test ----------------------------------------------------------------------

HDR = "Acme X200 Service Manual"
WORDS = st.sampled_from(
    [
        "belt", "pulley", "assembly", "re", "self", "Lock", "M8", "4471-A", "10", "-40",
        "+5", "±0.05", "0.25", "N·m", "mm²", "ﬁlter", "a", "the", "(see", "Figure", "3).",
        "lubri", "cation", "*", "–", "o", "x", "1)", "a.", "10-", "-",
    ]
)  # fmt: skip
SEPS = st.sampled_from([" ", " ", "  ", "\t", "\n", "\r\n", "-\n", " ", "­", "\n\n"])


@st.composite
def texts(draw: st.DrawFn) -> str:
    n = draw(st.integers(1, 14))
    parts: list[str] = []
    for i in range(n):
        if i:
            parts.append(draw(SEPS))
        parts.append(draw(WORDS))
    s = "".join(parts)
    lines = s.split("\n")
    if draw(st.booleans()):
        lines.insert(draw(st.integers(0, len(lines))), HDR)
    if draw(st.booleans()):
        lines.insert(0, draw(st.sampled_from(["• ", "¢ ", "- ", "● "])) + lines.pop(0))
    return "\n".join(lines)


def _words(s: str, type: BlockType) -> list[str]:
    """\\w runs, with an AE2 hyphen break (and a kept compound hyphen) not separating them and
    line-start bullet glyphs (AE4) dropped."""
    s = glyph_identity(s).text
    glyphs = "•·◦▪‣●*–-" + ("¢+o«" if type == L else "")
    s = re.sub(rf"(?m)^[ \t]*[{re.escape(glyphs)}](?=\s|$)", "", s)
    s = re.sub(r"(?<=[^\W\d_])-\s*(?=[^\W\d_])", "", s)
    return re.findall(r"\w+", s)


@settings(
    max_examples=300,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(texts(), st.sampled_from([P, L, BlockType.other, BlockType.heading, BlockType.caption]))
def test_10_property(raw: str, type: BlockType) -> None:
    hf = [HDR]
    out = det(raw, type, hf=hf)
    assert check_faithfulness(raw, out, block_type=type, hf_strings=hf, page=1).passed, (
        raw,
        out,
    )
    assert det(out, type, hf=hf) == out  # idempotent
    # whitespace between two word chars is never deleted (word sequence unchanged once the
    # leading/trailing header remnants are gone; an interior header line is body text and a
    # block that is only header lines is never emptied)
    body = raw
    if type != BlockType.caption:  # captions are whitespace-only: the header stays inline
        lines = raw.replace("\r", "\n").split("\n")
        nb = [k for k, ln in enumerate(lines) if ln.strip()]
        drop: set[int] = set()
        for order in (nb, nb[::-1]):
            for k in order:
                if lines[k].strip() != HDR:
                    break
                drop.add(k)
        if len(drop) < len(nb):
            body = "\n".join(ln for k, ln in enumerate(lines) if k not in drop)
    assert _words(out, type) == _words(body, type)
    # an interior header line is never deleted
    lines = [ln.strip() for ln in raw.replace("\r", "\n").split("\n")]
    nb = [k for k, ln in enumerate(lines) if ln]
    interior = [k for k in nb[1:-1] if lines[k] == HDR]
    if type != BlockType.caption and any(
        any(lines[j] != HDR for j in nb if j < k) and any(lines[j] != HDR for j in nb if j > k)
        for k in interior
    ):
        assert HDR in out, (raw, out)


# -- 39 performance ------------------------------------------------------------------------


def test_39_thousand_blocks_under_five_seconds() -> None:
    para = (
        "Replace the drive belt if it shows any sign of deformation. Wear protective gloves\n"
        "when handling the pressure valve. Any assem-\nbly work on the cover plate must be\n"
        "done with the unit switched off. Torque to 35 N·m."
    )
    blocks = [mk(1 + i // 50, 1 + i % 50, para) for i in range(1000)]
    doc = doc_of(blocks)
    t0 = time.perf_counter()
    entries, _ = clean_document(doc, blocks, [], {b.id for b in blocks}, mode="off")
    elapsed = time.perf_counter() - t0
    print(f"\n1000 blocks cleaned + checked in {elapsed:.2f} s")
    assert len(entries) == 1000 and all(e.faith_passed for e in entries)
    assert elapsed < 5.0


def test_compose_records_applied_passes() -> None:
    passes = plan_passes(P, False)
    r = compose("Check the\nbelt.", passes, ctx())
    assert r.text == "Check the belt." and r.applied == ["join_lines"]
