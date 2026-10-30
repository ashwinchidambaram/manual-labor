"""Page rendering and the OCR worker pool (design 01-parse section 11)."""

from __future__ import annotations

import logging
import multiprocessing
import os
import time
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manuallabor.contracts._base import Sha256Hex
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.io import PART_SUFFIX, read_json, temp_path, write_json
from manuallabor.parse.types import OcrPage, ParseModel

DEFAULT_WORKERS = 2
WORKERS_ENV = "MANUALLABOR_WORKERS"
# how long `OcrPool.close` waits for the workers to exit before it terminates them (01 §11.1)
CLOSE_TIMEOUT = 10.0
_KILL_GRACE = 3.0

log = logging.getLogger(__name__)


def pool_workers(explicit: int | None = None) -> int:
    """Worker count: explicit value, else $MANUALLABOR_WORKERS, else min(2, cpu_count)."""
    if explicit is not None:
        return max(1, explicit)
    env = os.environ.get(WORKERS_ENV)
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return max(1, min(DEFAULT_WORKERS, os.cpu_count() or 1))


class PartialOcr(ParseModel):
    """A per-page OCR result cached while a parse is running (resumability)."""

    version: str
    source_sha256: Sha256Hex
    page: OcrPage


def render_tmp_path(out: Path) -> Path:
    """The private temp file one render writes before its atomic replace into `out`.

    One per call (two requests can render the same page at once), and ".part" rather than ".tmp":
    API page renders run without the worker lock, and a job's start-up `clean_stray_tmp` removes
    every "*.tmp" under docs/ while one may be in flight.
    """
    return temp_path(out, PART_SUFFIX)


def render_page_png(pdf_path: Path, page_index: int, dpi: int, out: Path) -> bool:
    """Render a page to a 300-DPI RGB PNG; returns True when it was (re)rendered."""
    from manuallabor.parse.pdf_pymupdf import open_pdf, pm

    if out.is_file() and out.stat().st_size > 0:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    # A shared "<out>.tmp" made the second of two concurrent renders fail on os.replace, and the
    # job cleaner deleted it under the first; see render_tmp_path. Last atomic replace wins and the
    # contents are identical.
    tmp = render_tmp_path(out)
    try:
        with open_pdf(pdf_path) as doc:
            pix = doc[page_index].get_pixmap(dpi=dpi, colorspace=pm().csRGB, alpha=False)
            pix.save(str(tmp), output="png")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return True


@dataclass(frozen=True)
class OcrJob:
    pdf_path: str
    page: int  # 1-based
    size_pt: tuple[float, float]
    dpi: int
    png_path: str
    config_json: str
    source_sha256: str
    roles: tuple[str, ...]  # subset of ("ocr", "ocr_alt")
    versions: tuple[tuple[str, str], ...]  # (role, version)
    partial_paths: tuple[tuple[str, str], ...]  # (role, path)


@dataclass
class OcrJobResult:
    page: int
    pages: dict[str, OcrPage]
    render_ms: float
    ocr_ms: float
    rendered: bool


_ENGINES: dict[str, Any] = {}


def _engines(config_json: str) -> tuple[Any, Any]:
    cached = _ENGINES.get(config_json)
    if cached is None:
        from manuallabor.parse import ocr as ocr_mod

        cfg = ProjectConfig.model_validate_json(config_json)
        cached = ocr_mod.build_engines(cfg, lambda _m: None)
        _ENGINES[config_json] = cached
    return cached


def run_ocr_job(job: OcrJob) -> OcrJobResult:
    """Render one page (cached) and run the requested OCR roles on it (a pool worker)."""
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    t0 = time.perf_counter()
    png = Path(job.png_path)
    rendered = render_page_png(Path(job.pdf_path), job.page - 1, job.dpi, png)
    t1 = time.perf_counter()
    versions = dict(job.versions)
    partials = dict(job.partial_paths)
    out: dict[str, OcrPage] = {}
    ocr_engine: Any = None
    alt_engine: Any = None
    for role in job.roles:
        ppath = Path(partials[role])
        if ppath.is_file():
            try:
                part = read_json(ppath, PartialOcr)
                if part.version == versions[role] and part.source_sha256 == job.source_sha256:
                    out[role] = part.page
                    continue
            except ValueError:
                pass
        if ocr_engine is None and alt_engine is None:
            ocr_engine, alt_engine = _engines(job.config_json)
        engine = ocr_engine if role == "ocr" else alt_engine
        if engine is None:
            raise RuntimeError(f"OCR role {role} has no engine")
        page = engine.ocr_page(png, job.page, job.size_pt, job.dpi)
        write_json(
            ppath,
            PartialOcr(version=versions[role], source_sha256=job.source_sha256, page=page),
        )
        out[role] = page
    t2 = time.perf_counter()
    return OcrJobResult(
        page=job.page,
        pages=out,
        render_ms=(t1 - t0) * 1000.0,
        ocr_ms=(t2 - t1) * 1000.0,
        rendered=rendered,
    )


def _worker_init() -> None:
    """Pool worker start-up. A spawned worker runs neither the CLI nor the job-worker entry, so
    it turns third-party telemetry off (importing this module already did, design 06 section 4)
    and installs the offline guard (MANUALLABOR_OFFLINE=1) itself."""
    from manuallabor.providers.offline import install_from_env
    from manuallabor.telemetry import disable_library_telemetry

    disable_library_telemetry()
    install_from_env()


def _wait_exit(procs: list[Any], timeout: float) -> list[Any]:
    """Wait up to `timeout` seconds for the processes to exit; returns those still running.

    Exit is read from each process's sentinel (closed by the kernel when it exits), never from
    `is_alive()`: the pool's manager thread reaps workers with its own `waitpid`, and a
    `waitpid` that loses that race reports a dead worker as alive (seen under load)."""
    from multiprocessing.connection import wait

    pending = {p.sentinel: p for p in procs}
    deadline = time.monotonic() + timeout
    while pending:
        left = deadline - time.monotonic()
        ready = wait(list(pending), max(0.0, left))
        for r in ready:
            pending.pop(r, None)
        if left <= 0:
            break
    return list(pending.values())


class OcrPool:
    """A lazily started spawn-context process pool; results are collected by page order."""

    def __init__(self, workers: int | None = None) -> None:
        self._pool: ProcessPoolExecutor | None = None
        self._workers = workers

    def executor(self) -> ProcessPoolExecutor:
        """The pool, started on first use (each worker runs `_worker_init`)."""
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=pool_workers(self._workers),
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_worker_init,
            )
        return self._pool

    def submit(self, job: OcrJob) -> Future[OcrJobResult]:
        return self.executor().submit(run_ocr_job, job)

    def processes(self) -> list[Any]:
        """The worker processes started so far (a snapshot)."""
        if self._pool is None:
            return []
        procs = getattr(self._pool, "_processes", None) or {}
        return list(procs.values())

    def close(self, timeout: float = CLOSE_TIMEOUT) -> None:
        """Shut the pool down without ever waiting forever (design 01 section 11.1). Callers
        have collected every result they need. Pending work is cancelled and the workers are
        asked to exit; a worker still alive after `timeout` seconds (seen: a library's exit-time
        teardown spinning forever) is terminated, then killed, and logged. The pool's own
        exit-time join then finds nothing left to wait for."""
        pool, self._pool = self._pool, None
        if pool is None:
            return
        procs = list((getattr(pool, "_processes", None) or {}).values())
        pool.shutdown(wait=False, cancel_futures=True)
        stuck = _wait_exit(procs, timeout)
        for p in stuck:
            log.warning(
                "render worker pid %s did not exit within %.0f s of shutdown; terminating it",
                p.pid,
                timeout,
            )
            p.terminate()
        for p in _wait_exit(stuck, _KILL_GRACE):
            log.warning("render worker pid %s ignored SIGTERM; killing it", p.pid)
            p.kill()
        _wait_exit(stuck, _KILL_GRACE)
        manager = getattr(pool, "_executor_manager_thread", None)
        if manager is not None:
            manager.join(_KILL_GRACE)
