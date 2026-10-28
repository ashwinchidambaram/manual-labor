"""Ingest: copy sources into a project, detect their kind, and write document.json."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manuallabor import ids
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import DocKind, Task
from manuallabor.contracts.io import write_json
from manuallabor.parse.metadata import infer_metadata, page1_lines_pdf
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import DEFAULT_FACTORIES, Provider
from manuallabor.providers.cache import LLMCache
from manuallabor.providers.sinks import JsonlSink

MIN_TEXT_CHARS = 16


class IngestError(Exception):
    pass


@dataclass(frozen=True)
class IngestResult:
    file: str
    slug: str
    status: str  # "new" | "exists"
    kind: DocKind
    pages: int
    detail: str | None = None

    def line(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "file": self.file,
            "doc": self.slug,
            "status": self.status,
            "kind": self.kind.value,
            "pages": self.pages,
        }
        if self.detail:
            d["detail"] = self.detail
        return d


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def visible_char_count(page: Any) -> int:
    """Non-whitespace characters drawn visibly (text render mode != 3)."""
    n = 0
    for span in page.get_texttrace():
        if span.get("type") == 3:
            continue
        for ch in span.get("chars", ()):
            if not chr(ch[0]).isspace():
                n += 1
    return n


def detect_pdf(path: Path) -> tuple[DocKind, int, list[int], list[tuple[float, float]], int]:
    """(kind, page_count, pages_without_text_layer, page sizes, invisible-text pages)."""
    from manuallabor.parse.pdf_pymupdf import open_pdf

    try:
        doc = open_pdf(path)
    except Exception as exc:
        raise IngestError(f"cannot open PDF {path.name}: {exc}") from exc
    with doc:
        if doc.needs_pass:
            raise IngestError(f"{path.name} is encrypted")
        n = doc.page_count
        if n < 1:
            raise IngestError(f"{path.name} has no pages")
        without: list[int] = []
        sizes: list[tuple[float, float]] = []
        invisible = 0
        for i in range(n):
            page = doc[i]
            sizes.append((float(page.rect.width), float(page.rect.height)))
            if visible_char_count(page) < MIN_TEXT_CHARS:
                without.append(i + 1)
                if len(page.get_text("text").strip()) >= MIN_TEXT_CHARS:
                    invisible += 1
    kind = DocKind.scanned_pdf if len(without) * 2 > n else DocKind.born_digital_pdf
    return kind, n, without, sizes, invisible


def detect_kind(path: Path) -> DocKind:
    ext = path.suffix.lower()
    if ext == ".docx":
        return DocKind.docx
    if ext == ".pdf":
        return detect_pdf(path)[0]
    raise IngestError(f"unsupported file type: {path.name}")


def _emit_line(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def metadata_provider(paths: ProjectPaths, warn: Callable[[str], None]) -> Provider | None:
    """The metadata-task provider, or None when the configured provider is not available."""
    try:
        cfg = paths.load_config()
    except Exception:
        return None
    ref = cfg.model_for(Task.metadata)
    if ref is None:
        return None
    factory = DEFAULT_FACTORIES.get(ref.provider)
    if factory is None:
        warn(f"metadata provider {ref.provider!r} is not available; skipping LLM inference")
        return None
    cache = LLMCache(paths.root / ".llm_cache")
    sink = JsonlSink(paths.root / "llm_calls.jsonl")
    from manuallabor.providers.base import utc_now

    return factory(ref, sink, cache, utc_now)


def _docx_info(path: Path) -> tuple[int, str | None]:
    title: str | None = None
    try:
        import docx

        d: Any = docx
        title = d.Document(str(path)).core_properties.title or None
    except Exception:
        title = None
    try:
        from manuallabor.parse.docx import count_virtual_pages

        pages = count_virtual_pages(path)
    except ImportError:
        pages = 1
    return pages, title


def ingest_files(
    paths: ProjectPaths,
    files: Sequence[Path],
    *,
    provider: Provider | None = None,
    emit: Callable[[dict[str, Any]], None] = _emit_line,
) -> list[IngestResult]:
    """Ingest each file; results are returned in input order."""

    def warn(msg: str) -> None:
        emit({"stage": "ingest", "status": "warning", "detail": msg})

    paths.root.mkdir(parents=True, exist_ok=True)
    paths.ensure_config()
    paths.sources.mkdir(parents=True, exist_ok=True)
    if provider is None:
        provider = metadata_provider(paths, warn)
    results: list[IngestResult] = []
    for src in files:
        src = Path(src)
        if not src.is_file():
            raise IngestError(f"no such file: {src}")
        name = src.name
        sha = sha256_file(src)
        dest = paths.source(name)
        existing = [d for d in paths.list_documents() if d.filename == name]
        if dest.exists():
            if sha256_file(dest) != sha:
                raise IngestError(
                    f"{name}: a different file with this name is already ingested; rename the file"
                )
            if existing:
                d = existing[0]
                res = IngestResult(name, d.slug, "exists", d.kind, d.page_count)
                emit(res.line())
                results.append(res)
                continue
        ext = src.suffix.lower()
        if ext not in (".pdf", ".docx"):
            raise IngestError(f"unsupported file type: {name}")
        slug = (
            existing[0].slug
            if existing
            else ids.make_unique_slug(ids.doc_slug_from_filename(name), paths.list_slugs())
        )
        detail: str | None = None
        title_hint: str | None = None
        if ext == ".docx":
            kind = DocKind.docx
            page_count, title_hint = _docx_info(src)
            without: list[int] = []
            page1_lines: list[Any] = []
            body = None
            embedded = title_hint
        else:
            kind, page_count, without, _sizes, invisible = detect_pdf(src)
            page1_lines, body, embedded = page1_lines_pdf(src)
            if invisible:
                detail = f"{invisible} page(s) carry invisible text; treated as no text layer"
            if without and not page1_lines and kind == DocKind.scanned_pdf:
                page1_lines = []
        meta = infer_metadata(
            page1_lines=page1_lines,
            body=body,
            embedded_title=embedded,
            filename=name,
            provider=provider,
            warn=warn,
        )
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
        doc = Document(
            slug=slug,
            sha256=sha,
            filename=name,
            title=meta.title,
            product_model=meta.product_model,
            product_model_inferred=meta.product_model_inferred,
            kind=kind,
            page_count=page_count,
            block_ids=[],
            pages_without_text_layer=without,
        )
        write_json(paths.doc(slug).document, doc)
        res = IngestResult(name, slug, "new", kind, page_count, detail)
        emit(res.line())
        results.append(res)
    return results
