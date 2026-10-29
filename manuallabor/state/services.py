"""Service assembly: the real implementations behind the Protocols of interfaces.py."""

from __future__ import annotations

from manuallabor.jobs.providers import ProviderMode
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import Clock
from manuallabor.state.data import ProjectData
from manuallabor.state.figures import FigureService
from manuallabor.state.interfaces import AppServices
from manuallabor.state.learning import LearningService
from manuallabor.state.review import ReviewService
from manuallabor.state.scope import ScopeService
from manuallabor.state.store import Store

__all__ = ["build_services"]


def build_services(
    paths: ProjectPaths, *, mode: ProviderMode, resume: bool, clock: Clock
) -> AppServices:
    from manuallabor.jobs.runner import JobRunner

    paths.ensure_config()
    store = Store.open(paths, clock=clock)
    data = ProjectData(paths, store)
    figures = FigureService(paths, store, data)
    review = ReviewService(paths, store, data, figures)
    scope = ScopeService(paths, store, data)
    learning = LearningService(paths, store)
    runner = JobRunner(paths, store, mode=mode, resume=resume)
    from manuallabor.agent.service import AgentService
    from manuallabor.calibration.apply import CalibrationService

    agent = AgentService(paths, store, data, review, figures, scope, runner)
    for ev in ("proposal", "agent_outcome"):
        runner.event_handlers[ev] = agent.ingest_event
    calibration = CalibrationService(paths, store, data, runner)
    return AppServices(
        paths=paths,
        store=store,
        review=review,
        scope=scope,
        figures=figures,
        learning=learning,
        runner=runner,
        mock=mode == "mock",
        agent=agent,
        calibration=calibration,
    )
