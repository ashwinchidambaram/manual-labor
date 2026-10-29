"""Request dependencies: the application services and injectable hooks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request

from manuallabor.api.errors import ApiError
from manuallabor.contracts.probe import ProbeResult
from manuallabor.project import ProjectPaths
from manuallabor.state.interfaces import AppServices, JobRunnerP
from manuallabor.state.models import ProjectStatus

StatusFn = Callable[[ProjectPaths, JobRunnerP | None], ProjectStatus]
ProbeFn = Callable[[ProjectPaths], ProbeResult]


def _default_status(paths: ProjectPaths, runner: JobRunnerP | None) -> ProjectStatus:
    from manuallabor.jobs.graph import project_status

    return project_status(paths, runner)


def _default_probe(paths: ProjectPaths) -> ProbeResult:
    from manuallabor.providers.probe import run_probe

    return run_probe(path=paths.root)


@dataclass
class Hooks:
    """Injectable seams (tests replace them; production uses the defaults)."""

    status: StatusFn = field(default=_default_status)
    probe: ProbeFn = field(default=_default_probe)


def get_ctx(request: Request) -> AppServices:
    ctx: AppServices | None = request.app.state.ctx
    if ctx is None:
        raise ApiError(503, "no_project", "no project is open")
    return ctx


def get_hooks(request: Request) -> Hooks:
    hooks: Hooks = request.app.state.hooks
    return hooks


Ctx = Annotated[AppServices, Depends(get_ctx)]
HooksDep = Annotated[Hooks, Depends(get_hooks)]
