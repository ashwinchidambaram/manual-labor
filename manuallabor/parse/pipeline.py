"""Parse pipeline: stages, idempotency, progress lines and persistence (design section 10)."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata as md
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockType, DocKind
from manuallabor.contracts.io import canonical_json, read_json, write_json
from manuallabor.ingest import metadata_provider
from manuallabor.parse import geometry as g
from manuallabor.parse.classify import ClassifyInput, body_size_of, classify_blocks
from manuallabor.parse.headers import HFItem, detect_headers_footers
from manuallabor.parse.layout import OrderItem, order_page_ex
from manuallabor.parse.merge import MergedBlock, merge_page
from manuallabor.parse.metadata import infer_metadata
from manuallabor.parse.pdf_docling import DoclingAdapter, docling_version_string, ensure_models
from manuallabor.parse.pdf_pymupdf import PyMuPdfAdapter, pymupdf_version
from manuallabor.parse.render import OcrJob, OcrJobResult, OcrPool
from manuallabor.parse.text import numeric_tokens
from manuallabor.parse.types import (
    Disposition,
    FigureCandidate,
    MergeReport,
    OcrOutput,
    OcrPage,
    Overlap,
    PageLayout,
    PageParse,
    ParseContext,
    ParseError,
    ParserOutput,
    ParseState,
)
from manuallabor.project import DocPaths, ProjectPaths

PARSE_ALGO_VERSION = "3"
MAX_BLOCKS_PER_PAGE = 999
OVERLAP_IOU = 0.05

Emit = Callable[[dict[str, Any]], None]


def stdout_emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


class Progress:
    def __init__(self, doc: str, emit: Emit) -> None:
        self.doc = doc
        self.emit = emit

    def line(
        self,
        stage: str,
        status: str,
        *,
        pages: int | None = None,
        t0: float | None = None,
        detail: str | None = None,
    ) -> None:
        elapsed = None if t0 is None else int(round((time.perf_counter() - t0) * 1000.0))
        self.emit(
            {
                "doc": self.doc,
                "stage": stage,
                "status": status,
                "pages": pages,
                "elapsed_ms": elapsed,
                "detail": detail,
            }
        )


@dataclass
class Runtime:
    """Process-wide, lazily created heavy resources shared by all documents of a run."""

    pool: OcrPool
    emit: Emit
    _docling: DoclingAdapter | None = None

    @classmethod
    def create(cls, emit: Emit = stdout_emit, workers: int | None = None) -> Runtime:
        return cls(pool=OcrPool(workers), emit=emit)

    def docling(self) -> DoclingAdapter:
        if self._docling is None:
            self._docling = DoclingAdapter()
        return self._docling

    def close(self) -> None:
        self.pool.close()


# ---------------------------------------------------------------------------------------------
# fingerprints and versions


def resolved_ocr_engine(cfg: ProjectConfig) -> str:
    try:
        from manuallabor.parse import ocr as ocr_mod

        return str(ocr_mod.resolve_engine(cfg.ocr_engine))
    except ImportError:
        return cfg.ocr_engine.value


def config_fingerprint(cfg: ProjectConfig) -> str:
    payload = {
        "parsers": list(cfg.parsers),
        "ocr_engine": resolved_ocr_engine(cfg),
        "ocr_dpi": cfg.ocr_dpi,
        "background_ocr_born_digital": cfg.background_ocr_born_digital,
        "parse_algo": PARSE_ALGO_VERSION,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _pkg(name: str) -> str:
    try:
        return f"{name}=={md.version(name)}"
    except md.PackageNotFoundError:
        return f"{name}==unknown"


def parser_versions_for(
    doc: Document, cfg: ProjectConfig, ocr_versions: dict[str, str] | None
) -> dict[str, str]:
    v: dict[str, str] = {}
    if doc.kind == DocKind.docx:
        v["docx"] = _pkg("python-docx")
        v["docling"] = _pkg("docling")
    else:
        for name in cfg.parsers:
            if name == "pymupdf":
                v[name] = pymupdf_version()
            elif name == "docling":
                v[name] = docling_version_string()
            else:
                raise ParseError(f"unknown parser {name!r} (registered: pymupdf, docling)")
        if ocr_versions:
            v.update(ocr_versions)
    v["ocr_engine"] = resolved_ocr_engine(cfg)
    v["parse_algo"] = PARSE_ALGO_VERSION
    v["config"] = config_fingerprint(cfg)
    return dict(sorted(v.items()))


# ---------------------------------------------------------------------------------------------
# helpers


def _reuse_output(path: Path, parser: str, version: str, sha: str) -> ParserOutput | None:
    if not path.is_file():
        return None
    try:
        out = read_json(path, ParserOutput)
    except ValueError:
        return None
    if out.parser == parser and out.version == version and out.source_sha256 == sha:
        return out
    return None


def _pdf_page_sizes(path: Path) -> list[tuple[float, float]]:
    from manuallabor.parse.pdf_pymupdf import open_pdf

    with open_pdf(path) as d:
        return [(float(p.rect.width), float(p.rect.height)) for p in d]


def _ocr_module() -> Any | None:
    try:
        from manuallabor.parse import ocr as ocr_mod
    except ImportError:
        return None
    return ocr_mod


# ---------------------------------------------------------------------------------------------
# public entry points


def parse_project(
    paths: ProjectPaths,
    *,
    force: bool = False,
    only: str | None = None,
    emit: Emit = stdout_emit,
    workers: int | None = None,
) -> int:
    """Parse every ingested document (slug order). Returns the number of failed documents."""
    cfg = paths.ensure_config()
    slugs = paths.list_slugs()
    if only is not None:
        if only not in slugs:
            emit({"doc": only, "stage": "parse", "status": "error", "detail": "unknown document"})
            return 1
        slugs = [only]
    failures = 0
    rt = Runtime.create(emit, workers)
    try:
        for slug in slugs:
            try:
                parse_document(paths, slug, cfg, rt, force=force)
            except Exception as exc:
                failures += 1
                emit(
                    {
                        "doc": slug,
                        "stage": "parse",
                        "status": "error",
                        "pages": None,
                        "elapsed_ms": None,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                )
    finally:
        rt.close()
    return failures


def parse_document(
    paths: ProjectPaths, slug: str, cfg: ProjectConfig, rt: Runtime, *, force: bool = False
) -> None:
    doc = paths.load_document(slug)
    dp = paths.doc(slug)
    prog = Progress(slug, rt.emit)
    if doc.kind == DocKind.docx:
        _parse_docx(paths, doc, dp, cfg, prog, force)
    else:
        _parse_pdf(paths, doc, dp, cfg, rt, prog, force)


def _skip_if_current(dp: DocPaths, doc: Document, versions: dict[str, str], force: bool) -> bool:
    if force or not dp.state.is_file():
        return False
    try:
        st = read_json(dp.state, ParseState)
    except ValueError:
        return False
    return (
        st.complete
        and st.sha256 == doc.sha256
        and st.parser_versions == versions
        and st.config_fingerprint == versions["config"]
        and dp.blocks.is_file()
    )


def parse_is_current(paths: ProjectPaths, slug: str, cfg: ProjectConfig) -> bool:
    """True when the document's parse is complete and made from the current source, config and
    parser versions. Same decision as the stage's own skip check, minus the OCR engine
    versions (those need the OCR runtime); the config fingerprint already carries the
    resolved OCR engine, so an engine switch is still caught. Pure: runs no parser."""
    dp = paths.doc(slug)
    try:
        doc = paths.load_document(slug)
        st = read_json(dp.state, ParseState)
    except (OSError, ValueError):
        return False
    if not (st.complete and dp.blocks.is_file() and st.sha256 == doc.sha256):
        return False
    expected: dict[str, str] = {
        "ocr_engine": resolved_ocr_engine(cfg),
        "parse_algo": PARSE_ALGO_VERSION,
        "config": config_fingerprint(cfg),
    }
    if doc.kind == DocKind.docx:
        expected["docx"] = _pkg("python-docx")
        expected["docling"] = _pkg("docling")
    else:
        for name in cfg.parsers:
            if name == "pymupdf":
                expected[name] = pymupdf_version()
            elif name == "docling":
                expected[name] = docling_version_string()
    return st.config_fingerprint == expected["config"] and all(
        st.parser_versions.get(k) == v for k, v in expected.items()
    )


# ---------------------------------------------------------------------------------------------
# DOCX


def _parse_docx(
    paths: ProjectPaths,
    doc: Document,
    dp: DocPaths,
    cfg: ProjectConfig,
    prog: Progress,
    force: bool,
) -> None:
    versions = parser_versions_for(doc, cfg, None)
    if _skip_if_current(dp, doc, versions, force):
        prog.line("parse", "skip", pages=doc.page_count, detail="up to date")
        return
    from manuallabor.parse.docx import build_docx

    t0 = time.perf_counter()
    ctx = ParseContext(
        slug=doc.slug,
        sha256=doc.sha256,
        page_sizes=(),
        text_layer=(),
        config=cfg,
        paths=paths,
    )
    write_json(
        dp.state,
        ParseState(
            sha256=doc.sha256,
            parser_versions=versions,
            config_fingerprint=versions["config"],
            stages_done=[],
            complete=False,
        ),
    )
    res = build_docx(paths.source(doc.filename), doc.slug, ctx)
    for out in res.outputs:
        write_json(dp.parser_output(out.parser), out)
    prog.line("docx", "done", pages=doc.page_count, t0=t0)
    t1 = time.perf_counter()
    blocks = sorted(res.blocks, key=lambda b: b.reading_order)
    write_json(dp.layout, res.layout)
    write_json(dp.merge, res.report)
    write_json(dp.figures, res.figures)
    write_json(dp.blocks, blocks)
    headers = sorted({b.raw_text for b in blocks if b.type == BlockType.header})
    footers = sorted({b.raw_text for b in blocks if b.type == BlockType.footer})
    new_doc = doc.model_copy(
        update={
            "block_ids": [b.id for b in blocks],
            "parser_versions": versions,
            "stripped_headers": headers,
            "stripped_footers": footers,
            "title": doc.title or res.title,
        }
    )
    write_json(dp.document, Document.model_validate(new_doc.model_dump()))
    write_json(
        dp.state,
        ParseState(
            sha256=doc.sha256,
            parser_versions=versions,
            config_fingerprint=versions["config"],
            stages_done=["docx", "write"],
            complete=True,
        ),
    )
    prog.line("write", "done", pages=doc.page_count, t0=t1, detail=f"{len(blocks)} blocks")


# ---------------------------------------------------------------------------------------------
# PDF


def _ocr_page_parse(
    ocr_mod: Any,
    op: OcrPage | None,
    role: str,
    body: float | None,
    page: int,
    size: tuple[float, float],
) -> PageParse:
    if op is None:
        return PageParse(page=page, width=size[0], height=size[1], has_text_layer=False, blocks=[])
    pp: PageParse = ocr_mod.ocr_page_to_parse(op, role, body)
    blocks = [rb.model_copy(update={"parser": role}) for rb in pp.blocks]
    return pp.model_copy(update={"blocks": blocks, "has_text_layer": False})


def _parse_pdf(
    paths: ProjectPaths,
    doc: Document,
    dp: DocPaths,
    cfg: ProjectConfig,
    rt: Runtime,
    prog: Progress,
    force: bool,
) -> None:
    src = paths.source(doc.filename)
    n = doc.page_count
    sha = doc.sha256
    no_text = set(doc.pages_without_text_layer)
    text_layer = tuple(p not in no_text for p in range(1, n + 1))
    scanned_pages = [p for p in range(1, n + 1) if p in no_text]
    text_pages = [p for p in range(1, n + 1) if p not in no_text]
    need_ocr = bool(scanned_pages) or (cfg.background_ocr_born_digital and bool(text_pages))

    # --- engines and versions -------------------------------------------------------------
    ocr_mod = _ocr_module() if need_ocr else None
    ocr_ad: Any = None
    alt_ad: Any = None
    ocr_versions: dict[str, str] = {}
    ocr_warnings: list[str] = []
    if need_ocr and ocr_mod is not None:
        try:
            ocr_ad, alt_ad = ocr_mod.build_engines(cfg, ocr_warnings.append)
            ocr_versions = dict(ocr_mod.engine_versions(ocr_ad, alt_ad))
        except RuntimeError as exc:
            ocr_warnings.append(str(exc))
            ocr_versions = {"ocr": "unavailable", "ocr_alt": "unavailable"}
    elif need_ocr:
        ocr_warnings.append("OCR module unavailable")
        ocr_versions = {"ocr": "unavailable", "ocr_alt": "unavailable"}
    versions = parser_versions_for(doc, cfg, ocr_versions)
    if _skip_if_current(dp, doc, versions, force):
        prog.line("parse", "skip", pages=n, detail="up to date")
        return
    if "docling" in cfg.parsers:
        ensure_models()
    for w in ocr_warnings:
        prog.line("ocr", "warning", detail=w)

    stages: list[str] = []
    fp = versions["config"]

    def save_state(complete: bool = False) -> None:
        write_json(
            dp.state,
            ParseState(
                sha256=sha,
                parser_versions=versions,
                config_fingerprint=fp,
                stages_done=list(stages),
                complete=complete,
            ),
        )

    save_state()
    sizes = _pdf_page_sizes(src)
    ctx = ParseContext(
        slug=doc.slug,
        sha256=sha,
        page_sizes=tuple(sizes),
        text_layer=text_layer,
        config=cfg,
        paths=paths,
    )

    # --- OCR jobs (render + OCR in the pool, overlapped with the in-process parsers) --------
    ocr_out: dict[str, OcrOutput] = {}
    futures: list[tuple[int, Any]] = []
    t_ocr = time.perf_counter()
    can_ocr = need_ocr and ocr_ad is not None
    if can_ocr:
        existing: dict[str, dict[int, OcrPage]] = {"ocr": {}, "ocr_alt": {}}
        for role in ("ocr", "ocr_alt"):
            f = dp.parser_output(role)
            if f.is_file() and not force:
                try:
                    prev = read_json(f, OcrOutput)
                except ValueError:
                    continue
                cur = ocr_ad.version() if role == "ocr" else (alt_ad.version() if alt_ad else None)
                if prev.version == cur and prev.source_sha256 == sha:
                    existing[role] = {op.page: op for op in prev.pages}
        role_version = {"ocr": ocr_ad.version(), "ocr_alt": alt_ad.version() if alt_ad else ""}
        for p in range(1, n + 1):
            roles: list[str] = []
            if p in no_text:
                roles.append("ocr")
                if alt_ad is not None:
                    roles.append("ocr_alt")
            elif cfg.background_ocr_born_digital:
                roles.append("ocr")
            need = tuple(r for r in roles if p not in existing[r])
            if not need:
                continue
            job = OcrJob(
                pdf_path=str(src),
                page=p,
                size_pt=sizes[p - 1],
                dpi=cfg.ocr_dpi,
                png_path=str(dp.page_png(p)),
                config_json=cfg.model_dump_json(),
                source_sha256=sha,
                roles=need,
                versions=tuple((r, role_version[r]) for r in need),
                partial_paths=tuple((r, str(dp.partial(r, p))) for r in need),
            )
            futures.append((p, rt.pool.submit(job)))
        ocr_pages: dict[str, dict[int, OcrPage]] = {r: dict(v) for r, v in existing.items()}
    else:
        ocr_pages = {"ocr": {}, "ocr_alt": {}}

    # --- in-process parsers ---------------------------------------------------------------
    outputs: dict[str, ParserOutput] = {}
    for name in cfg.parsers:
        t0 = time.perf_counter()
        ver = versions[name]
        reused = None if force else _reuse_output(dp.parser_output(name), name, ver, sha)
        if reused is not None:
            outputs[name] = reused
            prog.line(name, "skip", pages=n, detail="reused")
        else:
            adapter: Any = PyMuPdfAdapter() if name == "pymupdf" else rt.docling()
            outputs[name] = adapter.parse_pdf(src, ctx)
            write_json(dp.parser_output(name), outputs[name])
            prog.line(name, "done", pages=n, t0=t0)
        stages.append(name)

    # --- collect OCR ----------------------------------------------------------------------
    render_ms = 0.0
    rendered = 0
    for p, fut in futures:  # by page index, never as_completed
        res: OcrJobResult = fut.result()
        render_ms += res.render_ms
        rendered += int(res.rendered)
        for role, page in res.pages.items():
            ocr_pages[role][p] = page
    if can_ocr:
        prog.line(
            "render",
            "done",
            pages=len(futures) or None,
            detail=f"{rendered} rendered, {render_ms:.0f} ms in workers",
        )
        prog.line("ocr", "done", pages=len(ocr_pages["ocr"]), t0=t_ocr)
        stages += ["render", "ocr"]
        for role, ad in (("ocr", ocr_ad), ("ocr_alt", alt_ad)):
            if ad is None or not ocr_pages[role]:
                continue
            ocr_out[role] = OcrOutput(
                role=role,  # type: ignore[arg-type]
                engine=ad.engine,
                version=ad.version(),
                source_sha256=sha,
                pages=[ocr_pages[role][p] for p in sorted(ocr_pages[role])],
            )
            write_json(dp.parser_output(role), ocr_out[role])
        if alt_ad is not None and scanned_pages:
            prog.line("ocr_alt", "done", pages=len(ocr_pages["ocr_alt"]))
            stages.append("ocr_alt")
        elif scanned_pages:
            prog.line("ocr_alt", "warning", detail="no second OCR engine available")
    elif need_ocr:
        prog.line("ocr", "warning", detail="OCR skipped: no engine available")
    save_state()

    # --- merge ----------------------------------------------------------------------------
    t0 = time.perf_counter()
    merged_pages, dispositions = _merge_all(
        doc, cfg, outputs, ocr_pages, ocr_mod, text_layer, sizes
    )
    prog.line(
        "merge",
        "done",
        pages=n,
        t0=t0,
        detail=f"{sum(len(m) for m in merged_pages.values())} candidates merged",
    )
    stages.append("merge")

    # --- headers, classification, order, ids -------------------------------------------------
    t0 = time.perf_counter()
    flat: list[tuple[int, MergedBlock]] = [
        (p, mb) for p in sorted(merged_pages) for mb in merged_pages[p]
    ]
    hf_items = [
        HFItem(
            index=i,
            page=p,
            bbox=mb.bbox or [0, 0, 0, 0],
            text=mb.raw_text,
            hint=next(
                (h for h in (mb.hints.get(k) for k in sorted(mb.hints)) if h is not None), None
            ),
            is_region=mb.region != "text" or mb.bbox is None,
            page_height=sizes[p - 1][1],
            is_ocr=not text_layer[p - 1],
        )
        for i, (p, mb) in enumerate(flat)
    ]
    hf = detect_headers_footers(hf_items, n)
    prog.line(
        "headers",
        "done",
        pages=n,
        t0=t0,
        detail=f"{sum(1 for v in hf.values() if v == BlockType.header)} headers, "
        f"{sum(1 for v in hf.values() if v == BlockType.footer)} footers",
    )
    stages.append("headers")

    types = _classify_all(flat, hf, text_layer)
    t0 = time.perf_counter()
    blocks, layouts, figures, block_of = _order_and_ids(
        doc.slug, flat, hf, types, sizes, text_layer, cfg
    )
    prog.line("order", "done", pages=n, t0=t0)
    prog.line("ids", "done", pages=n, detail=f"{len(blocks)} blocks")
    stages += ["order", "ids"]

    report = _build_report(doc.slug, dispositions, block_of, outputs, merged_pages)

    # --- background OCR attachment ----------------------------------------------------------
    if cfg.background_ocr_born_digital and "ocr" in ocr_out and text_pages:
        t0 = time.perf_counter()
        from manuallabor.parse.ocr_attach import attach_ocr

        blocks = attach_ocr(blocks, ocr_out["ocr"], text_layer)
        prog.line("ocr_attach", "done", pages=len(text_pages), t0=t0)
        stages.append("ocr_attach")

    # --- metadata (scanned first pages) -------------------------------------------------------
    new_doc = doc
    t0 = time.perf_counter()
    if (doc.title is None or doc.product_model is None) and not text_layer[0]:
        page1 = [
            ln
            for b_idx, (p, mb) in enumerate(flat)
            if p == 1 and types[b_idx][0] not in (BlockType.header, BlockType.footer)
            for ln in mb.lines
        ]
        body = body_size_of(page1)
        warns: list[str] = []
        provider = metadata_provider(paths, warns.append)
        meta = infer_metadata(
            page1_lines=page1,
            body=body,
            embedded_title=doc.title,
            filename=doc.filename,
            provider=provider,
            warn=warns.append,
            page1_text="\n".join(ln.text for ln in page1),
        )
        updates: dict[str, Any] = {}
        if doc.title is None and meta.title:
            updates["title"] = meta.title
            updates["title_inferred"] = meta.title_inferred
        if doc.product_model is None and meta.product_model:
            updates["product_model"] = meta.product_model
            updates["product_model_inferred"] = meta.product_model_inferred
        if updates:
            new_doc = doc.model_copy(update=updates)
        for w in warns:
            prog.line("metadata", "warning", detail=w[:200])
        prog.line("metadata", "done", pages=1, t0=t0)
        stages.append("metadata")

    # --- write ----------------------------------------------------------------------------
    t0 = time.perf_counter()
    write_json(dp.layout, layouts)
    write_json(dp.merge, report)
    write_json(dp.figures, figures)
    write_json(dp.blocks, blocks)
    headers = sorted({b.raw_text for b in blocks if b.type == BlockType.header})
    footers = sorted({b.raw_text for b in blocks if b.type == BlockType.footer})
    final = new_doc.model_copy(
        update={
            "block_ids": [b.id for b in blocks],
            "parser_versions": versions,
            "stripped_headers": headers,
            "stripped_footers": footers,
        }
    )
    write_json(dp.document, Document.model_validate(final.model_dump()))
    stages.append("write")
    save_state(complete=True)
    # partials are only needed while running
    if dp.partial_dir.is_dir():
        for f in dp.partial_dir.glob("*.json"):
            f.unlink()
        with contextlib.suppress(OSError):
            dp.partial_dir.rmdir()
    prog.line("write", "done", pages=n, t0=t0, detail=f"{len(blocks)} blocks")


# ---------------------------------------------------------------------------------------------
# merge / classify / order


def _merge_all(
    doc: Document,
    cfg: ProjectConfig,
    outputs: dict[str, ParserOutput],
    ocr_pages: dict[str, dict[int, OcrPage]],
    ocr_mod: Any | None,
    text_layer: Sequence[bool],
    sizes: Sequence[tuple[float, float]],
) -> tuple[dict[int, list[MergedBlock]], list[Disposition]]:
    n = doc.page_count
    p_name, s_name = cfg.parsers[0], cfg.parsers[1]
    ocr_lines = [ln for op in ocr_pages["ocr"].values() for ln in op.lines]
    scanned_ocr_lines = [
        ln for p, op in sorted(ocr_pages["ocr"].items()) if not text_layer[p - 1] for ln in op.lines
    ]
    ocr_body = body_size_of(scanned_ocr_lines) if scanned_ocr_lines else body_size_of(ocr_lines)
    merged_pages: dict[int, list[MergedBlock]] = {}
    dispositions: list[Disposition] = []
    for p in range(1, n + 1):
        P: PageParse | None
        S: PageParse | None
        if text_layer[p - 1]:
            P = outputs[p_name].pages[p - 1]
            S = outputs[s_name].pages[p - 1]
            mbs, disps = merge_page(P, S, None, p, names=(p_name, s_name, None))
        else:
            size = sizes[p - 1]
            if ocr_mod is not None:
                P = _ocr_page_parse(ocr_mod, ocr_pages["ocr"].get(p), "ocr", ocr_body, p, size)
                S = (
                    _ocr_page_parse(
                        ocr_mod, ocr_pages["ocr_alt"].get(p), "ocr_alt", ocr_body, p, size
                    )
                    if ocr_pages["ocr_alt"]
                    else None
                )
            else:
                P = PageParse(
                    page=p, width=size[0], height=size[1], has_text_layer=False, blocks=[]
                )
                S = None
            R = outputs["docling"].pages[p - 1] if "docling" in outputs else None
            mbs, disps = merge_page(
                P,
                S,
                R,
                p,
                names=("ocr", "ocr_alt" if S is not None else None, "docling"),
                scanned=True,
            )
            # parsers other than docling see only skipped backgrounds on scanned pages
            for name, out in sorted(outputs.items()):
                if name == "docling":
                    continue
                for sk in out.pages[p - 1].skipped:
                    disps.append(
                        Disposition(
                            parser=name, page=p, order=sk.order, outcome="skipped", detail=sk.reason
                        )
                    )
            # non-docling parsers' candidates on scanned pages (pymupdf blocks, if any) are kept
            for name, out in sorted(outputs.items()):
                if name == "docling":
                    continue
                for rb in out.pages[p - 1].blocks:
                    mbs.append(_stray_block(rb, name, p))
                    disps.append(Disposition(parser=name, page=p, order=rb.order, outcome="alone"))
        merged_pages[p] = mbs
        dispositions.extend(disps)
    return merged_pages, dispositions


def _stray_block(rb: Any, name: str, page: int) -> MergedBlock:
    return MergedBlock(
        page=page,
        region="text"
        if rb.kind not in (BlockType.table, BlockType.figure)
        else ("table" if rb.kind == BlockType.table else "figure"),
        bbox=list(rb.bbox) if rb.bbox else None,
        raw_source=name,
        raw_text=rb.text,
        text_by_parser={name: rb.text},
        order_by_parser={name: rb.order},
        lines=list(rb.lines),
        size=rb.size,
        bold=rb.bold,
        kinds={name: rb.kind},
        members=[(name, rb.order)],
    )


def _classify_all(
    flat: Sequence[tuple[int, MergedBlock]],
    hf: dict[int, BlockType],
    text_layer: Sequence[bool],
) -> list[tuple[BlockType, int | None, str | None]]:
    """Per flat index: (type, heading_level, section_number). Families are classified separately
    because font points (text layer) and OCR word heights are not comparable."""
    result: list[tuple[BlockType, int | None, str | None]] = [(BlockType.other, None, None)] * len(
        flat
    )
    for family in (True, False):
        idxs = [i for i, (p, _) in enumerate(flat) if text_layer[p - 1] == family]
        if not idxs:
            continue
        body_lines = [
            ln
            for i in idxs
            if i not in hf and flat[i][1].region == "text"
            for ln in flat[i][1].lines
        ]
        body = body_size_of(body_lines)
        items = []
        for i in idxs:
            p, mb = flat[i]
            items.append(
                ClassifyInput(
                    page=p,
                    bbox=mb.bbox,
                    region=mb.region,
                    text=mb.raw_text,
                    lines=mb.lines,
                    size=mb.size,
                    bold=mb.bold,
                    docling_kind=mb.kinds.get("docling"),
                    docling_level=mb.heading_levels.get("docling"),
                    forced=hf.get(i),
                )
            )
        for i, c in zip(idxs, classify_blocks(items, body), strict=True):
            result[i] = (c.type, c.heading_level, c.section_number)
    return result


def _order_and_ids(
    slug: str,
    flat: Sequence[tuple[int, MergedBlock]],
    hf: dict[int, BlockType],
    types: list[tuple[BlockType, int | None, str | None]],
    sizes: Sequence[tuple[float, float]],
    text_layer: Sequence[bool],
    cfg: ProjectConfig,
) -> tuple[list[Block], list[PageLayout], list[FigureCandidate], dict[tuple[int, str, int], str]]:
    by_page: dict[int, list[int]] = {}
    for i, (p, _) in enumerate(flat):
        by_page.setdefault(p, []).append(i)
    p_name, s_name = cfg.parsers[0], cfg.parsers[1]
    blocks: list[Block] = []
    layouts: list[PageLayout] = []
    figures: list[FigureCandidate] = []
    block_of: dict[tuple[int, str, int], str] = {}
    reading_order = 0
    for p in sorted(by_page):
        idxs = by_page[p]
        keys = ("ocr", "ocr_alt", "docling") if not text_layer[p - 1] else (p_name, s_name)
        order_items = []
        for i in idxs:
            mb = flat[i][1]
            role = "body"
            if hf.get(i) == BlockType.header:
                role = "header"
            elif hf.get(i) == BlockType.footer:
                role = "footer"
            tb = tuple(mb.order_by_parser.get(k, 10**6) for k in keys)
            order_items.append(OrderItem(bbox=mb.bbox or [0, 0, 0, 0], role=role, tiebreak=tb))  # type: ignore[arg-type]
        seq, bands, cols = order_page_ex(order_items, sizes[p - 1][0], sizes[p - 1][1])
        if len(seq) > MAX_BLOCKS_PER_PAGE:
            raise ParseError(f"page {p} has {len(seq)} blocks; the ID scheme allows 999")
        page_blocks: list[Block] = []
        fig_k = 0
        block_columns: dict[str, int] = {}
        for pos, local in enumerate(seq):
            i = idxs[local]
            mb = flat[i][1]
            btype, level, number = types[i]
            bid = ids.block_id(slug, p, pos + 1)
            fid = None
            if btype == BlockType.figure:
                fig_k += 1
                fid = ids.figure_id(slug, p, fig_k)
            blk = Block(
                id=bid,
                doc_id=slug,
                page=p,
                bbox=mb.bbox,
                type=btype,
                reading_order=reading_order,
                raw_text=mb.raw_text,
                raw_source=mb.raw_source,
                raw_text_by_parser=dict(sorted(mb.text_by_parser.items())),
                order_by_parser=dict(sorted(mb.order_by_parser.items())),
                heading_level=level if btype == BlockType.heading else None,
                section_number=number if btype == BlockType.heading else None,
                table=mb.table if btype == BlockType.table else None,
                ocr_words=mb.ocr_words,
                numeric_tokens=numeric_tokens(mb.raw_text),
                figure_id=fid,
            )
            reading_order += 1
            page_blocks.append(blk)
            block_columns[bid] = cols[local]
            for key in mb.members:
                block_of.setdefault((p, key[0], key[1]), bid)
            if fid is not None:
                figures.append(
                    FigureCandidate(
                        figure_id=fid,
                        block_id=bid,
                        page=p,
                        bbox=mb.bbox,
                        sources=list(mb.sources),
                        image_xrefs=list(mb.image_xrefs),
                        has_drawings=mb.has_drawings,
                        docx_image_rid=mb.docx_image_rid,
                    )
                )
        blocks.extend(page_blocks)
        overlaps: list[Overlap] = []
        for a in range(len(page_blocks)):
            for b in range(a + 1, len(page_blocks)):
                ba, bb = page_blocks[a].bbox, page_blocks[b].bbox
                if ba is None or bb is None:
                    continue
                v = g.iou(ba, bb)
                if v > OVERLAP_IOU:
                    x, y = sorted((page_blocks[a].id, page_blocks[b].id))
                    overlaps.append(Overlap(a=x, b=y, iou=min(1.0, v)))
        overlaps.sort(key=lambda o: (o.a, o.b))
        layouts.append(
            PageLayout(
                page=p,
                source="textlayer" if text_layer[p - 1] else "ocr",
                n_columns=max([len(b.columns) for b in bands], default=1),
                bands=bands,
                block_columns=dict(sorted(block_columns.items())),
                overlaps=overlaps,
            )
        )
    return blocks, layouts, figures, block_of


def _build_report(
    slug: str,
    dispositions: list[Disposition],
    block_of: dict[tuple[int, str, int], str],
    outputs: dict[str, ParserOutput],
    merged_pages: dict[int, list[MergedBlock]],
) -> MergeReport:
    out: list[Disposition] = []
    seen: set[tuple[int, str, int]] = set()
    for d in dispositions:
        key = (d.page, d.parser, d.order)
        if key in seen:
            raise ParseError(f"candidate {key} recorded twice in the merge report")
        seen.add(key)
        if d.outcome == "skipped":
            out.append(d)
            continue
        bid = block_of.get(key)
        if bid is None:
            raise ParseError(f"candidate {key} was not assigned to any block")
        out.append(d.model_copy(update={"block_id": bid}))
    # every parser candidate must be accounted for
    for name, po in outputs.items():
        for page in po.pages:
            for rb in page.blocks:
                if (page.page, name, rb.order) not in seen:
                    raise ParseError(f"candidate {(page.page, name, rb.order)} was dropped")
            for sk in page.skipped:
                if (page.page, name, sk.order) not in seen:
                    raise ParseError(f"skipped {(page.page, name, sk.order)} was dropped")
    out.sort(key=lambda d: (d.page, d.parser, d.order))
    return MergeReport(doc_id=slug, dispositions=out)
