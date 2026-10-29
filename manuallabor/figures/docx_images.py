"""DOCX image extraction (design section 8)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from manuallabor.figures.encode import encode_png, sha256_bytes

_FORMAT_NAMES = {"JPEG": "jpeg", "GIF": "gif", "BMP": "bmp", "TIFF": "tiff", "PNG": "png"}


class UnsupportedImage(Exception):
    pass


@dataclass
class DocxRaster:
    png: bytes
    image: Image.Image
    source_format: str
    source_sha256: str
    effective_dpi: float | None


class DocxImages:
    """Opens the .docx once and extracts images by relationship id."""

    def __init__(self, path: Path) -> None:
        import docx

        self._doc: Any = docx.Document(str(path))
        self._widths: dict[str, int] = {}
        a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        r_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        for shape in self._doc.inline_shapes:
            for blip in shape._inline.iter(f"{{{a_ns}}}blip"):
                rid = blip.get(f"{{{r_ns}}}embed")
                if rid is not None and rid not in self._widths:
                    self._widths[rid] = int(shape.width)

    def extract(self, rid: str) -> DocxRaster:
        part = self._doc.part.related_parts.get(rid)
        if part is None:
            raise UnsupportedImage("no_image_part")
        blob: bytes = part.blob
        ctype = str(getattr(part, "content_type", ""))
        try:
            img = Image.open(io.BytesIO(blob))
            img.load()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise UnsupportedImage(f"unsupported_format:{ctype or 'unknown'}") from exc
        fmt = _FORMAT_NAMES.get(str(img.format))
        if fmt is None:
            raise UnsupportedImage(f"unsupported_format:{ctype or img.format}")
        png = blob if fmt == "png" else encode_png(img)
        width_emu = self._widths.get(rid)
        dpi = round(img.width / (width_emu / 914400), 1) if width_emu else None
        return DocxRaster(png, img, fmt, sha256_bytes(blob), dpi)
