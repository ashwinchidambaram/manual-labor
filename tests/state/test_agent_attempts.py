"""The flag card's "tried N times" (design 09 section 11): an agent pass that ends in an error
leaves no proposal, so `round` stays 1; `attempts` still counts it."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from manuallabor.agent.service import AgentService
from manuallabor.contracts.enums import BlockType
from manuallabor.project import ProjectPaths
from manuallabor.state.models import FlagIn, JobInfo, ReviewActionIn, RunPlanIn
from tests.state.helpers import Env


class _Runner:
    """Records enqueued agent plans; nothing runs."""

    def __init__(self) -> None:
        self.n = 0

    def _job(self, kind: str) -> JobInfo:
        self.n += 1
        return JobInfo(
            id=f"job-{self.n:06d}", kind=kind, status="queued", created_at=datetime.now(UTC)
        )

    def enqueue(self, plan: RunPlanIn, kind: str = "run", files: Sequence[Any] = ()) -> JobInfo:
        return self._job(kind)

    def enqueue_raw(self, plan: dict[str, Any], kind: str) -> JobInfo:
        return self._job(kind)

    def get(self, job_id: str) -> JobInfo:
        return self._job("agent")


@pytest.fixture
def env(lp: ProjectPaths) -> Iterator[tuple[Env, AgentService]]:
    e = Env(lp)
    agent = AgentService(lp, e.store, e.data, e.review, e.figures, e.scope, _Runner())
    yield e, agent
    e.close()


def test_two_passes_that_ended_in_errors_count_as_two_attempts(
    env: tuple[Env, AgentService],
) -> None:
    e, agent = env
    block = next(
        b for b in e.blocks("clean") if b.type == BlockType.paragraph and b.has_numeric_spec
    )
    out = e.review.act(
        ReviewActionIn(
            kind="flag",
            block_id=block.id,
            flag=FlagIn(category="wrong_text", note="torque looks wrong"),
            request_id=e.rid(),
        )
    )
    assert out.flag is not None
    fid = out.flag.id
    (fresh,) = [i for i in agent.items() if i.flag.id == fid]
    assert (fresh.attempts, fresh.round, fresh.last_outcome) == (0, 1, None)

    for _ in range(2):
        agent.enqueue(None, None, e.rid())
        agent.ingest_event(
            "job",
            {
                "event": "agent_outcome",
                "flag_id": fid,
                "outcome": "error",
                "detail": "proposal_text is missing",
                "round": 1,
            },
        )
    (item,) = [i for i in agent.items() if i.flag.id == fid]
    assert item.round == 1, "an error leaves no proposal: the next pass is still round 1"
    assert item.attempts == 2
    assert (item.last_outcome, item.last_detail) == ("error", "proposal_text is missing")
