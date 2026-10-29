"""Fixtures of the module 10 tests: a mock-scored copy of project-a (clean.pdf + figures.pdf),
the services over it, and a helper that runs the agent in-process."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from manuallabor.agent.pipeline import run_agent_plan
from manuallabor.agent.service import AgentService
from manuallabor.contracts.enums import Task
from manuallabor.contracts.llm import Message
from manuallabor.ingest import ingest_files
from manuallabor.jobs.inline import run_inline
from manuallabor.jobs.runner import JobRunner
from manuallabor.project import ProjectPaths
from manuallabor.providers import ListSink, MockProvider, ProviderSet
from manuallabor.providers.cache import LLMCache
from manuallabor.state.data import ProjectData
from manuallabor.state.figures import FigureService
from manuallabor.state.models import FlagIn, ReviewActionIn, RunPlanIn
from manuallabor.state.review import ReviewService
from manuallabor.state.scope import ScopeService
from manuallabor.state.store import Store
from tests.conftest import FIXTURES, labor_copy

NOW = datetime(2026, 1, 1, tzinfo=UTC)
Responder = Callable[[list[Message]], str]

# the five seeds of design test 1 (block ids of the mock-scored project-a)
SEEDS: list[tuple[str, str, str | None]] = [
    ("b-clean-p002-04", "wrong_text", None),  # clean numeric paragraph
    ("b-figures-p006-03", "wrong_text", None),  # figures paragraph
    ("b-clean-p004-04", "missing_figure", None),  # a figure two pages on is not attached
    ("b-figures-p003-04", "bad_crop", "FIG-figures-p003-01"),
    ("b-clean-p003-03", "wrong_grouping", None),
]


def fixed_clock() -> datetime:
    return NOW


@pytest.fixture(scope="session")
def project_a(requires_docling: None, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """project-a: clean.pdf + figures.pdf ingested, parsed, figure-extracted and scored with
    mock models. MANUALLABOR_TEST_TEMPLATE_A=<dir> reuses a prebuilt one (a dev shortcut)."""
    prebuilt = os.environ.get("MANUALLABOR_TEST_TEMPLATE_A")
    if prebuilt:
        return Path(prebuilt)
    root = tmp_path_factory.mktemp("project-a") / "proj"
    root.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "project-a" / "project.json", root / "project.json")
    paths = ProjectPaths(root)
    ingest_files(paths, [FIXTURES / "clean.pdf", FIXTURES / "figures.pdf"], emit=lambda _o: None)
    store = Store.open(paths)
    res = run_inline(paths, RunPlanIn(to="score2"), mode="mock", emit=lambda _o: None, store=store)
    store.close()
    assert res.ok
    for p in (root / "project.db", root / "project.db-wal", root / "project.db-shm"):
        p.unlink(missing_ok=True)
    return root


class AEnv:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.store = Store.open(paths, clock=fixed_clock)
        self.data = ProjectData(paths, self.store)
        self.figures = FigureService(paths, self.store, self.data)
        self.review = ReviewService(paths, self.store, self.data, self.figures)
        self.scope = ScopeService(paths, self.store, self.data)
        self.runner = JobRunner(paths, self.store, mode="mock")
        self.agent = AgentService(
            paths, self.store, self.data, self.review, self.figures, self.scope, self.runner
        )
        self.sink = ListSink()
        self.n = 0

    def rid(self) -> str:
        self.n += 1
        return f"t-{self.n}"

    def flag(
        self, block_id: str, category: str, target: str | None = None, note: str = "seeded"
    ) -> str:
        out = self.review.act(
            ReviewActionIn(
                kind="flag",
                block_id=block_id,
                flag=FlagIn(category=category, target_id=target, note=note),  # type: ignore[arg-type]
                request_id=self.rid(),
            )
        )
        assert out.flag is not None
        return out.flag.id

    def seed(self, which: list[int] | None = None) -> list[str]:
        rows = SEEDS if which is None else [SEEDS[i] for i in which]
        return [self.flag(b, c, t) for b, c, t in rows]

    def providers(
        self,
        responses: Mapping[Task, str | Responder] | None = None,
        vision: Callable[[bytes, str], str] | None = None,
    ) -> ProviderSet:
        cache = LLMCache(self.paths.root / ".llm_cache")
        by_task: dict[Task, Any] = {}
        for t in Task:
            by_task[t] = MockProvider(
                sink=self.sink,
                cache=cache,
                clock=fixed_clock,
                responses=responses,
                vision_response=vision if t == Task.vision else None,
            )
        return ProviderSet(by_task=by_task)

    def run_agent(
        self,
        responses: Mapping[Task, str | Responder] | None = None,
        *,
        vision: Callable[[bytes, str], str] | None = None,
        docs: list[str] | None = None,
        flag_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        plan, _skips = self.agent.plan(docs, flag_ids)
        events: list[dict[str, Any]] = []

        def emit(o: dict[str, Any]) -> None:
            events.append(o)
            if o.get("event") in ("proposal", "agent_outcome"):
                self.agent.ingest_event("job-x", o)

        ps = self.providers(responses, vision)
        run_agent_plan(self.paths, plan.model_dump(mode="json"), lambda: ps, emit, lambda: False)
        return events

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def aenv(project_a: Path, tmp_path: Path) -> Any:
    root = labor_copy(project_a, tmp_path / "proj")
    e = AEnv(ProjectPaths(root))
    yield e
    e.close()
    shutil.rmtree(tmp_path, ignore_errors=True)
