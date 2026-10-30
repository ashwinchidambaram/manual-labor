"""CLI wiring for `labor serve` and `labor openapi export` (registered from cli.py)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer


def register(app: typer.Typer) -> None:
    openapi_app = typer.Typer(help="OpenAPI utilities.", no_args_is_help=True)
    app.add_typer(openapi_app, name="openapi")

    @app.command("serve")
    def serve_cmd(
        project: Annotated[Path, typer.Argument(help="Project directory.")],
        host: Annotated[
            str,
            typer.Option(
                "--host",
                help="Interface to bind. Anything but loopback exposes the project, without "
                "authentication, to everyone who can reach that address.",
            ),
        ] = "127.0.0.1",
        port: Annotated[int, typer.Option("--port", help="Port to listen on.")] = 8765,
        dev: Annotated[
            bool, typer.Option("--dev", help="API only; Vite serves the UI on 5173.")
        ] = False,
        mock: Annotated[
            bool, typer.Option("--mock", help="Run every job with mock providers.")
        ] = False,
        no_resume: Annotated[
            bool, typer.Option("--no-resume", help="Do not re-enqueue interrupted jobs.")
        ] = False,
        allow_host: Annotated[
            list[str] | None,
            typer.Option(
                "--allow-host",
                help="Another host name the server answers to (repeatable), e.g. a LAN DNS name "
                "when --host is not loopback.",
            ),
        ] = None,
        max_upload_mb: Annotated[
            int,
            typer.Option("--max-upload-mb", min=1, help="Largest request body (upload) in MB."),
        ] = 200,
    ) -> None:
        """Start the local API and UI server."""
        from manuallabor.project import ProjectPaths
        from manuallabor.serve import serve

        if not project.is_dir():
            print(f"project directory not found: {project}", file=sys.stderr)
            raise typer.Exit(2)
        code = serve(
            ProjectPaths(project),
            host=host,
            port=port,
            dev=dev,
            mock=mock,
            resume=not no_resume,
            allow_hosts=list(allow_host or []),
            max_upload_bytes=max_upload_mb * 1024 * 1024,
        )
        raise typer.Exit(code)

    @openapi_app.command("export")
    def openapi_export(
        out: Annotated[Path | None, typer.Option("--out", help="Output file.")] = None,
        check: Annotated[
            bool, typer.Option("--check", help="Write nothing; exit 1 if the file would change.")
        ] = False,
    ) -> None:
        """Write (or verify) the OpenAPI document the frontend types are generated from."""
        from manuallabor.api.openapi import DEFAULT_OUT, export_openapi

        target = out or DEFAULT_OUT
        if not export_openapi(target, check=check):
            print(f"openapi drift: {target}", file=sys.stderr)
            raise typer.Exit(1)
        print("openapi up to date" if check else f"wrote {target}")
