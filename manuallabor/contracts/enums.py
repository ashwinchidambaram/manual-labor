"""Every contract enum. Values are part of the on-disk format."""

from __future__ import annotations

from enum import StrEnum


class DocKind(StrEnum):
    born_digital_pdf = "born_digital_pdf"
    scanned_pdf = "scanned_pdf"
    docx = "docx"


class BlockType(StrEnum):
    heading = "heading"
    paragraph = "paragraph"
    list = "list"
    table = "table"
    figure = "figure"
    caption = "caption"
    header = "header"
    footer = "footer"
    other = "other"


class BlockStatus(StrEnum):
    auto_approved = "auto_approved"
    queued = "queued"
    approved = "approved"
    edited = "edited"
    flagged = "flagged"
    rejected = "rejected"


class SignalName(StrEnum):
    ocr_mean = "ocr_mean"
    ocr_min = "ocr_min"
    textlayer_vs_ocr = "textlayer_vs_ocr"
    parser_agreement = "parser_agreement"
    reading_order_risk = "reading_order_risk"
    table_consistency = "table_consistency"
    garbage_ratio = "garbage_ratio"
    faithfulness = "faithfulness"
    figure_method = "figure_method"
    figure_resolution = "figure_resolution"
    figure_attach_rule = "figure_attach_rule"
    has_numeric_spec = "has_numeric_spec"
    llm_verifier = "llm_verifier"


class Extraction(StrEnum):
    native = "native"
    vector = "vector"
    crop = "crop"


class AttachRule(StrEnum):
    caption_ref = "caption_ref"
    caption_match = "caption_match"
    proximity = "proximity"
    none = "none"
    human = "human"


class GroupView(StrEnum):
    structure = "structure"
    topic = "topic"


class UnassignedReason(StrEnum):
    header_footer = "header_footer"
    low_similarity = "low_similarity"
    no_text = "no_text"
    topic_failed = "topic_failed"
    do_not_merge = "do_not_merge"


class TitleSource(StrEnum):
    heading = "heading"
    llm = "llm"
    fallback = "fallback"
    human = "human"


class ArticleSplit(StrEnum):
    per_topic = "per_topic"
    per_document = "per_document"


class FlagCategory(StrEnum):
    wrong_text = "wrong_text"
    missing_figure = "missing_figure"
    wrong_grouping = "wrong_grouping"
    bad_crop = "bad_crop"
    table_structure = "table_structure"


class FlagStatus(StrEnum):
    open = "open"
    resolved = "resolved"


class DecisionAction(StrEnum):
    approve = "approve"
    edit = "edit"
    flag = "flag"
    skip = "skip"


class ProposalStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    edited = "edited"
    rejected = "rejected"
    superseded = "superseded"


class ProposalKind(StrEnum):
    """What a proposal changes (module 10)."""

    text = "text"
    cells = "cells"
    bbox = "bbox"
    attach = "attach"
    regroup = "regroup"


class EvidenceSource(StrEnum):
    """Where a proposal's evidence span was quoted from (module 10)."""

    pymupdf = "pymupdf"
    docling = "docling"
    ocr = "ocr"
    ocr_alt = "ocr_alt"
    docx = "docx"
    vision = "vision"
    note = "note"
    candidate = "candidate"


class Task(StrEnum):
    cleanup = "cleanup"
    grouping = "grouping"
    vision = "vision"
    verifier = "verifier"
    embeddings = "embeddings"
    metadata = "metadata"
    agent = "agent"


class CallKind(StrEnum):
    chat = "chat"
    vision = "vision"
    embed = "embed"


class OcrEngine(StrEnum):
    auto = "auto"
    rapidocr = "rapidocr"
    tesseract = "tesseract"


class FaithViolationKind(StrEnum):
    insertion = "insertion"
    deletion = "deletion"
    numeric_mismatch = "numeric_mismatch"
    reorder = "reorder"


class DiffOpKind(StrEnum):
    equal = "equal"
    insert = "insert"
    delete = "delete"
    replace = "replace"  # type: ignore[assignment]
    reorder = "reorder"
