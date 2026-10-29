"""Run a plan in the current process (`labor run`, `labor check`): same executor as the
worker, with a `jobs` row so the history shows CLI runs too. The caller holds the locks."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from manuallabor.contracts.enums import Task
from manuallabor.jobs.executor import Cancelled, ExecResult, Heartbeat, execute, make_plan
from manuallabor.jobs.providers import ProviderMode, provider_set_factory
from manuallabor.project import ProjectPaths
from manuallabor.providers.sinks import JsonlSink
from manuallabor.state.models import RunPlanIn
from manuallabor.state.store import Store

__all__ = ["run_inline"]


def run_inline(
    paths: ProjectPaths,
    plan_in: RunPlanIn,
    *,
    mode: ProviderMode,
    emit: Callable[[dict[str, Any]], None],
    store: Store,
    files: Sequence[Path] = (),
    include_fresh: bool = False,
) -> ExecResult:
    cfg = paths.ensure_config()
    hb = Heartbeat(JsonlSink(paths.llm_log))
    providers = provider_set_factory(paths, cfg, mode, hb)
    job_id = store.add_job(kind="run", plan={**plan_in.model_dump(mode="json"), "origin": "cli"})
    store.update_job(job_id, status="running", pid=os.getpid(), started_at=store.now())
    status, error = "done", None
    res = ExecResult()
    try:
        if files:
            from manuallabor.ingest import ingest_files

            provider = providers().get(Task.metadata) if mode == "mock" else None
            ingest_files(paths, list(files), provider=provider, emit=emit)
        plan = make_plan(
            paths,
            paths.load_config(),
            to=plan_in.to,
            docs=plan_in.docs,
            force=set(plan_in.force),
            allow_reparse=plan_in.allow_reparse,
            provider_mode=mode,
            include_fresh=include_fresh,
        )
        total = len(plan.units)
        store.update_job(job_id, units_total=total)
        done = [0]

        def on_unit(node: str, doc: str, st: str) -> None:
            done[0] += 1
            store.update_job(
                job_id,
                units_done=done[0],
                progress=min(1.0, done[0] / total) if total else 1.0,
                node=node,
                doc=doc,
            )

        res = execute(paths, plan, emit=emit, providers=providers, heartbeat=hb, on_unit=on_unit)
        if not res.ok:
            status = "failed"
            error = res.error_message() or (
                "failed: " + ", ".join(f"{n}={s}" for n, s in sorted(res.failed.items()))
            )
    except Cancelled:
        status = "cancelled"
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        fields: dict[str, Any] = {"status": status, "finished_at": store.now(), "error": error}
        if status == "done":
            fields["progress"] = 1.0
        store.update_job(job_id, **fields)
    return res
