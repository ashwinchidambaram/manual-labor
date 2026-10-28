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
