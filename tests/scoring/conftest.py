"""Fixtures for the scoring tests: a parsed + figures + scored project and block factories."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.io import read_json, read_json_list
from manuallabor.figures.pipeline import run_figures
from manuallabor.parse.types import PageLayout
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import block_contexts, run_score
from manuallabor.scoring.types import BlockContext
from tests.conftest import Parsed

SLUG = "doc"


def make_block(
    raw: str = "Check the drive belt.",
    *,
    n: int = 1,
    page: int = 1,
    type: BlockType = BlockType.paragraph,
    source: str = "pymupdf",
    texts: dict[str, str] | None = None,
    order: dict[str, int] | None = None,
    reading_order: int | None = None,
    **kw: Any,
) -> Block:
    if texts is None:
        texts = {"pymupdf": raw, "docling": raw} if source in ("pymupdf", "docling") else {}
    return Block(
        id=f"b-{SLUG}-p{page:03d}-{n:02d}",
        doc_id=SLUG,
        page=page,
        bbox=[0, 0, 10, 10],
        type=type,
        reading_order=n if reading_order is None else reading_order,
        raw_text=raw,
        raw_source=source,
        raw_text_by_parser=texts,
        order_by_parser=order or {},
        **kw,
    )


def ctx(**kw: Any) -> BlockContext:
    base: dict[str, Any] = {
        "parser_versions": {"pymupdf": "x", "docling": "y", "ocr": "t", "ocr_alt": "r"},
        "product_model": "Acme X200",
        "hf_strings": ["Acme X200 Service Manual", "Page 3"],
    }
    base.update(kw)
    return BlockContext(**base)


@dataclass
class Scored:
    paths: ProjectPaths

    def doc(self, slug: str) -> Document:
        return read_json(self.paths.doc(slug).document, Document)

    def blocks(self, slug: str) -> list[Block]:
        return read_json_list(self.paths.doc(slug).blocks, Block)

    def layouts(self, slug: str) -> list[PageLayout]:
        return read_json_list(self.paths.doc(slug).layout, PageLayout)

    def contexts(self, slug: str, blocks: list[Block] | None = None) -> dict[str, BlockContext]:
        return block_contexts(self.doc(slug), blocks or self.blocks(slug), self.layouts(slug))


@pytest.fixture(scope="session")
def figproj_scoring(parsed: Parsed, tmp_path_factory: pytest.TempPathFactory) -> ProjectPaths:
    root = tmp_path_factory.mktemp("figproj-scoring") / "proj"
    shutil.copytree(parsed.paths.root, root)
    paths = ProjectPaths(root)
    assert run_figures(paths, emit=lambda _o: None) == []
    return paths


@pytest.fixture(scope="session")
def scoredproj(figproj_scoring: ProjectPaths, tmp_path_factory: pytest.TempPathFactory) -> Scored:
    root = tmp_path_factory.mktemp("scoredproj") / "proj"
    shutil.copytree(figproj_scoring.root, root)
    paths = ProjectPaths(root)
    assert run_score(paths, emit=lambda _o: None) == []
    return Scored(paths)


@pytest.fixture
def scored_copy(scoredproj: Scored, tmp_path: Path) -> ProjectPaths:
    root = tmp_path / "scored"
    shutil.copytree(scoredproj.paths.root, root)
    return ProjectPaths(root)
