"""The re-check notes a reviewer reads on the Agent screen are plain words (design 09 section 14,
second first-use report C5): no code names ("attester", "symbol soup", "token"), no reader keys
("docling", "pymupdf"), and a failed check says what is wrong in a reviewer's words."""

from __future__ import annotations

import re

from manuallabor.agent.recheck import (
    attested_faithfulness,
    build_table_data,
    check_garbage,
    check_parser_agreement,
    check_token_whitespace,
    numeric_attested,
)
from tests.conftest import ctx, make_block

JARGON = re.compile(
    r"attest|symbol soup|token|garbage|pymupdf|docling|ocr_alt|§|normali[sz]ation|strict", re.I
)


def plain(detail: str | None) -> str:
    assert detail, "a note is expected"
    assert not JARGON.search(detail), detail
    return detail


def test_a_changed_number_no_other_reading_shows_is_said_plainly() -> None:
    raw = "Allow the unit to cool before removing the filter."
    text = raw + " The 2.5 L refill line might belong to the next column."
    r = numeric_attested(raw, {"pymupdf": raw, "docling": raw}, "pymupdf", text, None, True)
    assert not r.passed
    d = plain(r.detail)
    assert "nothing → 2.5" in d and "no other reading of the page shows it" in d
    assert "2 needed" in d


def test_a_look_alike_names_the_reading_that_shows_it() -> None:
    raw = "Torque 3S N·m"
    r = numeric_attested(raw, {"pymupdf": raw, "docling": "Torque 35 N·m"}, "pymupdf",
                         "Torque 35 N·m", None, True)  # fmt: skip
    assert r.passed
    assert plain(r.detail) == "3S → 35: shown by the layout parser"


def test_unchanged_numbers() -> None:
    r = numeric_attested("A 5 B", {"pymupdf": "A 5 B"}, "pymupdf", "A 5 B", None, True)
    assert plain(r.detail) == "no number changed"


def test_faithfulness_failure_says_what_is_not_in_the_manual() -> None:
    raw = "Allow the unit to cool."
    b = make_block(raw, texts={"pymupdf": raw, "docling": raw})
    r = attested_faithfulness(b, ctx(), [], raw + " The 2.5 L refill line might belong here.")
    assert not r.passed
    d = plain(r.detail)
    assert d.startswith("not in the manual: ") and "added text" in d


def test_faithfulness_passes_name_the_allowed_edits_and_the_reading() -> None:
    b = make_block("Check the\ndrive belt.", texts={"pymupdf": "Check the\ndrive belt."})
    assert plain(attested_faithfulness(b, ctx(), [], "Check the drive belt.").detail) == (
        "only the allowed clean-up edits"
    )
    raw = "Wipe witha clean cloth"
    b2 = make_block(raw, texts={"pymupdf": raw, "ocr": "Wipe with a clean cloth"})
    r = attested_faithfulness(b2, ctx(), [], "Wipe with a clean cloth")
    assert r.passed and "shown by OCR" in plain(r.detail)


def test_split_words_garbled_text_and_agreement_in_plain_words() -> None:
    raw = "Use part 12/4 here"
    r = check_token_whitespace(raw, "Use part 12 / 4 here", {"pymupdf": raw}, "pymupdf")
    assert not r.passed
    assert plain(r.detail) == "new words no other reading shows: /, 12, 4"
    g = check_garbage("Check the belt", "Check the belt")
    assert g.passed and plain(g.detail) == "no more garbled characters than before"
    bad = check_garbage("Check the belt", "Ch#@ek t%%he b~~elt")
    assert not bad.passed and plain(bad.detail).startswith("more garbled characters than before")
    a = check_parser_agreement("Check the belt", "Check the belt", {"pymupdf": "Check the belt",
                               "docling": "Check the belt"}, "pymupdf")  # fmt: skip
    assert a.passed and plain(a.detail) == "as close to the other readings as before (1 → 1)"


def test_table_and_figure_notes_in_plain_words() -> None:
    from tests.agent.test_review_fixes_c import LA_CUR, LA_FIXED, LA_OTHER, LA_RAW, pos, tb

    b = tb(LA_RAW, build_table_data(LA_CUR, 1), docling=LA_OTHER)
    r = pos(b, LA_FIXED, {"docling": build_table_data(LA_FIXED, 1)})
    assert (
        r.passed and "row " in plain(r.detail) and "shown by the layout parser" in plain(r.detail)
    )
    lone = pos(b, LA_FIXED)
    assert not lone.passed and "no other reading of the table shows it there" in plain(lone.detail)


def test_every_required_check_has_a_sentence_on_the_agent_screen() -> None:
    """The Agent card's sentences (frontend/src/agent/recheck.ts RECHECK_WORDS) cover every check
    a proposal must carry, so a check added here cannot reach the screen by its code name."""
    from pathlib import Path

    from manuallabor.contracts.proposal import REQUIRED_CHECKS

    ts = (Path(__file__).parents[2] / "frontend/src/agent/recheck.ts").read_text(encoding="utf-8")
    body = ts[ts.index("RECHECK_WORDS") : ts.index("export function recheckSentence")]
    keys = set(re.findall(r"^\s+(\w+): \{", body, re.M))
    required = {c for checks in REQUIRED_CHECKS.values() for c in checks}
    assert required <= keys, sorted(required - keys)
