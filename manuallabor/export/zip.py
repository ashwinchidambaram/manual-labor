"""Deterministic zip writer (design 11 section 5.1)."""

from __future__ import annotations

import os
import zipfile
from collections.abc import Mapping
from pathlib import Path

__all__ = ["ZIP_DATE", "tree_files", "write_tree", "write_zip"]

ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_STORED_SUFFIXES = (".png",)


def _bytes(src: str | Path) -> bytes:
    return src.encode("utf-8") if isinstance(src, str) else Path(src).read_bytes()


def write_zip(files: Mapping[str, str | Path | bytes], out: Path) -> None:
    """Entries sorted by path (byte order), fixed timestamps and attributes, PNGs stored,
    text deflated at level 9, no directory entries, no extra fields, no comment. Written to
    `<out>.tmp` and renamed, so a crash leaves no half-written zip."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        for name in sorted(files, key=lambda n: n.encode("utf-8")):
            src = files[name]
            data = src if isinstance(src, bytes) else _bytes(src)
            zi = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            zi.create_system = 3
            zi.external_attr = 0o644 << 16
            zi.compress_type = (
                zipfile.ZIP_STORED if name.endswith(_STORED_SUFFIXES) else zipfile.ZIP_DEFLATED
            )
            if zi.compress_type == zipfile.ZIP_DEFLATED:
                zf.writestr(zi, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            else:
                zf.writestr(zi, data, compress_type=zipfile.ZIP_STORED)
    os.replace(tmp, out)


def write_tree(files: Mapping[str, str | Path], root: Path) -> None:
    """Write the zip layout under `root` (the staging tree)."""
    for name, src in files.items():
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(src, str):
            dest.write_text(src, encoding="utf-8", newline="\n")
        else:
            dest.write_bytes(Path(src).read_bytes())


def tree_files(root: Path) -> dict[str, Path]:
    """Every file of a staging tree by zip path."""
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}
