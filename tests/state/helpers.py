"""Shared helpers for the state tests."""

from __future__ import annotations

from manuallabor.contracts.block import Block
from manuallabor.project import ProjectPaths
from manuallabor.state.data import ProjectData
from manuallabor.state.figures import FigureService
from manuallabor.state.models import ReviewActionIn
from manuallabor.state.review import ReviewService, load_review_blocks
from manuallabor.state.scope import ScopeService
from manuallabor.state.store import Store


class Env:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.store = Store.open(paths)
        self.data = ProjectData(paths, self.store)
        self.figures = FigureService(paths, self.store, self.data)
        self.review = ReviewService(paths, self.store, self.data, self.figures)
        self.scope = ScopeService(paths, self.store, self.data)
        self.n = 0

    def rid(self) -> str:
        self.n += 1
        return f"t-{self.n}"

    def act(self, kind: str, block_id: str | None = None, **kw: object):  # type: ignore[no-untyped-def]
        return self.review.act(
            ReviewActionIn(kind=kind, block_id=block_id, request_id=self.rid(), **kw)  # type: ignore[arg-type]
        )

    def blocks(self, slug: str) -> list[Block]:
        return load_review_blocks(self.paths, self.store, slug)

    def close(self) -> None:
        self.store.close()
