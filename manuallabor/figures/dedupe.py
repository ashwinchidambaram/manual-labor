"""Perceptual hashing and project-wide dedupe (design section 6). Pure."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import imagehash
from PIL import Image, ImageStat

from manuallabor import ids
from manuallabor.contracts.enums import Extraction
from manuallabor.figures.encode import composite_on_white
from manuallabor.figures.types import (
    ASPECT_TOL,
    BLANK_STD_MIN,
    NEAR_DUP_MAX_DIST,
    DedupeEntry,
)

_RANK = {Extraction.native: 0, Extraction.vector: 1, Extraction.crop: 2}


def phash_hex(img: Image.Image) -> str:
    return str(imagehash.phash(composite_on_white(img).convert("L")))


def is_blank(img: Image.Image) -> bool:
    small = composite_on_white(img).convert("L").resize((64, 64), Image.Resampling.LANCZOS)
    return float(ImageStat.Stat(small).stddev[0]) < BLANK_STD_MIN


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


@dataclass(frozen=True)
class DedupeItem:
    figure_id: str
    source_doc: str
    method: Extraction
    width: int
    height: int
    png_sha256: str
    svg_sha256: str | None
    phash: str
    blank: bool


def _key(it: DedupeItem) -> tuple[int, int, str, int, int]:
    slug, page, n = ids.parse_figure_id(it.figure_id)
    return (_RANK[it.method], -(it.width * it.height), slug, page, n)


def _compatible(item: DedupeItem, canon: DedupeItem) -> bool:
    return item.method != Extraction.vector or canon.method == Extraction.vector


def _aspect_ok(a: DedupeItem, b: DedupeItem) -> bool:
    ra, rb = a.width / a.height, b.width / b.height
    return abs(ra - rb) <= ASPECT_TOL * max(ra, rb)


def dedupe(items: Sequence[DedupeItem]) -> list[DedupeEntry]:
    """Entries sorted by figure id; every duplicate points directly at a canonical."""
    canon: list[DedupeItem] = []
    by_id: dict[str, DedupeEntry] = {}
    for it in sorted(items, key=_key):
        match: DedupeEntry | None = None
        for c in canon:
            if not _compatible(it, c) or c.png_sha256 != it.png_sha256:
                continue
            if it.method == Extraction.vector and c.svg_sha256 != it.svg_sha256:
                continue
            match = DedupeEntry(
                figure_id=it.figure_id,
                source_doc=it.source_doc,
                duplicate_of=c.figure_id,
                kind="exact",
                distance=0,
            )
            break
        if match is None and not it.blank:
            best: tuple[int, DedupeItem] | None = None
            for c in canon:
                if c.blank or not _compatible(it, c) or not _aspect_ok(it, c):
                    continue
                d = hamming(it.phash, c.phash)
                if d <= NEAR_DUP_MAX_DIST and (best is None or d < best[0]):
                    best = (d, c)
            if best is not None:
                match = DedupeEntry(
                    figure_id=it.figure_id,
                    source_doc=it.source_doc,
                    duplicate_of=best[1].figure_id,
                    kind="near",
                    distance=best[0],
                )
        if match is None:
            canon.append(it)
            match = DedupeEntry(figure_id=it.figure_id, source_doc=it.source_doc)
        by_id[it.figure_id] = match
    return [by_id[k] for k in sorted(by_id, key=ids.block_sort_key)]
