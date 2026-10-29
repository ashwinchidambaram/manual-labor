"""The vision reader: an optional third reader of a numeric block's numbers (design 10 3.7).

It emits no score and no confidence. Its numbers are used only as an attester in the number
check (`recheck.numeric_attested`), as evidence source `vision` and as a pane in the Agent
screen. It never attests text and never touches scores.json."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Final

from manuallabor.agent.types import (
    VREAD_DPI,
    VREAD_LONG_SIDE,
    VREAD_MARGIN_PT,
    VREAD_MAX_LINE,
    VREAD_PROMPT_VERSION,
)
from manuallabor.contracts.block import Block, VisionReading
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.enums import DocKind, FlagCategory, Task
from manuallabor.providers.base import Provider, ProviderError
from manuallabor.scoring.faithfulness import numeric_tokens

VREAD_PROMPT: Final = (
    f"{VREAD_PROMPT_VERSION}. Transcribe every number in this image exactly as printed, with "
    "its unit or symbol, in reading order, one per line. Use only characters you can see. "
    "Write ? for a character you cannot read. Output only the lines."
)
_LINE_RE: Final = re.compile(r"^[0-9A-Za-z.,:/±+\-×x°%·µΩ\"'?() ]+$")


def skipped(detail: str) -> VisionReading:
    return VisionReading(outcome="skipped", detail=detail)


def skip_reason(
    block: Block,
    doc_kind: DocKind,
    category: FlagCategory,
    cfg: ProjectConfig,
) -> str | None:
    """Why the vision reader does not run for this item (None: it runs)."""
    if not cfg.agent.vision_reader:
        return "agent.vision_reader is off"
    if category not in (FlagCategory.wrong_text, FlagCategory.table_structure):
        return "category does not read numbers"
    if not block.has_numeric_spec:
        return "block has no numeric spec"
    if doc_kind == DocKind.docx:
        return "DOCX has no page image"
    if block.bbox is None:
        return "block has no bbox"
    if cfg.model_for(Task.vision) is None:
        return "no vision model configured"
    return None


def crop_block_png(pdf_path: Path, page: int, bbox: list[float]) -> bytes:
    """Gray 300-DPI crop of bbox +- 4 pt, Lanczos-downscaled to a long side of <= 1024 px."""
    from PIL import Image

    from manuallabor.parse.pdf_pymupdf import open_pdf, pm

    with open_pdf(pdf_path) as doc:
        pg = doc[page - 1]
        r = pg.rect
        m = VREAD_MARGIN_PT
        clip = pm().Rect(
            max(r.x0, bbox[0] - m),
            max(r.y0, bbox[1] - m),
            min(r.x1, bbox[2] + m),
            min(r.y1, bbox[3] + m),
        )
        pix = pg.get_pixmap(clip=clip, dpi=VREAD_DPI, colorspace=pm().csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    long_side = max(img.size)
    if long_side > VREAD_LONG_SIDE:
        k = VREAD_LONG_SIDE / long_side
        img = img.resize(
            (max(1, round(img.width * k)), max(1, round(img.height * k))), Image.Resampling.LANCZOS
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def validate_vread(text: str, raw_numeric_count: int) -> tuple[list[str], list[str], str | None]:
    """(kept lines, numbers, problem). A problem makes the reading `invalid` (no numbers)."""
    lines = [
        ln
        for ln in (x.strip() for x in text.splitlines())
        if ln and len(ln) <= VREAD_MAX_LINE and _LINE_RE.match(ln)
    ]
    if not lines:
        return [], [], "no usable line"
    numbers = [t for ln in lines if "?" not in ln for t in numeric_tokens(ln)]
    if len(numbers) > 3 * max(1, raw_numeric_count):
        return lines, [], "too many numbers for the block"
    return lines, numbers, None


def read_numbers(provider: Provider, png: bytes, raw_numeric_count: int) -> VisionReading:
    model = f"{provider.ref.provider}/{provider.ref.model}"
    sha = hashlib.sha256(png).hexdigest()
    try:
        res = provider.vision(Task.vision, png, VREAD_PROMPT)
    except ProviderError as exc:
        return VisionReading(model=model, image_sha256=sha, outcome="error", detail=str(exc)[:300])
    lines, numbers, problem = validate_vread(res.text, raw_numeric_count)
    return VisionReading(
        model=model,
        image_sha256=sha,
        lines=lines,
        numbers=numbers,
        outcome="invalid" if problem else "ok",
        detail=problem,
        input_hash=res.log.input_hash,
    )
