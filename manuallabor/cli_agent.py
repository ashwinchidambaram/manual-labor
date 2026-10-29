"""`labor agent` and `labor calibration` (registered from cli.py)."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Annotated, Any

import typer


def _open(project: Path, cmd: str) -> tuple[Any, Any, list[Any]]:
    from manuallabor.project import ProjectPaths
    from manuallabor.providers.base import utc_now
    from manuallabor.state.errors import LockHeld
    from manuallabor.state.lock import ProjectLock
    from manuallabor.state.store import Store

    if not project.is_dir():
        print(f"project directory not found: {project}", file=sys.stderr)
        raise typer.Exit(2)
    paths = ProjectPaths(project)
    paths.ensure_config()
    plock, wlock = ProjectLock(paths.lock, cmd=cmd), ProjectLock(paths.worker_lock, cmd=cmd)
    try:
        plock.acquire()
        wlock.acquire()
    except LockHeld as exc:
        plock.release()
        print(str(exc), file=sys.stderr)
        raise typer.Exit(3) from exc
    clock = utc_now
    fixed = os.environ.get("MANUALLABOR_FIXED_NOW")
    if fixed:
        from manuallabor.contracts._base import _parse_utc

        at = _parse_utc(fixed)
        clock = lambda: at  # noqa: E731
    return paths, Store.open(paths, clock=clock), [wlock, plock]


def register(app: typer.Typer) -> None:
    @app.command("agent")
    def agent_cmd(
        project: Annotated[Path, typer.Argument(help="Project directory.")],
        doc: Annotated[list[str] | None, typer.Option("--doc", help="Only this document.")] = None,
        mock: Annotated[bool, typer.Option("--mock", help="Mock every model call.")] = False,
        json_out: Annotated[bool, typer.Option("--json", help="Print JSON lines.")] = False,
    ) -> None:
        """Propose fixes for the open flags (one fresh model call per flag, every proposal
        rechecked). Nothing is applied: accept proposals in the Agent screen."""
        from manuallabor.agent.pipeline import run_agent_inline

        paths, store, locks = _open(project, " ".join(sys.argv))
        try:
            code = run_agent_inline(
                paths,
                store,
                mode="mock" if mock else "config",
                docs=doc,
                emit=lambda o: print(json.dumps(o, sort_keys=True)) if json_out else None,
                echo=not json_out,
            )
        finally:
            store.close()
            for lk in locks:
                lk.release()
        raise typer.Exit(code)

    @app.command("calibration")
    def calibration_cmd(
        project: Annotated[Path, typer.Argument(help="Project directory.")],
        scope: Annotated[str, typer.Option("--scope", help="project or global.")] = "project",
        json_out: Annotated[bool, typer.Option("--json")] = False,
        apply: Annotated[
            float | None, typer.Option("--apply", help="Apply this threshold (explicit).")
        ] = None,
        apply_scope: Annotated[
            str, typer.Option("--apply-scope", help="next_docs or project.")
        ] = "next_docs",
        publish: Annotated[
            bool, typer.Option("--publish", help="Publish outcomes (needs contribute_global).")
        ] = False,
    ) -> None:
        """Calibration of the review threshold from the recorded decisions. Without --apply
        nothing is written to project.json."""
        from manuallabor.calibration.apply import CalibrationService
        from manuallabor.contracts.io import dump_json
        from manuallabor.state.data import ProjectData
        from manuallabor.state.errors import InvalidOp

        if scope not in ("project", "global") or apply_scope not in ("next_docs", "project"):
            print("--scope: project|global; --apply-scope: next_docs|project", file=sys.stderr)
            raise typer.Exit(2)
        paths, store, locks = _open(project, " ".join(sys.argv))
        try:
            data = ProjectData(paths, store)
            from manuallabor.jobs.runner import JobRunner

            svc = CalibrationService(paths, store, data, JobRunner(paths, store))
            if publish:
                from manuallabor.calibration.global_store import publish_outcomes
                from manuallabor.calibration.outcomes import outcomes

                if not paths.load_config().learning.contribute_global:
                    print("publishing needs learning.contribute_global", file=sys.stderr)
                    raise typer.Exit(1)
                n = publish_outcomes(
                    store.meta("project_uuid") or "project", outcomes(store.iter_actions())
                )
                print(f"published {n} outcomes")
            if apply is not None:
                try:
                    thr, pinned, _job = svc.apply(
                        apply,
                        apply_scope,  # type: ignore[arg-type]
                        f"cli-{uuid.uuid4().hex}",
                    )
                except InvalidOp as exc:
                    print(str(exc), file=sys.stderr)
                    raise typer.Exit(1) from exc
                print(f"threshold {thr:g} applied ({apply_scope}); pinned {len(pinned)} docs")
                return
            rep = svc.report(scope)  # type: ignore[arg-type]
            if json_out:
                sys.stdout.write(dump_json(rep))
                return
            print(
                f"outcomes {rep.n_outcomes} (numeric excluded {rep.n_numeric_excluded}); "
                f"current threshold {rep.current_threshold}; target {rep.target_edit_rate}"
            )
            for b in rep.buckets:
                if b.n:
                    print(f"  [{b.lo:.2f},{b.hi:.2f}) n={b.n} edited={b.edited}")
            print(f"suggested threshold: {rep.suggested_threshold} ({rep.suggestion_reason})")
            if rep.suggestion_detail:
                print(f"  {rep.suggestion_detail}")
            for w in rep.warnings:
                print(f"  warning: {w}")
        finally:
            store.close()
            for lk in locks:
                lk.release()
