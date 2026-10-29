"""Deterministic PNG encoding and hashing."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

from PIL import Image


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_mode(img: Image.Image) -> Image.Image:
    """Return an image in one of L, LA, RGB, RGBA (the modes we encode)."""
    if img.mode in ("L", "LA", "RGB", "RGBA"):
        return img
    if img.mode == "P":
        return img.convert("RGBA" if "transparency" in img.info else "RGB")
    if img.mode in ("1", "I;16", "I", "F"):
        return img.convert("L")
    if img.mode == "PA":
        return img.convert("RGBA")
    return img.convert("RGB")


def encode_png(img: Image.Image) -> bytes:
    """One encoder for every PNG we write: fixed params, no metadata chunks."""
    buf = io.BytesIO()
    normalize_mode(img).save(buf, "PNG", optimize=False, compress_level=6)
    return buf.getvalue()


def has_alpha(img: Image.Image) -> bool:
    return img.mode in ("LA", "RGBA")


def composite_on_white(img: Image.Image) -> Image.Image:
    img = normalize_mode(img)
    if not has_alpha(img):
        return img
    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    bg.alpha_composite(rgba)
    return bg.convert("RGB")


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_if_changed(path: Path, data: bytes) -> bool:
    """Write atomically unless the file already holds exactly these bytes."""
    if path.is_file() and path.read_bytes() == data:
        return False
    write_bytes_atomic(path, data)
    return True
