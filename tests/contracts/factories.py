"""Builders for valid contract instances (test helpers)."""

from __future__ import annotations

from typing import Any

SLUG = "acme-x200-service"
SHA = "a" * 64
TS = "2026-10-28T18:00:00Z"


def block_dict(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": f"b-{SLUG}-p042-03",
        "doc_id": SLUG,
        "page": 42,
        "bbox": [72.0, 100.0, 300.0, 120.0],
        "type": "paragraph",
        "reading_order": 3,
        "raw_text": "Tighten bolts to 35 N·m.",
        "raw_source": "pymupdf",
    }
    d.update(over)
    return d


def document_dict(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "slug": SLUG,
        "sha256": SHA,
        "filename": "X200_Service_Manual_rev4.pdf",
        "kind": "born_digital_pdf",
        "page_count": 100,
        "block_ids": [f"b-{SLUG}-p001-0{i}" for i in (1, 2, 3)],
    }
    d.update(over)
    return d


def figure_dict(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": f"FIG-{SLUG}-p042-01",
        "file": f"FIG-{SLUG}-p042-01.png",
        "svg": None,
        "source_doc": SLUG,
        "product_model": "Acme X200",
        "page": 42,
        "bbox": [72.0, 410.2, 523.5, 688.0],
        "extraction": "native",
        "width": 1800,
        "height": 1200,
        "phash": "c3a1b2c3d4e5f607",
        "caption_original": "Figure 1. Belt tension adjustment points",
        "description_generated": "Side view.",
        "tags": ["belt", "motor mount"],
        "articles": [f"{SLUG}--belt-tension"],
        "attach_rule": "caption_ref",
        "confidence": 0.96,
        "review": "approved",
    }
    d.update(over)
    return d


def manifest_dict() -> dict[str, Any]:
    b1, b2, b3 = (f"b-{SLUG}-p001-0{i}" for i in (1, 2, 3))
    fig = f"FIG-{SLUG}-p001-01"
    art = SLUG
    return {
        "project": {"name": "p", "tool_version": "0.1.0", "generated_at": TS},
        "docs": [document_dict()],
        "articles": [
            {
                "id": art,
                "path": f"articles/{art}.md",
                "review_sidecar": f"articles/{art}.review.json",
                "title": "T",
                "source_doc": SLUG,
                "block_ids": [b1, b2],
                "figures": [fig],
                "pages": [1],
                "sections": [],
            }
        ],
        "figures": [
            {
                "id": fig,
                "sidecar": f"images/{SLUG}/{fig}.json",
                "file": f"{fig}.png",
                "source_doc": SLUG,
            }
        ],
        "review_stats": {
            "total_blocks": 3,
            "auto_approved": 2,
            "approved": 0,
            "edited": 0,
            "flagged": 0,
            "rejected": 0,
            "queued": 1,
            "overrides": 0,
            "numbers_verified_blocks": [],
        },
        "models": {"cleanup": {"provider": "mock", "model": "mock-1"}},
        "threshold": 0.85,
        "article_split": "per_document",
        "overrides": [],
        "accounting": {
            "total_blocks": 3,
            "assignments": {b1: art, b2: art, b3: "unassigned"},
            "unassigned_reasons": {b3: "not_selected"},
        },
    }


def article_review_dict() -> dict[str, Any]:
    """A valid `articles/<id>.review.json` (design 11 section 20): one block of each status and
    a figure block."""
    art = f"{SLUG}--belt-tension"
    b = [f"b-{SLUG}-p042-0{i}" for i in range(1, 6)]

    def row(i: int, **over: Any) -> dict[str, Any]:
        d: dict[str, Any] = {
            "block_id": b[i],
            "type": "paragraph",
            "page": 42,
            "status": "approved",
            "decided_by": "person",
            "at": TS,
            "confidence": None,
            "edited_by": None,
            "reason": None,
            "flag_id": None,
            "figure": None,
            "text_sha256": "d" * 64,
        }
        d.update(over)
        return d

    return {
        "schema_version": "1.0",
        "article_id": art,
        "article": f"articles/{art}.md",
        "generated_at": TS,
        "counts": {"auto_approved": 2, "approved": 1, "edited": 1, "overridden": 1},
        "blocks": [
            row(
                0,
                type="heading",
                status="auto_approved",
                decided_by="checks",
                at=None,
                confidence=0.97,
            ),
            row(1),
            row(2, status="edited", edited_by="agent_proposal"),
            row(
                3,
                status="overridden",
                decided_by="override",
                reason="paper -- ok",
                flag_id="flag-000001",
            ),
            row(
                4,
                type="figure",
                status="auto_approved",
                decided_by="checks",
                at=None,
                confidence=0.99,
                text_sha256=None,
                figure={
                    "figure_id": f"FIG-{SLUG}-p042-01",
                    "placements": [{"article_id": art, "rule": "caption_ref", "confidence": 0.96}],
                },
            ),
        ],
    }
