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
) -> None:
    """Run the end-to-end smoke check on a project."""
    _not_implemented("check")


@app.command()
def serve(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    port: Annotated[int, typer.Option("--port", help="Port to listen on.")] = 8765,
) -> None:
    """Start the local API and UI server."""
    _not_implemented("serve")


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
    from manuallabor.parse.pipeline import parse_project
    from manuallabor.project import ProjectPaths

    failed = parse_project(ProjectPaths(project), force=force, only=doc, workers=workers)
    if failed:
        raise typer.Exit(1)


@app.command()
def figures(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    force: Annotated[bool, typer.Option("--force", help="Re-extract even if up to date.")] = False,
    doc: Annotated[str | None, typer.Option("--doc", help="Only this document slug.")] = None,
) -> None:
    """Extract figures from parsed documents (one JSON progress line per document)."""
    from manuallabor.figures.pipeline import run_figures
    from manuallabor.project import ProjectPaths

    failed = run_figures(ProjectPaths(project), only=doc, force=force)
    if failed:
        raise typer.Exit(1)


@app.command()
def score(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    force: Annotated[bool, typer.Option("--force", help="Re-score even if up to date.")] = False,
    doc: Annotated[str | None, typer.Option("--doc", help="Only this document slug.")] = None,
) -> None:
    """Score parsed blocks and run the faithfulness check (one JSON progress line per doc)."""
    from manuallabor.project import ProjectPaths
    from manuallabor.scoring.pipeline import run_score

    failed = run_score(ProjectPaths(project), only=doc, force=force)
    if failed:
        raise typer.Exit(1)


@app.command()
def group(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    force: Annotated[bool, typer.Option("--force", help="Re-group even if up to date.")] = False,
    doc: Annotated[str | None, typer.Option("--doc", help="Only this document slug.")] = None,
) -> None:
    """Build the structure and topic views (one JSON progress line per document)."""
    from manuallabor.grouping.pipeline import run_group
    from manuallabor.project import ProjectPaths

    failed = run_group(ProjectPaths(project), only=doc, force=force)
    if failed:
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
    from manuallabor.cleanup.pipeline import run_clean
    from manuallabor.project import ProjectPaths

    if llm is not None and llm not in ("off", "residual", "always"):
        print(f"--llm must be off, residual or always, got {llm!r}", file=sys.stderr)
        raise typer.Exit(2)
    failed = run_clean(
        ProjectPaths(project),
        only=doc,
        force=force,
        llm_mode=llm,  # type: ignore[arg-type]
        describe=False if no_describe else None,
        rescore=not no_score,
    )
    if failed:
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
