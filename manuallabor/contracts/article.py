"""Article front matter (SPEC 6.2)."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any, Final, Literal

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


class ArticleReviewCounts(ContractModel):
    """An article's blocks (figure blocks included) by who decided they could go out: the
    review sidecar's `counts` and, since design 11 section 20.11, the front matter `review`."""

    auto_approved: int = Field(ge=0)
    approved: int = Field(ge=0)
    edited: int = Field(ge=0)
    overridden: int = Field(ge=0)

    def total(self) -> int:
        return self.auto_approved + self.approved + self.edited + self.overridden


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
    # the sidecar's categories, key for key (design 11 section 20.11); they sum to `blocks`
    review: ArticleReviewCounts
    generated_at: UTCDateTime

    @field_validator("pages")
    @classmethod
    def _check_pages(cls, v: list[int]) -> list[int]:
        if v != sorted(set(v)) or any(p < 1 for p in v):
            raise ValueError("pages must be sorted, unique and >= 1")
        return v

    @model_validator(mode="after")
    def _check(self) -> ArticleFrontmatter:
        if self.review.total() != self.blocks:
            raise ValueError(
                f"review counts sum to {self.review.total()}, not to blocks ({self.blocks}): "
                "every block is in exactly one category"
            )
        if self.id != self.source_doc and not self.id.startswith(f"{self.source_doc}--"):
            raise ValueError("id must equal source_doc or start with '<source_doc>--'")
        if len(set(self.figures)) != len(self.figures):
            raise ValueError("figures must be unique")
        return self

    def to_yaml_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# -- the per-article review sidecar (design 11 section 20) -----------------------------------------

ReviewStatus = Literal["auto_approved", "approved", "edited", "overridden"]
# paragraph: a unit of the article, its marker on the line above; figure: a figure block, which
# has no paragraph and no marker (design 11 section 20.11)
Placement = Literal["paragraph", "figure"]
TEXT_PREFIX: Final = 80  # BlockReview.text: the first 80 characters of the block's part
DecidedBy = Literal["checks", "person", "override"]
# a figure line's status: who decided to show the figure there (design 11 section 20.13)
FigureLineStatus = Literal["auto_approved", "approved", "overridden"]
# `r<n>`: an override's reason in the article's `reasons` table (design 11 section 20.14)
ReasonId = Annotated[str, Field(pattern=r"^r[1-9][0-9]*$")]
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
    # each marker stands directly above its own paragraph and that the paragraph is unchanged.
    text_sha256: Sha256Hex | None
    # the first 80 characters of that part, so a reader can find the paragraph without counting;
    # None for a figure block (design 11 section 20.11)
    text: str | None
    placement: Placement
    # overridden only: the override's reason in the article's `reasons` table, which the marker
    # names instead of repeating the reason (design 11 section 20.14)
    reason_id: ReasonId | None
    # edited only: the block's text as the parser read it from the manual (full, unrendered) and
    # when the edit (a person's, or an accepted agent proposal) was made (section 20.12)
    original_text: str | None
    edited_at: UTCDateTime | None
    # the block's faithfulness verdict when it went out (None: no machine check applies, e.g. an
    # edited block or a figure block). False is allowed only when a person approved it after
    # reading the change; cleaned text that failed never goes out unchecked (section 20.16)
    faithfulness_passed: bool | None

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
        if (self.reason_id is not None) != (self.status == "overridden"):
            raise ValueError("reason_id must be set if and only if status == overridden")
        if (self.original_text is not None) != (self.status == "edited"):
            raise ValueError("original_text must be set if and only if status == edited")
        if (self.edited_at is not None) != (self.status == "edited"):
            raise ValueError("edited_at must be set if and only if status == edited")
        if self.edited_at is not None and self.at is not None and self.edited_at > self.at:
            raise ValueError("edited_at must not be later than at (the effective decision)")
        if self.faithfulness_passed is False and self.status not in ("approved", "edited"):
            raise ValueError(
                "faithfulness_passed is False: cleaned text that failed the faithfulness check "
                "goes out only after a person approved or edited it, never "
                f"{self.status!r}"
            )
        if (self.text_sha256 is None) != (self.type == BlockType.figure):
            raise ValueError("text_sha256 must be set if and only if the block is not a figure")
        if (self.text is None) != (self.type == BlockType.figure):
            raise ValueError("text must be set if and only if the block is not a figure")
        if self.text is not None and len(self.text) > TEXT_PREFIX:
            raise ValueError(f"text holds at most the first {TEXT_PREFIX} characters")
        if (self.placement == "figure") != (self.type == BlockType.figure):
            raise ValueError("placement must be 'figure' for a figure block, else 'paragraph'")
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


class ReviewReason(ContractModel):
    """One row of an article's reason table: `id` is what its markers carry (section 20.14)."""

    id: ReasonId
    reason: str


class FigureLineReview(ContractModel):
    """One figure line of the article (design 11 section 20.13): who decided to show the figure
    here. `block_id` is the figure's own block, wherever it is accounted (it may be in another
    article, or unassigned when a caption reference pulled the figure in)."""

    figure_id: FigureId
    block_id: BlockId
    rule: AttachRule  # how the figure was attached to this article
    status: FigureLineStatus
    decided_by: DecidedBy
    reason: str | None  # overridden only
    reason_id: ReasonId | None  # overridden only
    flag_id: FlagId | None  # overridden only: the open flag the override covered

    @model_validator(mode="after")
    def _check(self) -> FigureLineReview:
        if self.decided_by != DECIDED_BY[self.status]:
            raise ValueError(
                f"decided_by must be {DECIDED_BY[self.status]!r} for status {self.status!r}"
            )
        if self.rule == AttachRule.none:
            raise ValueError("rule: a figure line is shown by an attachment, never rule 'none'")
        over = self.status == "overridden"
        if (self.reason is not None) != over:
            raise ValueError("reason must be set if and only if status == overridden")
        if (self.reason_id is not None) != over:
            raise ValueError("reason_id must be set if and only if status == overridden")
        if self.flag_id is not None and not over:
            raise ValueError("flag_id is only allowed when status == overridden")
        return self


class ArticleReview(ContractModel):
    """`articles/<id>.review.json`: every block of the article (its manifest `block_ids`, same
    order) with its review status. Every text block (`placement: paragraph`) starts in the
    article with an invisible `<!-- ml: <status>; ... -->` marker on the line above it; a figure
    block (`placement: figure`) has none (design 11 section 20.11)."""

    schema_version: Literal["1.0"] = "1.0"
    article_id: ArticleId
    article: str
    generated_at: UTCDateTime
    counts: ArticleReviewCounts
    blocks: list[BlockReview]
    # the reasons the article's overridden markers refer to, `r1`, `r2`, ... in order of first
    # use in the article body (design 11 section 20.14)
    reasons: list[ReviewReason]
    # every figure line of the article, in body order, each with its marker (section 20.13)
    figure_lines: list[FigureLineReview]

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
        figs = [f.figure_id for f in self.figure_lines]
        if len(set(figs)) != len(figs):
            raise ValueError("figure_lines: a figure is shown at most once per article")
        for f in self.figure_lines:
            if (
                ids.parse_figure_id(f.figure_id)[0] != slug
                or ids.parse_block_id(f.block_id)[0] != slug
            ):
                raise ValueError(f"figure_lines: {f.figure_id} belongs to another document")
        rids = [r.id for r in self.reasons]
        if rids != [f"r{i}" for i in range(1, len(rids) + 1)]:
            raise ValueError(f"reasons: ids must be r1, r2, ... in order, got {rids}")
        texts = [r.reason for r in self.reasons]
        if len(set(texts)) != len(texts):
            raise ValueError("reasons: each reason appears once")
        table = {r.id: r.reason for r in self.reasons}
        used: set[str] = set()
        refs = [(b.reason_id, b.reason) for b in self.blocks]
        refs += [(f.reason_id, f.reason) for f in self.figure_lines]
        for rid, reason in refs:
            if rid is None:
                continue
            if rid not in table:
                raise ValueError(f"reason_id {rid} is not in reasons")
            if table[rid] != reason:
                raise ValueError(f"reason of {rid} differs from the reasons table")
            used.add(rid)
        unused = [r for r in rids if r not in used]
        if unused:
            raise ValueError(f"reasons: {unused} referenced by no entry")
        return self
