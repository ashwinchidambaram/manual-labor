"""Protocols that cross the A/B boundary (design 07 section 11.2), plus `open_project`.

`B` codes and tests against fakes implementing these; the real classes live in
`manuallabor.state.{review,scope,figures,learning}` and `manuallabor.jobs.runner`."""

from __future__ import annotations

import builtins
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from manuallabor.cleanup.types import AttachOverride
from manuallabor.contracts.enums import FlagStatus
from manuallabor.contracts.flag import Flag
from manuallabor.contracts.group import GroupOverride
from manuallabor.contracts.selection import ScopeSummary
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import Clock, utc_now
from manuallabor.state.models import (
    ActionRecord,
    BlockDetail,
    Cursor,
    FigureRailItem,
    JobInfo,
    LearningState,
    QueuePage,
    QueueSort,
    RegroupIn,
    ReviewActionIn,
    ReviewActionOut,
    RunPlanIn,
    SelectionOp,
    SelectionOut,
    SnapshotInfo,
)

if TYPE_CHECKING:
    from manuallabor.jobs.providers import ProviderMode

__all__ = [
    "AppServices",
    "FigureServiceP",
    "JobRunnerP",
    "LearningServiceP",
    "ReviewServiceP",
    "ScopeServiceP",
    "StoreP",
    "open_project",
]


class ReviewServiceP(Protocol):
    def queue(
        self,
        sort: QueueSort | None,
        view_threshold: float | None,
        doc: str | None,
        limit: int,
        offset: int,
    ) -> QueuePage: ...
    def cursor(self) -> Cursor: ...
    def set_cursor(self, c: Cursor, request_id: str) -> Cursor: ...
    def detail(self, block_id: str) -> BlockDetail: ...  # NotFound -> 404, OutOfScope -> 422
    def act(self, a: ReviewActionIn) -> ReviewActionOut: ...  # EditConflictError -> 409
    def flags(self, status: FlagStatus | None) -> list[Flag]: ...
    def resolve_flag(self, flag_id: str, resolution: str, request_id: str) -> Flag: ...
    def render_page(self, slug: str, page: int, dpi: int) -> Path: ...  # NoPageRender -> 404
    def page_blocks(self, slug: str, page: int) -> list[dict[str, Any]]: ...


class ScopeServiceP(Protocol):
    def groups(self, doc: str | None) -> list[dict[str, Any]]: ...
    def get(self) -> SelectionOut: ...
    def apply(self, op: SelectionOp) -> SelectionOut: ...
    def summary(self) -> ScopeSummary: ...
    def regroup(self, r: RegroupIn) -> GroupOverride: ...
    def models(self) -> dict[str, Any]: ...
    def set_project_threshold(self, value: float, reason: str, request_id: str) -> float: ...


class FigureServiceP(Protocol):
    def rail(self, article_id: str) -> list[FigureRailItem]: ...
    def image_path(self, figure_id: str) -> Path: ...
    def attach(
        self, figure_id: str, article_id: str, anchor: str | None, request_id: str
    ) -> AttachOverride: ...
    def detach(self, figure_id: str, article_id: str, request_id: str) -> AttachOverride: ...
    def set_bbox(self, figure_id: str, bbox: list[float], request_id: str) -> None: ...


class LearningServiceP(Protocol):
    def state(self) -> LearningState: ...
    def set_flags(
        self,
        enabled: bool | None,
        use_global: bool | None,
        contribute_global: bool | None,
        request_id: str,
    ) -> LearningState: ...
    def snapshot(self, request_id: str) -> SnapshotInfo: ...
    def activate(self, snapshot_id: str, request_id: str) -> LearningState: ...
    def reset(self, request_id: str) -> LearningState: ...
    def disable_item(self, item_id: str, request_id: str) -> SnapshotInfo: ...
    def publish(self, snapshot_id: str, request_id: str) -> SnapshotInfo: ...


class JobRunnerP(Protocol):
    def enqueue(
        self, plan: RunPlanIn, kind: str = "run", files: Sequence[Path] = ()
    ) -> JobInfo: ...
    def get(self, job_id: str) -> JobInfo: ...
    def list(self, status: set[str] | None = None) -> builtins.list[JobInfo]: ...
    def cancel(self, job_id: str) -> JobInfo: ...
    def log(
        self, job_id: str, after_line: int, limit: int = 500
    ) -> builtins.list[dict[str, Any]]: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...


class StoreP(Protocol):
    def iter_actions(self) -> Iterator[ActionRecord]: ...
    def open_flag_count(self) -> int: ...
    def close(self) -> None: ...


@dataclass
class AppServices:
    paths: ProjectPaths
    store: StoreP
    review: ReviewServiceP
    scope: ScopeServiceP
    figures: FigureServiceP
    learning: LearningServiceP
    runner: JobRunnerP
    mock: bool


def open_project(
    paths: ProjectPaths,
    *,
    mode: ProviderMode,
    resume: bool,
    clock: Clock = utc_now,
) -> AppServices:
    """Open the store (migrate + reconcile) and build every service. The caller (serve.py)
    holds the project lock first. Does not start the runner."""
    from manuallabor.state.services import build_services

    return build_services(paths, mode=mode, resume=resume, clock=clock)
