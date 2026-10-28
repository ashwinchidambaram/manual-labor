"""Manual Labor data contracts."""

from __future__ import annotations

from pydantic import BaseModel

from manuallabor.contracts._base import (
    BBox,
    ContractModel,
    Coord,
    PHash,
    Sha256Hex,
    Unit,
    UTCDateTime,
)
from manuallabor.contracts.article import ArticleFrontmatter, ReviewCounts
from manuallabor.contracts.block import (
    Block,
    DiffOp,
    FaithfulnessResult,
    FaithfulnessViolation,
    NumericVariant,
    OcrWord,
    Signal,
    TableCell,
    TableData,
    TableShape,
)
from manuallabor.contracts.config import KNOWN_PROVIDERS, ModelRef, ProjectConfig, TaskModels
from manuallabor.contracts.decision import Decision
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import (
    ArticleSplit,
    AttachRule,
    BlockStatus,
    BlockType,
    CallKind,
    DecisionAction,
    DiffOpKind,
    DocKind,
    Extraction,
    FaithViolationKind,
    FlagCategory,
    FlagStatus,
    GroupView,
    OcrEngine,
    ProposalStatus,
    SignalName,
    Task,
)
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.flag import Flag
from manuallabor.contracts.group import Group, PageRange, Topic
from manuallabor.contracts.llm import ChatResult, LLMCallLog, Message
from manuallabor.contracts.manifest import (
    BlockAccounting,
    Manifest,
    ManifestArticle,
    ManifestFigure,
    ManifestProject,
    Override,
    ReviewStats,
)
from manuallabor.contracts.proposal import PriorAttempt, Proposal, RecheckResult
from manuallabor.contracts.selection import Selection

EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    Block,
    Document,
    FigureRecord,
    Group,
    Selection,
    Flag,
    Decision,
    Proposal,
    ArticleFrontmatter,
    Manifest,
    ProjectConfig,
    LLMCallLog,
)

__all__ = [
    "EXPORTED_MODELS",
    "KNOWN_PROVIDERS",
    "ArticleFrontmatter",
    "ArticleSplit",
    "AttachRule",
    "BBox",
    "Block",
    "BlockAccounting",
    "BlockStatus",
    "BlockType",
    "CallKind",
    "ChatResult",
    "ContractModel",
    "Coord",
    "Decision",
    "DecisionAction",
    "DiffOp",
    "DiffOpKind",
    "DocKind",
    "Document",
    "Extraction",
    "FaithViolationKind",
    "FaithfulnessResult",
    "FaithfulnessViolation",
    "FigureRecord",
    "Flag",
    "FlagCategory",
    "FlagStatus",
    "Group",
    "GroupView",
    "LLMCallLog",
    "Manifest",
    "ManifestArticle",
    "ManifestFigure",
    "ManifestProject",
    "Message",
    "ModelRef",
    "NumericVariant",
    "OcrEngine",
    "OcrWord",
    "Override",
    "PHash",
    "PageRange",
    "PriorAttempt",
    "ProjectConfig",
    "Proposal",
    "ProposalStatus",
    "RecheckResult",
    "ReviewCounts",
    "ReviewStats",
    "Selection",
    "Sha256Hex",
    "Signal",
    "SignalName",
    "TableCell",
    "TableData",
    "TableShape",
    "Task",
    "TaskModels",
    "Topic",
    "UTCDateTime",
    "Unit",
]
