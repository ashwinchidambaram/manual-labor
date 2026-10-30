"""Docling PDF adapter (design 01-parse section 4.2 and 4.3). Offline, cached models only."""

from __future__ import annotations

import importlib.metadata as md
import os
from pathlib import Path
from typing import Any

from manuallabor.contracts.enums import BlockType
from manuallabor.parse import geometry as g
from manuallabor.parse.types import (
    PageParse,
    ParseContext,
    ParserOutput,
    ParserUnavailable,
    RawBlock,
    Skipped,
)

NAME = "docling"
NUM_THREADS = 4
MODEL_REPOS = (
    "models--docling-project--docling-layout-heron",
    "models--docling-project--docling-models",
)

_CONVERTER: Any = None


def hf_cache_dir() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def docling_cache_dir() -> Path:
    """Docling's own cache directory: where `docling-tools models download` writes `models/`."""
    try:
        from docling.datamodel.settings import settings
    except Exception:  # docling not importable: fall back to its documented default
        return Path.home() / ".cache" / "docling"
    return Path(settings.cache_dir)


def docling_artifacts_dir() -> Path | None:
    """`<docling cache>/models` when it holds both model repos this parser needs.

    The folder alone is not enough: docling creates it before downloading, and OCR models
    download into it on first use. Under an artifacts path docling never falls back to the
    hub cache, so a partial folder must not win over a complete hub cache.
    """
    local = docling_cache_dir() / "models"
    names = [r.removeprefix("models--") for r in MODEL_REPOS]
    return local if all((local / n).is_dir() for n in names) else None


def artifacts_path() -> Path | None:
    """The explicit artifacts directory, else the one `docling-tools models download` filled.

    None means "let docling resolve the Hugging Face hub cache itself".
    """
    p = os.environ.get("MANUALLABOR_DOCLING_ARTIFACTS")
    if p:
        return Path(p)
    return docling_artifacts_dir()


def models_cached() -> bool:
    if artifacts_path() is not None:
        return artifacts_path().is_dir()  # type: ignore[union-attr]
    cache = hf_cache_dir()
    return all((cache / r).is_dir() for r in MODEL_REPOS)


def docling_version_string() -> str:
    parts = []
    for pkg in ("docling", "docling-ibm-models"):
        try:
            parts.append(f"{pkg}=={md.version(pkg)}")
        except md.PackageNotFoundError:
            parts.append(f"{pkg}==unknown")
    refs = []
    cache = hf_cache_dir()
    for r in MODEL_REPOS:
        ref = cache / r / "refs" / "main"
        name = r.removeprefix("models--").replace("--", "/")
        if ref.is_file():
            refs.append(f"{name}@{ref.read_text().strip()[:12]}")
        elif (snap := cache / r / "snapshots").is_dir() and any(snap.iterdir()):
            refs.append(f"{name}@{sorted(x.name for x in snap.iterdir())[0][:12]}")
        elif artifacts_path() is not None:
            refs.append(f"{name}@artifacts")
        else:
            refs.append(f"{name}@unknown")
    return "; ".join(parts) + "; models=" + ",".join(sorted(refs))


def ensure_models() -> None:
    if os.environ.get("MANUALLABOR_ALLOW_MODEL_DOWNLOAD") == "1":
        return
    if not models_cached():
        raise ParserUnavailable(
            "docling models not cached; run: uv run docling-tools models download"
        )
    os.environ.setdefault("HF_HUB_OFFLINE", "1")


def _determinism() -> None:
    import torch

    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True, warn_only=True)


def get_pdf_converter() -> Any:
    global _CONVERTER
    if _CONVERTER is not None:
        return _CONVERTER
    ensure_models()
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        generate_page_images=False,
        generate_picture_images=False,
    )
    opts.table_structure_options.do_cell_matching = True  # type: ignore[attr-defined]
    opts.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CPU, num_threads=NUM_THREADS
    )
    ap = artifacts_path()
    if ap is not None:
        opts.artifacts_path = str(ap)
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    _determinism()
    conv.initialize_pipeline(InputFormat.PDF)
    _CONVERTER = conv
    return conv


def quant_half(x: float) -> float:
    return round(x * 2.0) / 2.0 + 0.0


def _top_left(prov: Any, page_height: float) -> tuple[float, float, float, float]:
    bb = prov.bbox
    if bb.coord_origin.value != "BOTTOMLEFT":
        raise AssertionError(f"unexpected docling coord origin {bb.coord_origin}")
    tl = bb.to_top_left_origin(page_height=page_height)
    return (float(tl.l), float(tl.t), float(tl.r), float(tl.b))


_LABEL_KIND: dict[str, BlockType] = {
    "title": BlockType.heading,
    "section_header": BlockType.heading,
    "text": BlockType.paragraph,
    "paragraph": BlockType.paragraph,
    "list_item": BlockType.list,
    "caption": BlockType.caption,
    "page_header": BlockType.paragraph,
    "page_footer": BlockType.paragraph,
    "table": BlockType.table,
    "picture": BlockType.figure,
    "chart": BlockType.figure,
}


def docling_items_to_pages(doc: Any, ctx: ParseContext) -> list[PageParse]:
    """Turn a DoclingDocument into PageParse objects (shared by PDF and DOCX paths)."""
    from docling_core.types.doc.document import ContentLayer  # type: ignore[attr-defined]

    try:
        from manuallabor.parse import tables as tables_mod
    except ImportError:  # pragma: no cover
        tables_mod = None  # type: ignore[assignment]

    n_pages = len(ctx.page_sizes)
    blocks: dict[int, list[RawBlock]] = {p: [] for p in range(1, n_pages + 1)}
    skipped: dict[int, list[Skipped]] = {p: [] for p in range(1, n_pages + 1)}
    counters: dict[int, int] = dict.fromkeys(range(1, n_pages + 1), 0)
    open_list: dict[int, RawBlock | None] = dict.fromkeys(range(1, n_pages + 1))
    open_list_parent: dict[int, str | None] = dict.fromkeys(range(1, n_pages + 1))

    layers = {ContentLayer.BODY, ContentLayer.FURNITURE}
    for item, _level in doc.iterate_items(included_content_layers=layers):
        label = str(getattr(item.label, "value", item.label))
        provs = list(getattr(item, "prov", []) or [])
        if not provs:
            continue
        full_text = getattr(item, "text", "") or ""
        for prov in provs:
            page_no = int(prov.page_no)
            if page_no not in blocks:
                continue
            page_h = float(doc.pages[page_no].size.height)
            has_text = ctx.text_layer[page_no - 1]
            x0, y0, x1, y1 = _top_left(prov, page_h)
            kind = _LABEL_KIND.get(label, BlockType.other)
            hint = label if label in ("page_header", "page_footer") else None
            order = counters[page_no]
            if kind in (BlockType.figure, BlockType.table):
                box = [quant_half(x0), quant_half(y0), quant_half(x1), quant_half(y1)]
                table = None
                if kind == BlockType.table and tables_mod is not None:
                    cand = tables_mod.from_docling(item)
                    table = cand if cand.cells else None
                blocks[page_no].append(
                    RawBlock(
                        parser=NAME,
                        page=page_no,
                        order=order,
                        bbox=box,
                        kind=kind,
                        text="",
                        table=table,
                        layout_only=not has_text,
                        hint=label if label in ("chart",) else None,
                    )
                )
                counters[page_no] += 1
                open_list[page_no] = None
                continue
            text = full_text
            if len(provs) > 1 and prov.charspan:
                text = full_text[prov.charspan[0] : prov.charspan[1]]
            text = text.strip("\n")
            box = g.qbox((x0, y0, x1, y1))
            if not has_text or not text.strip():
                skipped[page_no].append(
                    Skipped(page=page_no, order=order, bbox=box, reason="empty_text")
                )
                counters[page_no] += 1
                continue
            parent = item.parent.cref if getattr(item, "parent", None) else None
            if kind == BlockType.list:
                cur = open_list[page_no]
                if cur is not None and open_list_parent[page_no] == parent:
                    merged_box = g.union([cur.bbox or box, box])
                    blocks[page_no][-1] = cur.model_copy(
                        update={"text": cur.text + "\n" + text, "bbox": merged_box}
                    )
                    open_list[page_no] = blocks[page_no][-1]
                    continue
            rb = RawBlock(
                parser=NAME,
                page=page_no,
                order=order,
                bbox=box,
                kind=kind,
                text=text,
                hint=hint,
                heading_level=(
                    max(1, min(6, int(getattr(item, "level", 1) or 1)))
                    if kind == BlockType.heading
                    else None
                ),
                layout_only=False,
            )
            blocks[page_no].append(rb)
            counters[page_no] += 1
            if kind == BlockType.list:
                open_list[page_no] = rb
                open_list_parent[page_no] = parent
            else:
                open_list[page_no] = None
    out: list[PageParse] = []
    for p in range(1, n_pages + 1):
        w, h = ctx.page_sizes[p - 1]
        out.append(
            PageParse(
                page=p,
                width=w,
                height=h,
                has_text_layer=ctx.text_layer[p - 1],
                blocks=blocks[p],
                skipped=skipped[p],
            )
        )
    return out


class DoclingAdapter:
    name = NAME

    def __init__(self) -> None:
        ensure_models()

    def version(self) -> str:
        return docling_version_string()

    def parse_pdf(self, path: Path, ctx: ParseContext) -> ParserOutput:
        conv = get_pdf_converter()
        _determinism()
        result = conv.convert(str(path))
        pages = docling_items_to_pages(result.document, ctx)
        return ParserOutput(
            parser=NAME, version=self.version(), source_sha256=ctx.sha256, pages=pages
        )
