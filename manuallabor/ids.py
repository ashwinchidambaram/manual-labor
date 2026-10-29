"""Deterministic ID formatting, parsing and slugs. Imports nothing from manuallabor."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from pathlib import Path

SLUG_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
PAGE_PATTERN = r"(?:\d{3}|[1-9]\d{3,})"
INDEX_PATTERN = r"(?:\d{2}|[1-9]\d{2,})"

BLOCK_ID_PATTERN = rf"^b-(?P<slug>{SLUG_PATTERN})-p(?P<page>{PAGE_PATTERN})-(?P<n>{INDEX_PATTERN})$"
FIGURE_ID_PATTERN = (
    rf"^FIG-(?P<slug>{SLUG_PATTERN})-p(?P<page>{PAGE_PATTERN})-(?P<n>{INDEX_PATTERN})$"
)
ARTICLE_ID_PATTERN = rf"^(?P<slug>{SLUG_PATTERN})(?:--(?P<topic>{SLUG_PATTERN}))?$"
GROUP_ID_PATTERN = rf"^g-(?P<slug>{SLUG_PATTERN})-(?P<view>[st])(?P<n>\d{{3}})$"
FIGURE_ID_SEARCH_PATTERN = rf"FIG-[a-z0-9-]+-p{PAGE_PATTERN}-{INDEX_PATTERN}(?![0-9])"

BLOCK_ID_RE = re.compile(BLOCK_ID_PATTERN)
FIGURE_ID_RE = re.compile(FIGURE_ID_PATTERN)
FIGURE_ID_SEARCH_RE = re.compile(FIGURE_ID_SEARCH_PATTERN)
ARTICLE_ID_RE = re.compile(ARTICLE_ID_PATTERN)
GROUP_ID_RE = re.compile(GROUP_ID_PATTERN)
SLUG_RE = re.compile(rf"^{SLUG_PATTERN}$")

MAX_SLUG_LEN = 48
UNASSIGNED = "unassigned"
RESERVED_SLUGS = frozenset({UNASSIGNED})


def slugify(text: str, max_len: int = MAX_SLUG_LEN) -> str:
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)  # hyphens, en/em dashes, minus
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if len(s) > max_len:
        cut = s.rfind("-", 0, max_len + 1)
        s = s[:cut] if cut > 0 else s[:max_len]
        s = s.strip("-")
    return s or "doc"


def doc_slug_from_filename(filename: str) -> str:
    return slugify(Path(filename).stem)


def make_unique_slug(base: str, existing: Collection[str]) -> str:
    if base not in existing and base not in RESERVED_SLUGS:
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        cand = base[: MAX_SLUG_LEN - len(suffix)].rstrip("-") + suffix
        if cand not in existing:
            return cand
        n += 1


def _check(slug: str, page: int, n: int) -> None:
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    if not 1 <= page <= 9999:
        raise ValueError(f"page out of range 1..9999: {page}")
    if not 1 <= n <= 999:
        raise ValueError(f"index out of range 1..999: {n}")


def block_id(slug: str, page: int, n: int) -> str:
    _check(slug, page, n)
    return f"b-{slug}-p{page:03d}-{n:02d}"


def figure_id(slug: str, page: int, n: int) -> str:
    _check(slug, page, n)
    return f"FIG-{slug}-p{page:03d}-{n:02d}"


def article_id(slug: str, topic_slug: str | None) -> str:
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    if topic_slug is None:
        if slug in RESERVED_SLUGS:
            raise ValueError(f"slug {slug!r} is reserved and cannot be an article id")
        return slug
    if not SLUG_RE.match(topic_slug):
        raise ValueError(f"invalid topic slug: {topic_slug!r}")
    return f"{slug}--{topic_slug}"


def group_id(slug: str, view: str, n: int) -> str:
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    letter = {"structure": "s", "topic": "t"}.get(str(view))
    if letter is None:
        raise ValueError(f"invalid view: {view!r}")
    if not 0 <= n <= 999:
        raise ValueError(f"group index out of range: {n}")
    return f"g-{slug}-{letter}{n:03d}"


def _parse(rx: re.Pattern[str], s: str, what: str) -> tuple[str, int, int]:
    m = rx.match(s)
    if m is None or s.endswith("\n"):
        raise ValueError(f"not a valid {what} id: {s!r}")
    return m.group("slug"), int(m.group("page")), int(m.group("n"))


def parse_block_id(s: str) -> tuple[str, int, int]:
    return _parse(BLOCK_ID_RE, s, "block")


def parse_figure_id(s: str) -> tuple[str, int, int]:
    return _parse(FIGURE_ID_RE, s, "figure")


def parse_article_id(s: str) -> tuple[str, str | None]:
    m = ARTICLE_ID_RE.match(s)
    if m is None or s.endswith("\n"):
        raise ValueError(f"not a valid article id: {s!r}")
    return m.group("slug"), m.group("topic")


def block_sort_key(s: str) -> tuple[str, int, int]:
    if s.startswith("FIG-"):
        return parse_figure_id(s)
    return parse_block_id(s)
