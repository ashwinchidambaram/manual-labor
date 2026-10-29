"""`labor serve`: lock the project, open the store, start the job supervisor, run uvicorn.

Never waits on a job or an LLM call (design 07 section 7)."""

from __future__ import annotations

import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from types import FrameType

from manuallabor.project import ProjectPaths
from manuallabor.state.errors import LockHeld
from manuallabor.state.interfaces import AppServices

EXIT_LOCKED = 3


def find_frontend_dist() -> Path | None:
    """First existing of $MANUALLABOR_FRONTEND_DIST, the packaged dir, <repo>/frontend/dist."""
    here = Path(__file__).resolve().parent
    candidates: list[Path] = []
    env = os.environ.get("MANUALLABOR_FRONTEND_DIST")
    if env:
        candidates.append(Path(env))
    candidates += [here / "_frontend", here.parent / "frontend" / "dist"]
    for c in candidates:
        if (c / "index.html").is_file():
            return c
    return None


def _default_services(paths: ProjectPaths, mock: bool, resume: bool) -> AppServices:
    from manuallabor.state.interfaces import open_project

    return open_project(paths, mode="mock" if mock else "config", resume=resume)


def serve(
    paths: ProjectPaths,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    dev: bool = False,
    mock: bool = False,
    resume: bool = True,
    static_dir: Path | None = None,
    open_services: Callable[[ProjectPaths, bool, bool], AppServices] = _default_services,
) -> int:
    """Run until SIGINT/SIGTERM. Returns the process exit code (3 when the project is locked)."""
    import uvicorn

    from manuallabor.api.app import create_app
    from manuallabor.state.lock import ProjectLock

    lock = ProjectLock(paths.lock)
    try:
        lock.acquire(nonblocking=True)
    except LockHeld as exc:
        print(f"labor serve: {exc}", file=sys.stderr)
        return EXIT_LOCKED
    services: AppServices | None = None
    try:
        services = open_services(paths, mock, resume)
        _print_status(paths, services)
        services.runner.start()
        app = create_app(
            services, static_dir=None if dev else (static_dir or find_frontend_dist()), dev=dev
        )
        config = uvicorn.Config(app, host=host, port=port, workers=1, log_level="warning")
        server = uvicorn.Server(config)

        def _stop(signum: int, frame: FrameType | None) -> None:
            server.should_exit = True

        # uvicorn installs its own handlers only when it owns the main thread's signals;
        # ours make SIGTERM and SIGINT a graceful shutdown that reaches the finally block.
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        print(f"labor serve: http://{host}:{port}  (project {paths.root})", flush=True)
        server.run()
        return 0
    finally:
        if services is not None:
            services.runner.stop()
            services.store.close()
        lock.release()


def _print_status(paths: ProjectPaths, services: AppServices) -> None:
    from manuallabor.jobs.graph import project_status

    try:
        st = project_status(paths, services.runner)
    except Exception as exc:  # status is informational; never block startup on it
        print(f"labor serve: status unavailable ({exc})", file=sys.stderr)
        return
    for d in st.docs:
        states = " ".join(f"{n.node}={n.state}" for n in d.nodes)
        print(f"  {d.doc_id}: {states}")
