"""File-backed project data for the worker (no database) and the shared per-item facts.

The worker has no DB access (design 07 section 4), so it reads the same files the stages read;
the selection comes from its projection (`selection.json`). The service side passes its own
`ProjectData`; both produce identical facts because the projections are exact."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, cast

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import canonical_json, read_json
from manuallabor.project import ProjectPaths
from manuallabor.state.data import ProjectData
from manuallabor.state.store import Store

__all__ = [
    "FigureFacts",
    "file_data",
    "figure_facts",
    "file_sha",
    "find_block",
    "target_slug",
]


class _FileStore:
    """The one thing `ProjectData` reads from the store: the selection body."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    def get_selection_json(self) -> str | None:
        p = self.paths.selection
        return p.read_text(encoding="utf-8") if p.is_file() else None


def file_data(paths: ProjectPaths) -> ProjectData:
    """A `ProjectData` over the project files only (the worker's view)."""
    return ProjectData(paths, cast(Store, _FileStore(paths)))


def file_sha(path: Any) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def target_slug(target_id: str) -> str:
    return (
        ids.parse_figure_id(target_id)[0]
        if target_id.startswith("FIG-")
        else (ids.parse_block_id(target_id)[0])
    )


def find_block(data: ProjectData, slug: str, block_id: str) -> Block | None:
    for b in data.machine_blocks(slug):
        if b.id == block_id:
            return b
    return None


@dataclass(frozen=True)
class FigureFacts:
    figure_id: str
    block: Block
    record: FigureRecord | None
    bbox: list[float] | None  # the crop in force: latest human override, else the sidecar's


def figure_facts(paths: ProjectPaths, data: ProjectData, figure_id: str) -> FigureFacts | None:
    slug = ids.parse_figure_id(figure_id)[0]
    block = next(
        (
            b
            for b in data.raw_blocks(slug)
            if b.type == BlockType.figure and b.figure_id == figure_id
        ),
        None,
    )
    if block is None:
        return None
    sc = paths.figure_file(slug, figure_id, "json")
    rec = read_json(sc, FigureRecord) if sc.is_file() else None
    from manuallabor.figures.pipeline import load_bbox_overrides

    human = load_bbox_overrides(paths.doc(slug)).get(figure_id)
    bbox = human if human is not None else (rec.bbox if rec is not None else block.bbox)
    return FigureFacts(figure_id, block, rec, None if bbox is None else [float(v) for v in bbox])


def canon(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()
