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

_FIG_CORE = re.sub(r"\?P<\w+>", "?:", ids.FIGURE_ID_PATTERN[1:-1])
FILE_RE = re.compile(rf"^(?:\.\./[a-z0-9-]+/)?{_FIG_CORE}\.(?:png|jpg)$")


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

    @field_validator("file")
    @classmethod
    def _check_file(cls, v: str) -> str:
        if not FILE_RE.match(v):
            raise ValueError("file must match [../<slug>/]FIG-<...>.(png|jpg)")
        return v

    @model_validator(mode="after")
    def _check(self) -> FigureRecord:
        if (self.svg is not None) != (self.extraction == Extraction.vector):
            raise ValueError("svg must be set if and only if extraction == vector")
        if self.svg is not None and self.svg != f"{self.id}.svg":
            raise ValueError("svg must equal <id>.svg")
        slug, page, _ = ids.parse_figure_id(self.id)
        if slug != self.source_doc or page != self.page:
            raise ValueError("id: slug/page do not match source_doc/page")
        return self
