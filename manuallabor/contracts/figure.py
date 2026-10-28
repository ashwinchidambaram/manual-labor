"""Figure sidecar record (SPEC 6.3)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator, model_validator

from manuallabor import ids
from manuallabor.contracts._base import (
    ArticleId,
    BBox,
    ContractModel,
    DocSlug,
    FigureId,
    PHash,
    Unit,
)
from manuallabor.contracts.enums import AttachRule, BlockStatus, Extraction

_DEDUP_RE = re.compile(
    rf"^\.\./(?P<dir>{ids.SLUG_PATTERN})/(?P<fid>FIG-[a-z0-9-]+-p[0-9]+-[0-9]+)\.(?P<ext>png|svg)$"
)


def parse_figure_file(own_id: str, file: str, exts: tuple[str, ...]) -> tuple[str, str] | None:
    """Validate a figure file path. Returns None for the figure's own file, or
    (other_slug, other_figure_id) for a deduplicated figure. Raises ValueError otherwise."""
    if any(file == f"{own_id}.{e}" for e in exts):
        return None
    m = _DEDUP_RE.match(file)
    if m is not None and m.group("ext") in exts and ids.FIGURE_ID_RE.match(m.group("fid")):
        other_slug = ids.parse_figure_id(m.group("fid"))[0]
        if other_slug == m.group("dir") and m.group("fid") != own_id:
            return other_slug, m.group("fid")
    allowed = "|".join(exts)
    raise ValueError(
        f"file must be <own id>.({allowed}) or ../<other-slug>/<FIG-other-id>.({allowed}) "
        f"with the other id's slug matching the directory, got {file!r}"
    )


class FigureRecord(ContractModel):
    id: FigureId
    file: str
    svg: str | None
    source_doc: DocSlug
    product_model: str | None
    page: int = Field(ge=1)
    bbox: BBox | None
    extraction: Extraction
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    phash: PHash
    caption_original: str | None
    description_generated: str | None
    tags: list[str]
    articles: list[ArticleId]
    attach_rule: AttachRule
    confidence: Unit
    review: BlockStatus

    @field_validator("tags", mode="before")
    @classmethod
    def _norm_tags(cls, v: Any) -> Any:
        if isinstance(v, list) and all(isinstance(t, str) for t in v):
            # lowercase + de-duplicate, keeping first-seen order (SPEC 6.3 example is unsorted)
            return list(dict.fromkeys(t.lower() for t in v))
        return v

    @field_validator("articles", mode="before")
    @classmethod
    def _norm_articles(cls, v: Any) -> Any:
        if isinstance(v, list) and all(isinstance(t, str) for t in v):
            return sorted(set(v))
        return v

    @model_validator(mode="after")
    def _check(self) -> FigureRecord:
        if (self.svg is not None) != (self.extraction == Extraction.vector):
            raise ValueError("svg must be set if and only if extraction == vector")
        file_target = parse_figure_file(self.id, self.file, ("png", "svg"))
        if self.svg is not None:
            svg_target = parse_figure_file(self.id, self.svg, ("svg",))
            if svg_target != file_target:
                raise ValueError("svg must point at the same figure as file")
        slug, page, _ = ids.parse_figure_id(self.id)
        if slug != self.source_doc or page != self.page:
            raise ValueError("id: slug/page do not match source_doc/page")
        return self
