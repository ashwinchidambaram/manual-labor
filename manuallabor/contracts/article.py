"""Article front matter (SPEC 6.2)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Final, Literal

from pydantic import Field, field_validator, model_validator

from manuallabor import ids
from manuallabor.contracts._base import (
    ArticleId,
    BlockId,
    ContractModel,
    DocSlug,
    FigureId,
    FlagId,
    Sha256Hex,
    Unit,
    UTCDateTime,
)
from manuallabor.contracts.enums import AttachRule, BlockType


class ReviewCounts(ContractModel):
    approved: int = Field(ge=0)
    edited: int = Field(ge=0)
    overrides: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> ReviewCounts:
        if self.edited > self.approved:
            raise ValueError("review.edited must be <= review.approved")
        return self


class ArticleFrontmatter(ContractModel):
    id: ArticleId
    title: str
    source_doc: DocSlug
    source_file: str
    product_model: str | None
    pages: list[int]
    sections: list[str]
    figures: list[FigureId]
    blocks: int = Field(ge=0)
    review: ReviewCounts
    generated_at: UTCDateTime

    @field_validator("pages")
    @classmethod
    def _check_pages(cls, v: list[int]) -> list[int]:
        if v != sorted(set(v)) or any(p < 1 for p in v):
            raise ValueError("pages must be sorted, unique and >= 1")
        return v

    @model_validator(mode="after")
    def _check(self) -> ArticleFrontmatter:
        if self.review.approved > self.blocks:
            raise ValueError("review.approved must be <= blocks")
        if self.id != self.source_doc and not self.id.startswith(f"{self.source_doc}--"):
            raise ValueError("id must equal source_doc or start with '<source_doc>--'")
        if len(set(self.figures)) != len(self.figures):
            raise ValueError("figures must be unique")
        return self

    def to_yaml_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# -- the per-article review sidecar (design 11 section 20) -----------------------------------------

ReviewStatus = Literal["auto_approved", "approved", "edited", "overridden"]
DecidedBy = Literal["checks", "person", "override"]
DECIDED_BY: Final[dict[str, DecidedBy]] = {
    "auto_approved": "checks",
    "approved": "person",
    "edited": "person",
    "overridden": "override",
}


class FigurePlacement(ContractModel):
    """One attachment of a figure in a written article: where its figure line appears."""

    article_id: ArticleId
    rule: AttachRule
    confidence: Unit


class FigureReview(ContractModel):
    figure_id: FigureId
    # sorted by article id; empty = the figure is shown in no article
    placements: list[FigurePlacement]

    @model_validator(mode="after")
    def _check(self) -> FigureReview:
        arts = [p.article_id for p in self.placements]
        if arts != sorted(set(arts)):
            raise ValueError("figure placements must be unique and sorted by article_id")
        return self


class BlockReview(ContractModel):
    """Who decided that one block of an article could go out, and when. `status` fixes
    `decided_by`: auto_approved -> checks, approved/edited -> person, overridden -> override."""

    block_id: BlockId
    type: BlockType
    page: int = Field(ge=1)
    status: ReviewStatus
    decided_by: DecidedBy
    # person: the effective decision's time; override: when the override was recorded
    at: UTCDateTime | None
    confidence: Unit | None  # auto_approved only: the block's combined score
    edited_by: Literal["person", "agent_proposal"] | None  # edited only: who wrote the text
    reason: str | None  # overridden only: the override's reason
    flag_id: FlagId | None  # overridden only: the open flag the override covered
    figure: FigureReview | None  # iff type == figure
    # sha256 of the block's part exactly as it is in the article (heading `#`s and list `* `
    # included); None for a figure block, which has no part. The validator uses it to prove that
    # each marker directly follows its own paragraph and that the paragraph is unchanged.
    text_sha256: Sha256Hex | None

    @model_validator(mode="after")
    def _check(self) -> BlockReview:
        if self.decided_by != DECIDED_BY[self.status]:
            raise ValueError(
                f"decided_by must be {DECIDED_BY[self.status]!r} for status {self.status!r}"
            )
        if self.type in (BlockType.header, BlockType.footer):
            raise ValueError("a page header or footer is never exported")
        if self.decided_by == "checks" and self.at is not None:
            raise ValueError("at must be None when the checks decided")
        if self.decided_by in ("override", "person") and self.at is None:
            raise ValueError(f"at is required when {self.decided_by!r} decided")
        if (self.reason is not None) != (self.status == "overridden"):
            raise ValueError("reason must be set if and only if status == overridden")
        if self.flag_id is not None and self.status != "overridden":
            raise ValueError("flag_id is only allowed when status == overridden")
        if (self.confidence is not None) != (self.status == "auto_approved"):
            raise ValueError("confidence must be set if and only if status == auto_approved")
        if (self.edited_by is not None) != (self.status == "edited"):
            raise ValueError("edited_by must be set if and only if status == edited")
        if (self.text_sha256 is None) != (self.type == BlockType.figure):
            raise ValueError("text_sha256 must be set if and only if the block is not a figure")
        if (self.figure is not None) != (self.type == BlockType.figure):
            raise ValueError("figure must be set if and only if type == figure")
        if self.figure is not None:
            slug, page, _ = ids.parse_block_id(self.block_id)
            fslug, fpage, _ = ids.parse_figure_id(self.figure.figure_id)
            if (fslug, fpage) != (slug, page) or page != self.page:
                raise ValueError("figure: the figure's document and page must be the block's")
        elif ids.parse_block_id(self.block_id)[1] != self.page:
            raise ValueError("page must be the block id's page")
        return self


class ArticleReviewCounts(ContractModel):
    auto_approved: int = Field(ge=0)
    approved: int = Field(ge=0)
    edited: int = Field(ge=0)
    overridden: int = Field(ge=0)


class ArticleReview(ContractModel):
    """`articles/<id>.review.json`: every block of the article (its manifest `block_ids`, same
    order) with its review status. A text block whose status is auto_approved or overridden is
    followed in the article by an invisible `<!-- ml: ... -->` marker; approved and edited blocks
    (a person looked) and figure blocks carry none."""

    schema_version: Literal["1.0"] = "1.0"
    article_id: ArticleId
    article: str
    generated_at: UTCDateTime
    counts: ArticleReviewCounts
    blocks: list[BlockReview]

    @model_validator(mode="after")
    def _check(self) -> ArticleReview:
        if self.article != f"articles/{self.article_id}.md":
            raise ValueError("article must be articles/<article_id>.md")
        bids = [b.block_id for b in self.blocks]
        if len(set(bids)) != len(bids):
            raise ValueError("blocks: block ids must be unique")
        slug = ids.parse_article_id(self.article_id)[0]
        for b in bids:
            if ids.parse_block_id(b)[0] != slug:
                raise ValueError(f"blocks: {b} belongs to another document")
        tally = Counter(b.status for b in self.blocks)
        want = ArticleReviewCounts(
            auto_approved=tally["auto_approved"],
            approved=tally["approved"],
            edited=tally["edited"],
            overridden=tally["overridden"],
        )
        if self.counts != want:
            raise ValueError(f"counts {self.counts.model_dump()} != tally {want.model_dump()}")
        return self
