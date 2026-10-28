from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from manuallabor import ids

# ruff: noqa: E501
SPEC_BODY = """---
figures: [FIG-acme-x200-service-p042-01, FIG-acme-x200-service-p042-02]
---
![FIG-acme-x200-service-p042-01 — Belt tension adjustment points](images/acme-x200-service/FIG-acme-x200-service-p042-01.png)
"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("X200_Service_Manual_rev4", "x200-service-manual-rev4"),
        ("Ünïcödé Manual", "unicode-manual"),
        ("---", "doc"),
        ("clean", "clean"),
    ],
)
def test_i1_slugify(text: str, expected: str) -> None:
    assert ids.slugify(text) == expected


def test_i1_slugify_long() -> None:
    s = ids.slugify("-".join(["alpha"] * 12))
    assert len(s) <= 48
    assert not s.endswith("-")
    assert ids.slugify("x" * 60) == "x" * 48


def test_i1_doc_slug_from_filename() -> None:
    assert ids.doc_slug_from_filename("X200_Service_Manual_rev4.pdf") == "x200-service-manual-rev4"


def test_i2_make_unique_slug() -> None:
    assert ids.make_unique_slug("a", set()) == "a"
    assert ids.make_unique_slug("a", {"a"}) == "a-2"
    assert ids.make_unique_slug("a", {"a", "a-2"}) == "a-3"
    long = "x" * 48
    out = ids.make_unique_slug(long, {long})
    assert out == "x" * 46 + "-2"
    assert len(out) <= 48


def test_i3_block_id() -> None:
    assert ids.block_id("acme-x200-service", 42, 3) == "b-acme-x200-service-p042-03"
    assert ids.block_id("a", 1000, 1) == "b-a-p1000-01"
    assert ids.block_id("a", 1, 100) == "b-a-p001-100"
    for args in [("a", 0, 1), ("a", 1, 0), ("Bad", 1, 1), ("a", 10000, 1), ("a", 1, 1000)]:
        with pytest.raises(ValueError):
            ids.block_id(*args)


def test_i4_figure_id() -> None:
    assert ids.figure_id("acme-x200-service", 42, 1) == "FIG-acme-x200-service-p042-01"
    with pytest.raises(ValueError):
        ids.figure_id("Bad", 1, 1)


slugs = st.from_regex(ids.SLUG_RE, fullmatch=True).filter(lambda s: len(s) <= 48)


@given(slug=slugs, page=st.integers(1, 9999), n=st.integers(1, 999))
def test_i5_roundtrip(slug: str, page: int, n: int) -> None:
    assert ids.parse_block_id(ids.block_id(slug, page, n)) == (slug, page, n)
    assert ids.parse_figure_id(ids.figure_id(slug, page, n)) == (slug, page, n)


@pytest.mark.parametrize("slug", ["x-p001", "a-p042-03"])
def test_i5_tricky_slugs(slug: str) -> None:
    assert ids.parse_block_id(ids.block_id(slug, 7, 2)) == (slug, 7, 2)
    assert ids.parse_figure_id(ids.figure_id(slug, 7, 2)) == (slug, 7, 2)


@pytest.mark.parametrize(
    "bad",
    [
        "B-x-p001-01",
        "FIG-Acme-p001-01",
        "b-x-p42-03",
        "b-x-p042-3",
        "b-x-p042-03 ",
        "b--p001-01",
        "b-x--y-p001-01",
        "b-x-p042-03\n",
    ],
)
def test_i6_rejected(bad: str) -> None:
    assert not ids.BLOCK_ID_RE.match(bad) or bad.endswith("\n")
    assert not ids.FIGURE_ID_RE.match(bad)
    with pytest.raises(ValueError):
        ids.parse_block_id(bad)


def test_i7_search_re() -> None:
    found = ids.FIGURE_ID_SEARCH_RE.findall(SPEC_BODY)
    assert found == [
        "FIG-acme-x200-service-p042-01",
        "FIG-acme-x200-service-p042-02",
        "FIG-acme-x200-service-p042-01",
        "FIG-acme-x200-service-p042-01",
    ]
    assert re.search(r"FIG-[a-z0-9-]+-p\d{3}-\d{2}", "FIG-a-p001-01")


def test_i8_article_ids() -> None:
    assert ids.article_id("s", None) == "s"
    full = ids.article_id("acme-x200-service", "belt-tension")
    assert full == "acme-x200-service--belt-tension"
    assert ids.parse_article_id("s") == ("s", None)
    assert ids.parse_article_id(full) == ("acme-x200-service", "belt-tension")
    with pytest.raises(ValueError):
        ids.article_id("s", "a--b")
    with pytest.raises(ValueError):
        ids.parse_article_id("a--b--c")


def test_i9_group_ids() -> None:
    assert ids.group_id("clean", "structure", 1) == "g-clean-s001"
    assert ids.group_id("clean", "topic", 0) == "g-clean-t000"
    m = ids.GROUP_ID_RE.match("g-clean-s001")
    assert m and m.group("slug") == "clean" and m.group("view") == "s" and m.group("n") == "001"
    assert ids.GROUP_ID_RE.match("g-clean-t000")


def test_sort_key_numeric() -> None:
    a, b = ids.block_id("x", 9, 1), ids.block_id("x", 10, 1)
    assert sorted([b, a], key=ids.block_sort_key) == [a, b]
