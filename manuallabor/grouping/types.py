"""Grouping constants (single source, copied into GroupingParams) and internal models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from manuallabor.contracts.enums import TitleSource, UnassignedReason
from manuallabor.contracts.group import Group, GroupingParams, UnassignedEntry

GROUPING_ALGO_VERSION: Final = "1"

SUMMARY_TOKENS: Final = 64
NAME_SAMPLE: Final = 12
NAME_TOKENS: Final = 40
EMBED_BATCH: Final = 32
EMBED_PREFIX: Final[dict[str, str]] = {"nomic-embed-text": "clustering: "}
SMALL_DOC: Final = 12
D_CUT: Final = 0.80
K_MAX_DIVISOR: Final = 4
MIN_TOPIC_BLOCKS: Final = 3
MAX_TOPIC_BLOCKS: Final = 60
MIN_FINAL_TOPIC_BLOCKS: Final = 2
T_ASSIGN: Final = 0.30
T_CANDIDATE: Final = 0.15
N_CANDIDATES: Final = 3
STRAGGLER_BATCH: Final = 10
LOW_COHESION: Final = 0.30
PAGE_WINDOW: Final = 10
TITLE_MAX: Final = 80
TOPIC_SLUG_MAX: Final = 40
STRUCTURE_TITLE_MAX: Final = 200
MAX_GROUPS: Final = 999
MAX_EXAMPLES: Final = 3

UNASSIGNED_TITLE: Final = "Unassigned blocks"


class GroupingError(Exception):
    """A grouping invariant failed; nothing is written for the document."""


class TopicFailure(GroupingError):
    """The topic view could not be built (embeddings failed); the structure view still stands."""


def embed_prefix_for(model: str) -> str:
    """Document prefix for an embedding model name, with any `:tag` removed."""
    return EMBED_PREFIX.get(model.split(":", 1)[0], "")


def default_params(embed_prefix: str = "") -> GroupingParams:
    return GroupingParams(
        summary_tokens=SUMMARY_TOKENS,
        name_sample=NAME_SAMPLE,
        name_tokens=NAME_TOKENS,
        embed_batch=EMBED_BATCH,
        embed_prefix=embed_prefix,
        small_doc=SMALL_DOC,
        d_cut=D_CUT,
        k_max_divisor=K_MAX_DIVISOR,
        min_topic_blocks=MIN_TOPIC_BLOCKS,
        max_topic_blocks=MAX_TOPIC_BLOCKS,
        t_assign=T_ASSIGN,
        t_candidate=T_CANDIDATE,
        n_candidates=N_CANDIDATES,
        straggler_batch=STRAGGLER_BATCH,
        low_cohesion=LOW_COHESION,
        page_window=PAGE_WINDOW,
        title_max=TITLE_MAX,
        topic_slug_max=TOPIC_SLUG_MAX,
        llm_stragglers=True,
    )


@dataclass
class SectionNode:
    """One heading that became a structure group."""

    block_id: str
    title: str
    level: int  # raw level used for stack parenting
    section_number: str | None
    parent: int | None  # index into the node list
    depth: int  # 1 = top level


@dataclass
class StructureResult:
    groups: list[Group]
    unassigned: list[UnassignedEntry]
    section_of: dict[str, str]
    path_of: dict[str, list[str]]
    title_sources: dict[str, TitleSource]
    heading_of: dict[str, str]  # structure group id -> its heading block id


@dataclass(frozen=True)
class StragglerDecision:
    block_id: str
    topic_key: str | None
    similarity: float
    by: Literal["centroid", "llm"]


@dataclass
class Assembly:
    """Topic membership while the §3.6 rules and the overrides run. Topics are addressed by a
    provisional key (`c01`, ...); a block placed on None sits in t000 for `reasons[block]`."""

    placed: dict[str, str | None]
    reasons: dict[str, UnassignedReason]
    titles: dict[str, str]
    slugs: dict[str, str]
    sources: dict[str, TitleSource]

    def members(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {k: [] for k in self.titles}
        for b, k in self.placed.items():
            if k is not None:
                out[k].append(b)
        return out


@dataclass
class GroupStats:
    llm_fallbacks: int = 0
    straggler_fallbacks: int = 0
