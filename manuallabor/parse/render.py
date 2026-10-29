"""Page rendering and the OCR worker pool (design 01-parse section 11)."""

from __future__ import annotations

import multiprocessing
import os
import time
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manuallabor.contracts._base import Sha256Hex
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.io import read_json, write_json
from manuallabor.parse.types import OcrPage, ParseModel

DEFAULT_WORKERS = 2
WORKERS_ENV = "MANUALLABOR_WORKERS"


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


def render_page_png(pdf_path: Path, page_index: int, dpi: int, out: Path) -> bool:
    """Render a page to a 300-DPI RGB PNG; returns True when it was (re)rendered."""
    from manuallabor.parse.pdf_pymupdf import open_pdf, pm

    if out.is_file() and out.stat().st_size > 0:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    with open_pdf(pdf_path) as doc:
        pix = doc[page_index].get_pixmap(dpi=dpi, colorspace=pm().csRGB, alpha=False)
        tmp = out.with_name(out.name + ".tmp")
        pix.save(str(tmp), output="png")
    os.replace(tmp, out)
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


class OcrPool:
    """A lazily started spawn-context process pool; results are collected by page order."""

    def __init__(self, workers: int | None = None) -> None:
        self._pool: ProcessPoolExecutor | None = None
        self._workers = workers

    def executor(self) -> ProcessPoolExecutor:
        """The pool, started on first use. Spawned workers do not run the CLI or job-worker
        entry, so they install the offline guard (MANUALLABOR_OFFLINE=1) themselves."""
        if self._pool is None:
            from manuallabor.providers.offline import install_from_env

            self._pool = ProcessPoolExecutor(
                max_workers=pool_workers(self._workers),
                mp_context=multiprocessing.get_context("spawn"),
                initializer=install_from_env,
            )
        return self._pool

    def submit(self, job: OcrJob) -> Future[OcrJobResult]:
        return self.executor().submit(run_ocr_job, job)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None
