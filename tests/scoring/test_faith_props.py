"""Test 15: property tests of the faithfulness check."""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from manuallabor.contracts.enums import BlockType
from manuallabor.scoring.faithfulness import canonicalize, check_faithfulness

HF = ["Acme X200 Service Manual", "Page 3", "Page 4"]  # footers recorded on pages 3, 4
SETTINGS = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])

WEIRD = "abcXYZ019 \n\t-–·±|•*¢«o.,;:()­  ﬁﬂ́éÅ"
any_text = st.text(alphabet=st.sampled_from(list(WEIRD)), max_size=120)

word = st.text(alphabet=st.sampled_from(list("abcdefghijkmnprstuvwyz")), min_size=1, max_size=8)
numword = st.from_regex(r"[0-9]{1,3}(\.[0-9]{1,2})?", fullmatch=True)
token = st.one_of(
    word, word, word, numword, st.sampled_from(["N·m", "±0.05", "M8", "(see", "it)."])
)


@st.composite
def structured(draw: st.DrawFn) -> tuple[list[str], list[str | None], list[bool]]:
    """Lines of tokens; per line an optional bullet glyph and whether it ends in a hyphen
    break (`word-` + next line starting with a letter)."""
    n = draw(st.integers(min_value=1, max_value=6))
    lines, bullets, hyph = [], [], []
    for i in range(n):
        toks = draw(st.lists(token, min_size=1, max_size=6))
        bullets.append(draw(st.sampled_from([None, None, "•", "-", "*"])))
        h = i < n - 1 and draw(st.booleans())
        if h:
            toks[-1] = draw(word) + "-"
        lines.append(" ".join(toks))
        hyph.append(h)
    # the line after a hyphen break must start with a letter and have no bullet
    for i in range(1, n):
        if hyph[i - 1]:
            bullets[i] = None
            lines[i] = draw(word) + " " + lines[i]
    return lines, bullets, hyph


def render_raw(lines: list[str], bullets: list[str | None]) -> str:
    return "\n".join((f"{b} " if b else "") + ln for ln, b in zip(lines, bullets, strict=True))


@given(any_text)
@SETTINGS
def test_raw_to_raw_always_passes(s: str) -> None:
    for bt in (BlockType.paragraph, BlockType.list):
        r = check_faithfulness(s, s, hf_strings=HF, block_type=bt)
        assert r.passed, [(v.kind, v.raw, v.clean) for v in r.violations]


@given(any_text)
@SETTINGS
def test_canonicalize_idempotent(s: str) -> None:
    once = canonicalize(s, hf_strings=HF).mt.text
    assert canonicalize(once, hf_strings=HF).mt.text == once


@given(structured(), st.data())
@SETTINGS
def test_allowed_edit_compositions_pass(parts, data: st.DataObject) -> None:  # type: ignore[no-untyped-def]
    lines, bullets, hyph = parts
    raw_lines: list[str] = []
    clean_lines: list[str] = []
    for i, ln in enumerate(lines):
        b = bullets[i]
        raw_body, clean_body = ln, ln
        # AE5 on the raw side: ligature / NBSP / soft hyphen
        if "fi" in raw_body and data.draw(st.booleans()):
            raw_body = raw_body.replace("fi", "ﬁ")
        if " " in raw_body and data.draw(st.booleans()):
            raw_body = raw_body.replace(" ", " ", 1)
        if (
            data.draw(st.booleans())
            and len(raw_body) > 2
            and raw_body[1].isalpha()
            and raw_body[0].isalpha()
        ):
            raw_body = raw_body[:1] + "­" + raw_body[1:]
        # AE1 inside the line
        clean_body = clean_body.replace(" ", data.draw(st.sampled_from([" ", "  ", " \n "])))
        raw_lines.append((f"{b} " if b else "") + raw_body)
        cb = data.draw(st.sampled_from(["•", "-", "*"])) if b else None  # AE4
        clean_lines.append((f"{cb} " if cb else "") + clean_body)
    raw = "\n".join(raw_lines)
    if data.draw(st.booleans()):
        raw = raw + "\nPage 7"  # AE3: clean drops the footer line (block on page 7)
    # join lines: AE2 drop / keep for hyphen breaks; AE1 newline or space otherwise,
    # keeping a newline before every bullet line
    clean = clean_lines[0]
    for i in range(1, len(clean_lines)):
        if hyph[i - 1]:
            mode = data.draw(st.sampled_from(["drop", "keep_nl", "keep_join"]))
            if mode == "drop":
                clean = clean[:-1] + clean_lines[i]
            elif mode == "keep_nl":
                clean = clean + "\n" + clean_lines[i]
            else:
                clean = clean + clean_lines[i]
        elif bullets[i]:
            clean = clean + "\n" + clean_lines[i]
        else:
            clean = clean + data.draw(st.sampled_from([" ", "\n", "\n\n"])) + clean_lines[i]
    r = check_faithfulness(raw, clean, hf_strings=HF, page=7)
    assert r.passed, (raw, clean, [(v.kind.value, v.raw, v.clean) for v in r.violations])


@given(structured(), st.data())
@SETTINGS
def test_one_inserted_char_fails(parts, data: st.DataObject) -> None:  # type: ignore[no-untyped-def]
    lines, bullets, _ = parts
    raw = render_raw(lines, bullets)
    pos = data.draw(st.integers(min_value=0, max_value=len(raw)))
    ch = data.draw(st.sampled_from(list("abqXZ0179")))
    clean = raw[:pos] + ch + raw[pos:]
    r = check_faithfulness(raw, clean, hf_strings=HF, page=7)
    assert not r.passed, (raw, clean)


@given(any_text, any_text)
@SETTINGS
def test_spans_in_bounds(raw: str, clean: str) -> None:
    assume(raw or clean)
    r = check_faithfulness(raw, clean, hf_strings=HF, page=7)
    for v in r.violations:
        if v.raw_start is not None:
            assert v.raw_end is not None and 0 <= v.raw_start <= v.raw_end <= len(raw)
            assert raw[v.raw_start : v.raw_end] == v.raw
        if v.clean_start is not None:
            assert v.clean_end is not None and 0 <= v.clean_start <= v.clean_end <= len(clean)
            assert clean[v.clean_start : v.clean_end] == v.clean
    for op in r.diff:
        assert raw[op.raw_start : op.raw_end] == op.raw
        assert clean[op.clean_start : op.clean_end] == op.clean
