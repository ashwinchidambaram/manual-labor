"""Fixtures and builders for the grouping tests."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from manuallabor import ids
from manuallabor.contracts import ModelRef, Task
from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockType, DocKind
from manuallabor.contracts.group import GroupsFile
from manuallabor.contracts.io import read_json
from manuallabor.grouping.pipeline import run_group
from manuallabor.grouping.selection import load_groups
from manuallabor.project import ProjectPaths
from manuallabor.providers import ListSink, MockProvider, ProviderSet
from manuallabor.providers.mock import Responder
from manuallabor.scoring.pipeline import load_scored_blocks
from tests.conftest import ALL_FIXTURES, FIXTURES, Scored
from tests.conftest import copy_project as _lean_copy

SLUG = "doc"
GT_DIR = FIXTURES / "ground_truth"


def gt_blocks(name: str) -> list[Block]:
    """Contract Blocks built from the hand-written ground truth (no parser involved)."""
    gt = json.loads((GT_DIR / f"{name}.json").read_text(encoding="utf-8"))
    slug = gt["expected_slug"]
    per_page: dict[int, int] = {}
    figs: dict[int, int] = {}
    out: list[Block] = []
    for b in gt["blocks"]:
        page = int(b["page"])
        per_page[page] = per_page.get(page, 0) + 1
        extra: dict[str, Any] = {}
        if b["type"] == "figure":
            figs[page] = figs.get(page, 0) + 1
            extra["figure_id"] = ids.figure_id(slug, page, figs[page])
        if b["type"] == "heading":
            extra["heading_level"] = b["heading_level"]
            extra["section_number"] = b["section_number"]
        out.append(
            Block(
                id=ids.block_id(slug, page, per_page[page]),
                doc_id=slug,
                page=page,
                bbox=b["bbox"],
                type=BlockType(b["type"]),
                reading_order=int(b["index"]),
                raw_text=b["text"],
                raw_source="pymupdf",
                **extra,
            )
        )
    return out


def gt_document(name: str, blocks: Sequence[Block]) -> Document:
    gt = json.loads((GT_DIR / f"{name}.json").read_text(encoding="utf-8"))
    kind = DocKind.docx if gt["kind"] == "docx" else DocKind.born_digital_pdf
    return Document(
        slug=gt["expected_slug"],
        sha256="a" * 64,
        filename=gt["file"],
        kind=kind,
        page_count=int(gt["page_count"]),
        block_ids=[b.id for b in blocks],
    )


def gt_headings(name: str) -> list[dict[str, Any]]:
    gt = json.loads((GT_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return [b for b in gt["blocks"] if b["type"] == "heading"]


def gt_sections(name: str) -> list[tuple[dict[str, Any], list[int]]]:
    """Each GT heading with the pages of the non-header/footer GT blocks from it to the next
    heading (the heading itself included)."""
    gt = json.loads((GT_DIR / f"{name}.json").read_text(encoding="utf-8"))
    out: list[tuple[dict[str, Any], list[int]]] = []
    for b in gt["blocks"]:
        if b["type"] in ("header", "footer"):
            continue
        if b["type"] == "heading":
            out.append((b, [b["page"]]))
        elif out:
            out[-1][1].append(b["page"])
    return out


def mk(
    page: int,
    n: int,
    text: str = "Some text.",
    type: BlockType = BlockType.paragraph,
    *,
    ro: int | None = None,
    **kw: Any,
) -> Block:
    """A synthetic block of document `doc`; reading order follows (page, n)."""
    if type == BlockType.figure:
        kw.setdefault("figure_id", ids.figure_id(SLUG, page, n))
    if type == BlockType.heading:
        kw.setdefault("bbox", [0, 0, 100, 10])
    return Block(
        id=ids.block_id(SLUG, page, n),
        doc_id=SLUG,
        page=page,
        bbox=kw.pop("bbox", [0, 0, 10, 10]),
        type=type,
        reading_order=page * 1000 + n if ro is None else ro,
        raw_text=text,
        raw_source="pymupdf",
        **kw,
    )


def heading(page: int, n: int, text: str, **kw: Any) -> Block:
    return mk(page, n, text, BlockType.heading, **kw)


def doc_of(blocks: Sequence[Block], slug: str = SLUG) -> Document:
    return Document(
        slug=slug,
        sha256="a" * 64,
        filename=f"{slug}.pdf",
        kind=DocKind.born_digital_pdf,
        page_count=max((b.page for b in blocks), default=1),
        block_ids=[b.id for b in blocks],
    )


def provider_set(
    sink: ListSink,
    *,
    grouping: str | Responder | None = None,
    embeddings: Any = None,
) -> ProviderSet:
    responses = {Task.grouping: grouping} if grouping is not None else None
    chat = MockProvider(sink=sink, responses=responses)
    emb = embeddings if embeddings is not None else MockProvider(sink=sink)
    by_task: dict[Task, Any] = {t: MockProvider(sink=sink) for t in Task}
    by_task[Task.grouping] = chat
    by_task[Task.embeddings] = emb
    return ProviderSet(by_task=by_task)


@dataclass
class Grouped:
    paths: ProjectPaths
    scored: Scored

    def gf(self, slug: str) -> GroupsFile:
        return read_json(self.paths.doc(slug).groups, GroupsFile)

    def blocks(self, slug: str) -> list[Block]:
        return load_scored_blocks(self.paths, slug)

    def all_groups(self) -> dict[str, GroupsFile]:
        return load_groups(self.paths)


@pytest.fixture(scope="session")
def grouped(scoredproj: Scored, tmp_path_factory: pytest.TempPathFactory) -> Grouped:
    """All six fixtures grouped once with the all-mock project config (one parse per session)."""
    root = tmp_path_factory.mktemp("grouped") / "proj"
    _lean_copy(scoredproj.paths.root, root)
    paths = ProjectPaths(root)
    assert run_group(paths, emit=lambda _o: None) == []
    return Grouped(paths=paths, scored=scoredproj)


@pytest.fixture(params=ALL_FIXTURES)
def stem(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def run_and_collect() -> Callable[..., tuple[list[str], list[dict[str, Any]]]]:
    def _run(paths: ProjectPaths, **kw: Any) -> tuple[list[str], list[dict[str, Any]]]:
        lines: list[dict[str, Any]] = []
        failed = run_group(paths, emit=lines.append, **kw)
        return failed, lines

    return _run


def model_ref() -> ModelRef:
    return ModelRef(provider="mock", model="mock-1")


def copy_project(src: Path, dst: Path) -> ProjectPaths:
    _lean_copy(src, dst)
    return ProjectPaths(dst)


def mini_project(grouped: Grouped, dst: Path) -> ProjectPaths:
    """A light copy holding only project.json, document.json and groups.json per document."""
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(grouped.paths.config, dst / "project.json")
    for slug in grouped.paths.list_slugs():
        src = grouped.paths.doc(slug)
        out = ProjectPaths(dst).doc(slug)
        out.root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src.document, out.document)
        shutil.copyfile(src.groups, out.groups)
    return ProjectPaths(dst)
