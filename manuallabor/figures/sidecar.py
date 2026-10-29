"""Build the SPEC 6.3 sidecar for one figure (design section 9)."""

from __future__ import annotations

from manuallabor import ids
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import AttachRule, BlockStatus, Extraction
from manuallabor.contracts.figure import FigureRecord
from manuallabor.figures.types import DedupeEntry, FigureExtraction

PROVISIONAL_CONFIDENCE = {Extraction.native: 1.0, Extraction.vector: 0.95, Extraction.crop: 0.70}


def build_record(
    ext: FigureExtraction, doc: Document, entry: DedupeEntry, existing: FigureRecord | None
) -> FigureRecord:
    if entry.duplicate_of is None:
        file, svg = f"{ext.figure_id}.png", f"{ext.figure_id}.svg"
    else:
        cslug = ids.parse_figure_id(entry.duplicate_of)[0]
        file = f"../{cslug}/{entry.duplicate_of}.png"
        svg = f"../{cslug}/{entry.duplicate_of}.svg"
    is_vector = ext.method == Extraction.vector
    fields: dict[str, object] = {
        "id": ext.figure_id,
        "file": file,
        "svg": svg if is_vector else None,
        "source_doc": doc.slug,
        "product_model": doc.product_model,
        "page": ext.page,
        "bbox": ext.bbox,
        "extraction": ext.method,
        "width": ext.width,
        "height": ext.height,
        "phash": ext.phash,
        "caption_original": ext.caption_original,
        "description_generated": None,
        "tags": [],
        "articles": [],
        "attach_rule": AttachRule.none,
        "confidence": PROVISIONAL_CONFIDENCE[ext.method],
        "review": BlockStatus.queued,
    }
    if existing is not None:
        for k in (
            "description_generated",
            "tags",
            "articles",
            "attach_rule",
            "confidence",
            "review",
        ):
            fields[k] = getattr(existing, k)
    return FigureRecord.model_validate(fields)
