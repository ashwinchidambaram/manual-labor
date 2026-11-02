"""A failed stage never counts as fresh (design 07 section 19, first-time user run 5).

With the model service down, `group` wrote a degraded groups.json under the current
fingerprint; every later run then skipped it as "up to date" and failed again, so a manual
could never be re-grouped once the service came back."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from manuallabor.cleanup.describe import describe_figure
from manuallabor.contracts.enums import Task
from manuallabor.contracts.io import write_json
from manuallabor.contracts.llm import Message
from manuallabor.grouping.label import name_topic, review_stragglers
from manuallabor.grouping.pipeline import _group_fp, group_document_ex
from manuallabor.jobs import graph
from manuallabor.jobs.executor import Plan, execute, make_plan
from manuallabor.project import ProjectPaths
from manuallabor.providers import ListSink, MockProvider, ProviderError, ProviderSet
from manuallabor.providers.base import ProviderUnavailable, RawEmbed, build_provider_set
from manuallabor.scoring.pipeline import load_scored_blocks
from manuallabor.scoring.verifier import llm_verifier, plan_verifier
from tests.cleanup.conftest import mk
from tests.cleanup.test_verify import run as clean_run
from tests.grouping.test_topics import _items
from tests.scoring.test_verifier import NCLEAN, NRAW, VERIFIER, _config

DOC = "clean"
REFUSED = (
    "APIConnectionError: litellm.APIConnectionError: OllamaException - "
    "[Errno 61] Connection refused"
)


class _DownEmbed(MockProvider):
    """Embeddings that fail the way a stopped service makes them fail."""

    def __init__(self, *a: Any, error: ProviderError, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.error = error

    def _embed_raw(self, task: Task, texts: Sequence[str]) -> RawEmbed:
        raise self.error


def _providers(paths: ProjectPaths, embed_error: ProviderError | None = None) -> ProviderSet:
    base = build_provider_set(paths.load_config(), cache_dir=None, sink=ListSink())
    if embed_error is None:
        return base
    by_task = dict(base.by_task)
    by_task[Task.embeddings] = _DownEmbed(
        base.get(Task.embeddings).ref, sink=ListSink(), error=embed_error
    )
    return ProviderSet(by_task=by_task)


def _run(
    paths: ProjectPaths, units: list[tuple[str, str]], ps: ProviderSet, force: Sequence[str] = ()
) -> tuple[Any, list[dict[str, Any]]]:
    lines: list[dict[str, Any]] = []
    res = execute(
        paths, Plan(units=units, to=units[-1][0], force=list(force)), emit=lines.append,
        providers=lambda: ps,
    )  # fmt: skip
    return res, lines


def _state(paths: ProjectPaths, node: str, slug: str = DOC) -> graph.NodeState:
    return next(
        s for s in graph.doc_node_states(paths, slug, paths.load_config()) if s.node == node
    )


def test_a_topic_failure_writes_no_groups_file_and_records_the_real_error(lp: ProjectPaths) -> None:
    lp.doc(DOC).groups.unlink()
    res, lines = _run(lp, [("group", DOC)], _providers(lp, ProviderError("embeddings broke")))
    assert not res.ok
    assert not lp.doc(DOC).groups.exists()
    rec = graph.load_stages(lp, DOC).nodes["group"]
    assert rec.status == "failed" and rec.error is not None and "embedding failed" in rec.error
    assert res.errors and "embedding failed" in res.errors[0]
    assert _state(lp, "group").state == "failed"


def test_a_topic_failure_keeps_an_earlier_good_grouping(lp: ProjectPaths) -> None:
    before = lp.doc(DOC).groups.read_bytes()
    res, _ = _run(
        lp, [("group", DOC)], _providers(lp, ProviderError("embeddings broke")), force=["group"]
    )
    assert not res.ok
    assert lp.doc(DOC).groups.read_bytes() == before


def _write_degraded_groups(paths: ProjectPaths) -> None:
    """The human-test-3 shape: groups.json written by the failed attempt (topic_status failed)
    under the current fingerprint, and a `failed` record in stages.json."""
    cfg = paths.load_config()
    fp, params, learned = _group_fp(paths, DOC, cfg)
    gf, _ = group_document_ex(
        paths.load_document(DOC),
        load_scored_blocks(paths, DOC),
        _providers(paths, ProviderError(REFUSED)),
        params=params,
        learned=learned,
        fingerprint_hex=fp,
    )
    assert gf.topic_status == "failed" and gf.fingerprint == fp
    write_json(paths.doc(DOC).groups, gf)
    st = graph.load_stages(paths, DOC)
    st.record("group", "failed", None, "stage failed")
    graph.save_stages(paths, DOC, st)


def test_a_failed_record_over_a_current_output_is_re_executed(lp: ProjectPaths) -> None:
    _write_degraded_groups(lp)
    assert _state(lp, "group").state == "failed"
    plan = make_plan(lp, lp.load_config(), to="group")
    assert ("group", DOC) in plan.units
    lines: list[dict[str, Any]] = []
    good = _providers(lp)
    res = execute(lp, plan, emit=lines.append, providers=lambda: good)
    group_lines = [o for o in lines if o.get("stage") == "group" and o.get("doc") == DOC]
    assert group_lines and not [o for o in group_lines if o.get("status") == "skip"], group_lines
    assert res.ok, res.errors
    assert '"topic_status": "ok"' in lp.doc(DOC).groups.read_text(encoding="utf-8")
    assert _state(lp, "group").state == "fresh"


def test_re_run_succeeds_once_the_provider_is_back(lp: ProjectPaths) -> None:
    lp.doc(DOC).groups.unlink()
    down = _providers(lp, ProviderUnavailable(REFUSED))
    res, _ = _run(lp, [("group", DOC)], down)
    assert not res.ok and not lp.doc(DOC).groups.exists()
    assert "Connection refused" in (graph.load_stages(lp, DOC).nodes["group"].error or "")
    plan = make_plan(lp, lp.load_config(), to="group")
    good = _providers(lp)
    res = execute(lp, plan, emit=lambda _o: None, providers=lambda: good)
    assert res.ok, res.errors
    assert _state(lp, "group").state == "fresh"


# -- a transport failure is never an answer (section 19 rule 2) -----------------------------


def _down(_m: Sequence[Message]) -> str:
    raise ProviderUnavailable(REFUSED)


def test_the_cleanup_model_being_unreachable_fails_the_block() -> None:
    prov = MockProvider(sink=ListSink(), responses={Task.cleanup: _down})
    with pytest.raises(ProviderUnavailable):
        clean_run(mk(1, 1, "Check the belt and the pulley."), provider=prov, mode="always")


def test_an_answer_error_still_falls_back_in_cleanup() -> None:
    def broke(_m: Sequence[Message]) -> str:
        raise ProviderError("the model said something odd")

    prov = MockProvider(sink=ListSink(), responses={Task.cleanup: broke})
    r = clean_run(mk(1, 1, "Check the belt and the pulley."), provider=prov, mode="always")
    assert r.entry.llm is not None and r.entry.llm.outcome == "error"


def test_the_vision_model_being_unreachable_fails_describe() -> None:
    def down(_img: bytes, _p: str) -> str:
        raise ProviderUnavailable(REFUSED)

    with pytest.raises(ProviderUnavailable):
        describe_figure(MockProvider(sink=ListSink(), vision_response=down), b"\x89PNG", None)


def test_the_verifier_being_unreachable_fails_scoring(tmp_path: Path) -> None:
    prov = MockProvider(sink=ListSink(), responses={Task.verifier: _down})
    plan = plan_verifier(_config(VERIFIER), lambda: ProviderSet(by_task={Task.verifier: prov}))
    with pytest.raises(ProviderUnavailable):
        llm_verifier(NRAW, NCLEAN, faith_passed=True, plan=plan)


def test_the_namer_and_straggler_review_being_unreachable_fail_grouping() -> None:
    chat = MockProvider(sink=ListSink(), responses={Task.grouping: _down})
    with pytest.raises(ProviderUnavailable):
        name_topic(chat, ["Belt"], ["s1"], number=1)
    with pytest.raises(ProviderUnavailable):
        review_stragglers(chat, [("c01", "A"), ("c02", "B")], _items())


# -- the provider tells a refused connection from other errors -------------------------------


class APIConnectionError(Exception):  # the name LiteLLM gives it
    pass


class NotFoundError(Exception):
    status_code = 404


def _ollama() -> Any:
    from manuallabor.contracts.config import ModelRef
    from manuallabor.providers.registry import make_factory

    p = make_factory("ollama")(
        ModelRef(provider="ollama", model="llama3.2:1b", api_base="http://127.0.0.1:9"),
        ListSink(),
        None,
        lambda: None,  # type: ignore[arg-type,return-value]
    )
    p._sleep = lambda _s: None
    return p


def test_a_refused_connection_is_provider_unavailable() -> None:
    p = _ollama()

    def go() -> None:
        raise APIConnectionError(
            "litellm.APIConnectionError: OllamaException - [Errno 61] Connection refused"
        )

    with pytest.raises(ProviderUnavailable):
        p._call(go)


def test_a_missing_model_is_not_provider_unavailable() -> None:
    p = _ollama()

    def go() -> None:
        raise NotFoundError("model 'llama3.2:1b' not found")

    with pytest.raises(ProviderError) as ei:
        p._call(go)
    assert not isinstance(ei.value, ProviderUnavailable)
