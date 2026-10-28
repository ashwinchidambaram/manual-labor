"""Command-line entry point for Manual Labor (`labor`)."""

from __future__ import annotations

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
    """Copy source files into a project."""
    _not_implemented("ingest")


@app.command()
def parse(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
) -> None:
    """Parse ingested sources into blocks."""
    _not_implemented("parse")


@app.command()
def export(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
) -> None:
    """Assemble and export the knowledge base."""
    _not_implemented("export")


@app.command()
def probe() -> None:
    """Probe local hardware and suggest model settings."""
    _not_implemented("probe")
