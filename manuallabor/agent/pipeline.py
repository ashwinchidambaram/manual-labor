"""Run the agent over a plan of items (design 10 section 3.8): the worker's job body and the
`labor agent` CLI use the same function, so both produce the same events."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from manuallabor import faults
from manuallabor.agent.data import file_data
from manuallabor.agent.inputs import (
    DocEmbeddings,
    RunCache,
    basis_sha256,
    build_input,
    load_hints,
    load_learned_agent,
)
from manuallabor.agent.propose import Reply, propose
from manuallabor.agent.recheck import resolve_payload, run_rechecks
from manuallabor.agent.types import AgentItem, AgentOutcome, AgentPlan
from manuallabor.agent.vision_reader import crop_block_png, read_numbers, skip_reason, skipped
from manuallabor.calibration.types import LearnedAgent
from manuallabor.contracts.block import VisionReading
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.enums import FlagCategory, Task
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import ProviderError, ProviderSet
from manuallabor.scoring.faithfulness import numeric_tokens
from manuallabor.state.data import ProjectData

__all__ = ["process_item", "run_agent_plan"]

Emit = Callable[[dict[str, Any]], None]


def _vision(
    paths: ProjectPaths,
    data: ProjectData,
    cfg: ProjectConfig,
    item: AgentItem,
    providers: ProviderSet,
) -> VisionReading | None:
    """The vision reader's transcript, only for the categories that read numbers."""
    if item.category not in (FlagCategory.wrong_text, FlagCategory.table_structure):
        return None
    block = next((b for b in data.machine_blocks(item.doc_id) if b.id == item.target_id), None)
    if block is None:
        return None
    doc = data.document(item.doc_id)
    why = skip_reason(block, doc.kind, item.category, cfg)
    if why is not None:
        return skipped(why)
    assert block.bbox is not None
    try:
        png = crop_block_png(paths.source(doc.filename), block.page, block.bbox)
        provider = providers.get(Task.vision)
    except (ProviderError, OSError, KeyError) as exc:
        return VisionReading(outcome="error", detail=str(exc)[:300])
    return read_numbers(provider, png, len(numeric_tokens(block.raw_text)))


def process_item(
    paths: ProjectPaths,
    data: ProjectData,
    cfg: ProjectConfig,
    item: AgentItem,
    providers: ProviderSet,
    learned: LearnedAgent | None,
    hints: list[str],
    cache: RunCache,
) -> dict[str, Any]:
    """One item -> one event: `proposal` (with its rechecks) or `agent_outcome`."""

    def outcome(o: AgentOutcome) -> dict[str, Any]:
        return {
            "event": "agent_outcome",
            "flag_id": o.flag_id,
            "round": o.round,
            "outcome": o.outcome,
            "detail": o.detail,
        }

    kind_is_regroup = item.category == FlagCategory.wrong_grouping
    emb_cell: list[DocEmbeddings | None] = []

    def emb_for() -> DocEmbeddings | None:
        if not emb_cell:
            emb_cell.append(cache.get(paths, data, providers, item.doc_id))
        return emb_cell[0]

    try:
        vision = _vision(paths, data, cfg, item, providers)
        inp = build_input(
            paths,
            data,
            cfg,
            item,
            vision=vision,
            emb=emb_for() if kind_is_regroup else None,
            learned=learned,
            hints=hints,
        )
        reply = propose(inp, providers)
        if not isinstance(reply, Reply):
            return outcome(reply)
        res = resolve_payload(inp, reply.payload, paths, data)
        rechecks = run_rechecks(inp, res, reply.evidence, paths, data, emb_for)
        basis = basis_sha256(paths, data, item.target_id, inp.kind, item.current_text, vision)
    except ProviderError as exc:
        return outcome(AgentOutcome(item.flag_id, item.round, "error", str(exc)[:300]))
    except Exception as exc:  # one bad item must not stop the pass
        return outcome(
            AgentOutcome(item.flag_id, item.round, "error", f"{type(exc).__name__}: {exc}"[:300])
        )
    draft: dict[str, Any] = {
        "flag_id": item.flag_id,
        "target_id": item.target_id,
        "round": item.round,
        "kind": inp.kind.value,
        **res.fields,
        "evidence": [e.model_dump(mode="json") for e in reply.evidence],
        "rationale": reply.rationale,
        "rechecks": [r.model_dump(mode="json") for r in rechecks],
        "history": [p.model_dump(mode="json") for p in item.priors],
        "vision": vision.model_dump(mode="json") if vision is not None else None,
        "basis_sha256": basis,
        "model": reply.model,
        "input_hash": reply.input_hash,
    }
    return {"event": "proposal", "plan_basis": item.basis_sha256, "draft": draft}


def run_agent_plan(
    paths: ProjectPaths,
    plan: dict[str, Any],
    providers: Callable[[], ProviderSet],
    emit: Emit,
    cancelled: Callable[[], bool],
) -> int:
    """Process the plan's items in order; returns the number of items that ended in an error
    outcome. Raises `Cancelled` between items (and at LLM calls through the heartbeat sink)."""
    from manuallabor.jobs.executor import Cancelled

    cfg = paths.load_config()
    data = file_data(paths)
    items = AgentPlan.model_validate(plan).items
    emit({"event": "job_start", "units": len(items)})
    learned = load_learned_agent(paths, cfg)
    hints = load_hints(paths, cfg)
    cache = RunCache()
    errors = 0
    for n, item in enumerate(items, 1):
        if cancelled():
            raise Cancelled()
        ev = process_item(paths, data, cfg, item, providers(), learned, hints, cache)
        if ev.get("outcome") == "error":
            errors += 1
        emit(ev)
        emit(
            {
                "event": "unit_done",
                "node": "agent",
                "doc": item.doc_id,
                "status": ev.get("outcome", "proposal"),
            }
        )
        faults.fault(f"agent.after_items:{n}")
    return errors


def fixed_now() -> str | None:
    """MANUALLABOR_FIXED_NOW pins the store clock of `labor agent` (reproducibility tests)."""
    return os.environ.get("MANUALLABOR_FIXED_NOW")


def run_agent_inline(
    paths: ProjectPaths,
    store: Any,
    *,
    mode: str,
    docs: list[str] | None,
    emit: Emit,
    echo: bool = True,
    flag_ids: list[str] | None = None,
) -> int:
    """`labor agent`: the same plan and events as the worker job, in this process. The caller
    holds both project locks. Exit code 0 unless an item errored."""
    from manuallabor.agent.service import AgentService
    from manuallabor.jobs.executor import Heartbeat
    from manuallabor.jobs.providers import provider_set_factory
    from manuallabor.providers.sinks import JsonlSink
    from manuallabor.state.figures import FigureService
    from manuallabor.state.review import ReviewService
    from manuallabor.state.scope import ScopeService

    data = ProjectData(paths, store)
    figures = FigureService(paths, store, data)
    review = ReviewService(paths, store, data, figures)
    scope = ScopeService(paths, store, data)

    class _NoRunner:
        def enqueue(self, *a: Any, **k: Any) -> Any:
            return None

    svc = AgentService(paths, store, data, review, figures, scope, _NoRunner())  # type: ignore[arg-type]
    plan, skips = svc.plan(docs, flag_ids)
    if echo:
        for s in skips:
            print(f"skipped {s.flag_id}: {s.outcome}" + (f" ({s.detail})" if s.detail else ""))
    if not plan.items:
        if echo:
            print(svc.no_items_detail(skips))
        return 0
    cfg = paths.load_config()
    hb = Heartbeat(JsonlSink(paths.llm_log))
    providers = provider_set_factory(paths, cfg, mode, hb)  # type: ignore[arg-type]
    job_id = store.add_job(kind="agent", plan={**plan.model_dump(mode="json"), "origin": "cli"})
    store.update_job(job_id, status="running", pid=os.getpid(), started_at=store.now())
    status, error = "done", None

    def handle(o: dict[str, Any]) -> None:
        if o.get("event") in ("proposal", "agent_outcome"):
            svc.ingest_event(job_id, o)
            if echo:
                _print_event(o)
        emit(o)

    try:
        errors = run_agent_plan(
            paths, plan.model_dump(mode="json"), providers, handle, lambda: False
        )
        if errors:
            status, error = "failed", f"{errors} item(s) ended in an error"
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        fields: dict[str, Any] = {"status": status, "finished_at": store.now(), "error": error}
        if status == "done":
            fields["progress"] = 1.0
        store.update_job(job_id, **fields)
    return 0


def _print_event(o: dict[str, Any]) -> None:
    if o["event"] == "agent_outcome":
        print(f"{o['flag_id']} round {o['round']}: {o['outcome']} {o.get('detail') or ''}".rstrip())
        return
    d = o["draft"]
    checks = ", ".join(f"{r['check']}={'ok' if r['passed'] else 'FAIL'}" for r in d["rechecks"])
    print(f"{d['flag_id']} round {d['round']}: proposal ({d['kind']}) [{checks}]")
