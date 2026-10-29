"""Command-line entry point for Manual Labor (`labor`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="labor",
    help="Manual Labor: turn source documents into a reviewed knowledge base.",
    no_args_is_help=True,
    add_completion=False,
)
schemas_app = typer.Typer(help="Schema utilities.", no_args_is_help=True)
app.add_typer(schemas_app, name="schemas")


def _register_serve() -> None:
    """`labor serve` and `labor openapi export` live in cli_serve (module 7, implementer B)."""
    import importlib

    try:
        cli_serve = importlib.import_module("manuallabor.cli_serve")
    except ModuleNotFoundError as exc:
        if exc.name != "manuallabor.cli_serve":
            raise
        return
    cli_serve.register(app)


def _not_implemented(name: str) -> None:
    print(f"{name}: not implemented", file=sys.stderr)
    raise typer.Exit(2)


@schemas_app.command("export")
def schemas_export(
    out: Annotated[Path, typer.Option("--out", help="Output directory.")] = Path("schemas"),
    check: Annotated[
        bool, typer.Option("--check", help="Write nothing; exit 1 if files would change.")
    ] = False,
) -> None:
    """Export JSON schemas from the contract models into ./schemas."""
    from manuallabor.schemas_export import export_schemas

    result = export_schemas(out, check=check)
    if check:
        if result:
            for p in result:
                print(f"schema drift: {p}", file=sys.stderr)
            raise typer.Exit(1)
        print("schemas up to date")


@app.command()
def check(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    live: Annotated[bool, typer.Option("--live", help="Use real local models.")] = False,
    keep: Annotated[bool, typer.Option("--keep", help="Keep the temporary copy.")] = False,
) -> None:
    """Run the end-to-end smoke check on a temporary copy of a project."""
    if not project.is_dir():
        print(f"project directory not found: {project}", file=sys.stderr)
        raise typer.Exit(2)
    from manuallabor.check import run_check

    raise typer.Exit(run_check(project, live=live, keep=keep))


@app.command()
def ingest(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    files: Annotated[list[Path], typer.Argument(help="Source files to ingest.")],
) -> None:
    """Copy source files into a project and register them as documents."""
    from manuallabor.ingest import IngestError, ingest_files
    from manuallabor.project import ProjectPaths

    try:
        ingest_files(ProjectPaths(project), files)
    except IngestError as exc:
        print(
            json.dumps({"stage": "ingest", "status": "error", "detail": str(exc)}), file=sys.stderr
        )
        raise typer.Exit(1) from exc


def _stage(
    project: Path,
    node: str | list[str],
    *,
    only: str | None,
    force: bool,
    extra: dict[str, object] | None = None,
) -> list[str]:
    """Run one node (or several, document-major) through the executor (keeps
    docs/<slug>/stages.json true); the output lines are the stage's own."""
    from manuallabor.jobs.executor import run_node, run_nodes
    from manuallabor.jobs.providers import provider_set_factory
    from manuallabor.parse.pipeline import stdout_emit
    from manuallabor.project import ProjectPaths
    from manuallabor.providers.sinks import JsonlSink
    from manuallabor.state.errors import LockHeld
    from manuallabor.state.lock import ProjectLock

    paths = ProjectPaths(project)
    cfg = paths.ensure_config()
    lock = ProjectLock(paths.worker_lock, cmd=" ".join(sys.argv))
    try:
        lock.acquire()
    except LockHeld as exc:
        print(f"{exc}", file=sys.stderr)
        raise typer.Exit(3) from exc
    try:
        providers = provider_set_factory(paths, cfg, "config", JsonlSink(paths.llm_log))
        if isinstance(node, list):
            return run_nodes(
                paths,
                node,
                only=only,
                force=[node[0]] if force else [],
                emit=stdout_emit,
                providers=providers,
                extra=extra,
            )
        return run_node(
            paths, node, only=only, force=force, emit=stdout_emit, providers=providers, extra=extra
        )
    finally:
        lock.release()


@app.command()
def parse(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    force: Annotated[bool, typer.Option("--force", help="Re-parse even if up to date.")] = False,
    doc: Annotated[str | None, typer.Option("--doc", help="Only this document slug.")] = None,
    workers: Annotated[
        int | None,
        typer.Option("--workers", min=1, help="OCR worker processes (default min(2, cpus))."),
    ] = None,
) -> None:
    """Parse ingested sources into blocks (one JSON progress line per stage)."""
    failed = _stage(project, "parse", only=doc, force=force, extra={"workers": workers})
    if failed:
        raise typer.Exit(1)


@app.command()
def figures(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    force: Annotated[bool, typer.Option("--force", help="Re-extract even if up to date.")] = False,
    doc: Annotated[str | None, typer.Option("--doc", help="Only this document slug.")] = None,
) -> None:
    """Extract figures from parsed documents (one JSON progress line per document)."""
    if _stage(project, "figures", only=doc, force=force):
        raise typer.Exit(1)


@app.command()
def score(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    force: Annotated[bool, typer.Option("--force", help="Re-score even if up to date.")] = False,
    doc: Annotated[str | None, typer.Option("--doc", help="Only this document slug.")] = None,
) -> None:
    """Score parsed blocks and run the faithfulness check (one JSON progress line per doc)."""
    if _stage(project, "score", only=doc, force=force):
        raise typer.Exit(1)


@app.command()
def group(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    force: Annotated[bool, typer.Option("--force", help="Re-group even if up to date.")] = False,
    doc: Annotated[str | None, typer.Option("--doc", help="Only this document slug.")] = None,
) -> None:
    """Build the structure and topic views (one JSON progress line per document)."""
    if _stage(project, "group", only=doc, force=force):
        raise typer.Exit(1)


@app.command()
def clean(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    force: Annotated[bool, typer.Option("--force", help="Recompute even if up to date.")] = False,
    doc: Annotated[str | None, typer.Option("--doc", help="Only this document slug.")] = None,
    llm: Annotated[
        str | None,
        typer.Option("--llm", help="LLM pass: off, residual or always (default: project.json)."),
    ] = None,
    no_describe: Annotated[
        bool, typer.Option("--no-describe", help="Do not generate figure descriptions.")
    ] = False,
    no_score: Annotated[
        bool, typer.Option("--no-score", help="Do not re-score after cleaning.")
    ] = False,
) -> None:
    """Clean selected blocks, attach figures to articles, describe figures, re-score (one JSON
    progress line per document and stage)."""
    if llm is not None and llm not in ("off", "residual", "always"):
        print(f"--llm must be off, residual or always, got {llm!r}", file=sys.stderr)
        raise typer.Exit(2)
    failed = _stage(
        project,
        "clean" if no_score else ["clean", "score2"],
        only=doc,
        force=force,
        extra={"llm_mode": llm, "describe": False if no_describe else None},
    )
    if failed:
        raise typer.Exit(1)


@app.command()
def status(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    json_out: Annotated[
        bool, typer.Option("--json", help="Print JSON instead of a table.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Show the reason per node.")
    ] = False,
) -> None:
    """Per-document stage states (fresh / stale / missing / failed). Read-only."""
    from manuallabor.jobs.graph import project_status
    from manuallabor.jobs.render import render_status
    from manuallabor.project import ProjectPaths

    if not project.is_dir():
        print(f"project directory not found: {project}", file=sys.stderr)
        raise typer.Exit(2)
    st = project_status(ProjectPaths(project), None)
    if json_out:
        sys.stdout.write(json.dumps(st.model_dump(mode="json"), sort_keys=True, indent=2) + "\n")
    else:
        sys.stdout.write(render_status(st, verbose=verbose))


@app.command()
def run(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    to: Annotated[
        str, typer.Option("--to", help="Last node: parse, figures, score, group, clean or score2.")
    ] = "score2",
    doc: Annotated[
        list[str] | None, typer.Option("--doc", help="Only this document (repeatable).")
    ] = None,
    force: Annotated[
        list[str] | None, typer.Option("--force", help="Force this node (repeatable).")
    ] = None,
    allow_reparse: Annotated[
        bool,
        typer.Option("--allow-reparse", help="Allow a re-parse of documents that have decisions."),
    ] = False,
    mock: Annotated[bool, typer.Option("--mock", help="Mock every model call.")] = False,
) -> None:
    """Run every stale stage up to --to (resumable: a killed run continues where it stopped)."""
    from manuallabor.jobs.inline import run_inline
    from manuallabor.parse.pipeline import stdout_emit
    from manuallabor.project import ProjectPaths
    from manuallabor.state.errors import LockHeld
    from manuallabor.state.lock import ProjectLock
    from manuallabor.state.models import RunPlanIn
    from manuallabor.state.store import Store

    if not project.is_dir():
        print(f"project directory not found: {project}", file=sys.stderr)
        raise typer.Exit(2)
    paths = ProjectPaths(project)
    paths.ensure_config()
    cmd = " ".join(sys.argv)
    plock, wlock = ProjectLock(paths.lock, cmd=cmd), ProjectLock(paths.worker_lock, cmd=cmd)
    try:
        plock.acquire()
        wlock.acquire()
    except LockHeld as exc:
        plock.release()
        print(f"{exc}", file=sys.stderr)
        raise typer.Exit(3) from exc
    try:
        store = Store.open(paths)
        try:
            res = run_inline(
                paths,
                RunPlanIn(to=to, docs=doc, force=list(force or []), allow_reparse=allow_reparse),
                mode="mock" if mock else "config",
                emit=lambda o: stdout_emit(o),
                store=store,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise typer.Exit(2) from exc
        finally:
            store.close()
    finally:
        wlock.release()
        plock.release()
    if not res.ok:
        raise typer.Exit(1)


@app.command()
def export(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
) -> None:
    """Assemble and export the knowledge base."""
    _not_implemented("export")


@app.command()
def probe(
    json_out: Annotated[
        bool, typer.Option("--json", help="Print JSON instead of a table.")
    ] = False,
    apply: Annotated[
        str | None,
        typer.Option("--apply", help="Write this tier (small|medium|large|api) to --project."),
    ] = None,
    project: Annotated[
        Path | None, typer.Option("--project", help="Project directory (writes probe.json).")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="With --apply: write a tier that does not fit.")
    ] = False,
    keep_overrides: Annotated[
        bool,
        typer.Option(
            "--keep-overrides", help="With --apply: keep models.metadata and models.agent."
        ),
    ] = False,
) -> None:
    """Probe local hardware and suggest model settings (never installs anything)."""
    from manuallabor.contracts.io import dump_json, write_json
    from manuallabor.providers import probe as pr

    if apply is not None and apply not in ("small", "medium", "large", "api"):
        print(f"--apply must be small, medium, large or api, got {apply!r}", file=sys.stderr)
        raise typer.Exit(2)
    if apply is not None and project is None:
        print("--apply requires --project", file=sys.stderr)
        raise typer.Exit(2)
    if project is not None and not project.is_dir():
        print(f"project directory not found: {project}", file=sys.stderr)
        raise typer.Exit(2)
    result = pr.run_probe(path=project)
    table = pr.suggest(result)
    if project is not None:
        write_json(project / "probe.json", result)
    if apply is not None and project is not None:
        try:
            chosen = pr.apply_tier(
                project / "project.json",
                table,
                apply,  # type: ignore[arg-type]
                force=force,
                keep_overrides=keep_overrides,
                probe=result,
            )
        except pr.ApplyError as exc:
            print(str(exc), file=sys.stderr)
            raise typer.Exit(1) from exc
        print(
            "applied tier "
            + apply
            + ": "
            + ", ".join(f"{t}={m['provider']}:{m['model']}" for t, m in chosen.items()),
            file=sys.stderr,
        )
    if json_out:
        sys.stdout.write(dump_json({"probe": result, "suggestions": table}))
    else:
        sys.stdout.write(pr.render_table(result, table, apply))  # type: ignore[arg-type]


learning_app = typer.Typer(help="The reversible learning layer.", no_args_is_help=True)
app.add_typer(learning_app, name="learning")
decisions_app = typer.Typer(help="Decision log.", no_args_is_help=True)
app.add_typer(decisions_app, name="decisions")


def _locked_services(project: Path):  # type: ignore[no-untyped-def]
    """Take the project lock and open store + learning service (exit 3 when held)."""
    from manuallabor.project import ProjectPaths
    from manuallabor.state.errors import LockHeld
    from manuallabor.state.learning import LearningService
    from manuallabor.state.lock import ProjectLock
    from manuallabor.state.store import Store

    if not project.is_dir():
        print(f"project directory not found: {project}", file=sys.stderr)
        raise typer.Exit(2)
    paths = ProjectPaths(project)
    paths.ensure_config()
    lock = ProjectLock(paths.lock, cmd=" ".join(sys.argv))
    try:
        lock.acquire()
    except LockHeld as exc:
        print(f"{exc}", file=sys.stderr)
        raise typer.Exit(3) from exc
    store = Store.open(paths)
    return paths, store, LearningService(paths, store), lock


def _learning_op(project: Path, op: str, arg: str | None = None) -> None:
    import uuid

    from manuallabor.state.errors import InvalidOp, NotFound

    _paths, store, svc, lock = _locked_services(project)
    rid = f"cli-{uuid.uuid4().hex}"
    try:
        if op == "list":
            st = svc.state()
            print(
                f"enabled={st.enabled} use_global={st.use_global} "
                f"active={st.active} provenance={st.provenance}"
            )
            for sn in st.snapshots:
                mark = "*" if sn.active else " "
                print(
                    f"{mark} {sn.id}  parent={sn.parent or '-'}  "
                    f"origin={sn.origin}  counts={sn.counts}"
                )
        elif op == "snapshot":
            print(f"snapshot {svc.snapshot(rid).id} created (not activated)")
        elif op in ("activate", "rollback"):
            assert arg is not None
            print(f"active={svc.activate(arg, rid).active}")
        elif op == "reset":
            svc.reset(rid)
            print("learning reset: decisions and snapshots kept; baseline behaviour restored")
        elif op == "disable":
            assert arg is not None
            print(f"snapshot {svc.disable_item(arg, rid).id} active (item {arg} disabled)")
        elif op == "publish":
            assert arg is not None
            print(f"published {svc.publish(arg, rid).origin}")
    except (InvalidOp, NotFound) as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(1) from exc
    finally:
        store.close()
        lock.release()


@learning_app.command("list")
def learning_list(project: Annotated[Path, typer.Argument(help="Project directory.")]) -> None:
    """Snapshots, the active one and the provenance stages would record."""
    _learning_op(project, "list")


@learning_app.command("snapshot")
def learning_snapshot(project: Annotated[Path, typer.Argument(help="Project directory.")]) -> None:
    """Derive a new immutable snapshot from every recorded action (does not activate it)."""
    _learning_op(project, "snapshot")


@learning_app.command("activate")
def learning_activate(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    snapshot_id: Annotated[str, typer.Argument(help="Snapshot id, e.g. 002.")],
) -> None:
    """Make a snapshot the active learned layer."""
    _learning_op(project, "activate", snapshot_id)


@learning_app.command("rollback")
def learning_rollback(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    snapshot_id: Annotated[str, typer.Argument(help="Snapshot id to return to.")],
) -> None:
    """Return to an earlier snapshot (same operation as activate)."""
    _learning_op(project, "rollback", snapshot_id)


@learning_app.command("reset")
def learning_reset(project: Annotated[Path, typer.Argument(help="Project directory.")]) -> None:
    """Remove the active learned layer; decisions and snapshots are kept."""
    _learning_op(project, "reset")


@learning_app.command("disable")
def learning_disable(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    item_id: Annotated[str, typer.Argument(help="Rule or example id.")],
) -> None:
    """Disable one rule or example (a new child snapshot becomes active)."""
    _learning_op(project, "disable", item_id)


@learning_app.command("publish")
def learning_publish(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    snapshot_id: Annotated[str, typer.Argument(help="Snapshot id.")],
) -> None:
    """Copy a snapshot to the global store (needs learning.contribute_global)."""
    _learning_op(project, "publish", snapshot_id)


@decisions_app.command("export")
def decisions_export(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    out: Annotated[Path | None, typer.Option("--out", help="Output file (default stdout).")] = None,
) -> None:
    """Every recorded action as canonical NDJSON, sorted by id."""
    from manuallabor.contracts.io import canonical_json
    from manuallabor.project import ProjectPaths
    from manuallabor.state.store import Store

    paths = ProjectPaths(project)
    if not paths.db.is_file():
        print("no project.db yet", file=sys.stderr)
        raise typer.Exit(1)
    store = Store.open(paths, readonly=True)
    try:
        text = "".join(
            canonical_json(a.model_dump(mode="json")).decode() + "\n" for a in store.iter_actions()
        )
    finally:
        store.close()
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")


_register_serve()
