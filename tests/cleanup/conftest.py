"""Fixtures and helpers for the cleanup tests (design 05 §12)."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pytest

from manuallabor import ids
from manuallabor.cleanup.lexicon import Lexicon
from manuallabor.cleanup.pipeline import run_clean
from manuallabor.cleanup.rules import PassCtx, compose, plan_passes
from manuallabor.cleanup.types import AttachFile, CleanFile, DescribeFile
from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockType, DocKind, GroupView
from manuallabor.contracts.group import Group, GroupsFile
from manuallabor.contracts.io import read_json, read_json_list
from manuallabor.grouping.pipeline import run_group
from manuallabor.parse.types import PageLayout
from manuallabor.project import ProjectPaths
from manuallabor.scoring.faithfulness import hf_tables
from manuallabor.scoring.pipeline import block_contexts, load_scored_blocks
from manuallabor.scoring.types import BlockContext, ScoreFile
from tests.conftest import FIXTURES, Scored, copy_project

GT_DIR = FIXTURES / "ground_truth"
SLUG = "doc"
Emit = list[dict[str, Any]]


def gt(name: str) -> dict[str, Any]:
    return json.loads((GT_DIR / f"{name}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


@dataclass
class Proj:
    paths: ProjectPaths

    def doc(self, slug: str) -> Document:
        return read_json(self.paths.doc(slug).document, Document)

    def raw_blocks(self, slug: str) -> list[Block]:
        return read_json_list(self.paths.doc(slug).blocks, Block)

    def blocks(self, slug: str) -> list[Block]:
        return load_scored_blocks(self.paths, slug)

    def layouts(self, slug: str) -> list[PageLayout]:
        p = self.paths.doc(slug).layout
        return read_json_list(p, PageLayout) if p.is_file() else []

    def contexts(self, slug: str) -> dict[str, BlockContext]:
        return block_contexts(self.doc(slug), self.raw_blocks(slug), self.layouts(slug))

    def clean(self, slug: str) -> CleanFile:
        return read_json(self.paths.doc(slug).clean, CleanFile)

    def attach(self, slug: str) -> AttachFile:
        return read_json(self.paths.doc(slug).attach, AttachFile)

    def describe(self, slug: str) -> DescribeFile:
        return read_json(self.paths.doc(slug).describe, DescribeFile)

    def scores(self, slug: str) -> ScoreFile:
        return read_json(self.paths.doc(slug).scores, ScoreFile)

    def gf(self, slug: str) -> GroupsFile:
        return read_json(self.paths.doc(slug).groups, GroupsFile)


def quiet(_o: dict[str, Any]) -> None:
    return None


@pytest.fixture(scope="session")
def groupedproj(scoredproj: Scored, tmp_path_factory: pytest.TempPathFactory) -> Proj:
    """All six fixtures scored + grouped with the all-mock project config."""
    root = tmp_path_factory.mktemp("c-grouped") / "proj"
    copy_project(scoredproj.paths.root, root)
    paths = ProjectPaths(root)
    assert run_group(paths, emit=quiet) == []
    return Proj(paths)


@pytest.fixture(scope="session")
def cleanedproj(groupedproj: Proj, tmp_path_factory: pytest.TempPathFactory) -> Proj:
    """groupedproj + `labor clean` (mock providers, llm residual)."""
    root = tmp_path_factory.mktemp("c-cleaned") / "proj"
    copy_project(groupedproj.paths.root, root)
    paths = ProjectPaths(root)
    assert run_clean(paths, emit=quiet) == []
    return Proj(paths)


@pytest.fixture
def grouped_copy(groupedproj: Proj, tmp_path: Path) -> ProjectPaths:
    root = tmp_path / "grouped"
    copy_project(groupedproj.paths.root, root)
    return ProjectPaths(root)


@pytest.fixture
def collect() -> Callable[..., tuple[list[str], Emit]]:
    def _run(paths: ProjectPaths, **kw: Any) -> tuple[list[str], Emit]:
        lines: Emit = []
        failed = run_clean(paths, emit=lines.append, **kw)
        return failed, lines

    return _run


# -- GT matching ---------------------------------------------------------------------------


def parse_exact(
    name: str, blocks: Sequence[Block]
) -> tuple[list[tuple[dict[str, Any], Block]], int]:
    """GT block <-> parsed block: same page and NFC(raw_lines joined) == NFC(raw_text).
    Returns the pairs and the number of GT blocks without such a partner."""
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    pairs: list[tuple[dict[str, Any], Block]] = []
    missing = 0
    for g in gt(name)["blocks"]:
        want = nfc("\n".join(g["raw_lines"]))
        hit = [b for b in by_page.get(g["page"], []) if nfc(b.raw_text) == want]
        if hit:
            pairs.append((g, hit[0]))
        else:
            missing += 1
    return pairs, missing


def text_match(g: dict[str, Any], blocks: Sequence[Block], floor: float = 0.8) -> Block | None:
    """The parsed block on the GT block's page whose text matches it best (parse-exact first;
    otherwise the best SequenceMatcher ratio over whitespace-collapsed text, >= floor)."""
    want = " ".join(nfc(g["text"]).split())
    best: tuple[float, str] | None = None
    found: dict[str, Block] = {}
    for b in blocks:
        if b.page != g["page"] or b.type in (BlockType.header, BlockType.footer, BlockType.figure):
            continue
        have = " ".join(nfc(b.raw_text).split())
        r = 1.0 if have == want else SequenceMatcher(None, have, want, autojunk=False).ratio()
        found[b.id] = b
        if best is None or (r, b.id) > best:
            best = (r, b.id)
    if best is None or best[0] < floor:
        return None
    return found[best[1]]


# -- synthetic builders ----------------------------------------------------------------------


def mk(
    page: int,
    n: int,
    text: str = "Some text.",
    type: BlockType = BlockType.paragraph,
    *,
    ro: int | None = None,
    slug: str = SLUG,
    **kw: Any,
) -> Block:
    if type == BlockType.figure:
        kw.setdefault("figure_id", ids.figure_id(slug, page, n))
    texts = kw.pop("texts", {"pymupdf": text, "docling": text})
    return Block(
        id=ids.block_id(slug, page, n),
        doc_id=slug,
        page=page,
        bbox=kw.pop("bbox", [0, 0, 10, 10]),
        type=type,
        reading_order=page * 1000 + n if ro is None else ro,
        raw_text=text,
        raw_source=kw.pop("source", "pymupdf"),
        raw_text_by_parser=texts,
        **kw,
    )


def doc_of(blocks: Sequence[Block], slug: str = SLUG, **kw: Any) -> Document:
    return Document(
        slug=slug,
        sha256="a" * 64,
        filename=f"{slug}.pdf",
        kind=DocKind.born_digital_pdf,
        page_count=max((b.page for b in blocks), default=1),
        block_ids=[b.id for b in blocks],
        parser_versions={"pymupdf": "x", "docling": "y"},
        **kw,
    )


def group(view: GroupView, n: int, slug_: str, block_ids: Sequence[str], slug: str = SLUG) -> Group:
    return Group.model_construct(
        id=ids.group_id(slug, view.value, n),
        view=view,
        doc_id=slug,
        title=slug_,
        slug=slug_,
        block_ids=list(block_ids),
        is_unassigned=n == 0 and view == GroupView.topic,
    )


def gf_of(
    sections: Sequence[Sequence[str]], topics: Sequence[tuple[str, Sequence[str]]], slug: str = SLUG
) -> GroupsFile:
    """A GroupsFile with just what attachment reads (structure and topic membership)."""
    structure = [
        group(GroupView.structure, i + 1, f"s{i + 1}", s, slug) for i, s in enumerate(sections)
    ]
    tops = [group(GroupView.topic, i + 1, t, b, slug) for i, (t, b) in enumerate(topics)]
    return GroupsFile.model_construct(doc_id=slug, structure=structure, topics=tops)


def det(text: str, type: BlockType = BlockType.paragraph, **ctx: Any) -> str:
    """The composed deterministic passes on one text (no check)."""
    hf = ctx.pop("hf", None)
    pctx = PassCtx(
        block_type=type,
        page=ctx.pop("page", 1),
        hf=hf_tables(hf or ()),
        lexicon=ctx.pop("lexicon", Lexicon()),
        table=ctx.pop("table", None),
    )
    return compose(text, plan_passes(type, pctx.table is not None), pctx).text
