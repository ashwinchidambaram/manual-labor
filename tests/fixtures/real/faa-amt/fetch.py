"""Fetch the public-domain FAA AMT General Handbook and cut out Chapter 7 (born-digital).

Usage: uv run python tests/fixtures/real/faa-amt/fetch.py

faa.gov no longer publishes per-chapter PDFs, only the whole handbook (~88 MiB), so this
downloads the original PDF into source/, verifies its sha256, and writes pages 245-324
(Chapter 7) unchanged to faa-amt.pdf with PyMuPDF (page content streams, fonts and images are
copied as-is; no re-rendering, text layer preserved). Idempotent. Nothing downloaded is executed.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = "https://www.faa.gov/regulations_policies/handbooks_manuals/aviation/amtg_handbook.pdf"
SOURCE = HERE / "source" / "amtg_handbook.pdf"
OUTPUT = HERE / "faa-amt.pdf"
SOURCE_SHA256 = "0a39c01bbc454e77a49813cf27e2ef291756fa7111d9308bc290cd0eb71616fd"
FIRST_PAGE, LAST_PAGE = 245, 324  # 1-based, inclusive: Chapter 7
MAX_OUT_BYTES = 40 * 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download() -> None:
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    if SOURCE.exists() and sha256_file(SOURCE) == SOURCE_SHA256:
        return
    tmp = SOURCE.with_suffix(".part")
    req = urllib.request.Request(
        URL, headers={"User-Agent": "Mozilla/5.0 manual-labor-fixture-fetch/1"}
    )
    with urllib.request.urlopen(req, timeout=300) as r, tmp.open("wb") as f:  # noqa: S310
        while chunk := r.read(1 << 20):
            f.write(chunk)
    got = sha256_file(tmp)
    if got != SOURCE_SHA256:
        tmp.unlink()
        sys.exit(f"sha256 mismatch for {URL}: expected {SOURCE_SHA256}, got {got}")
    tmp.replace(SOURCE)


def build() -> None:
    import pymupdf

    src = pymupdf.open(str(SOURCE))
    out = pymupdf.open()
    out.insert_pdf(
        src, from_page=FIRST_PAGE - 1, to_page=LAST_PAGE - 1
    )  # select() would keep all shared resources (~90 MB)
    out.set_metadata(
        {"title": "FAA AMT Handbook General (FAA-H-8083-30B) Chapter 7 (fixture)", "author": "FAA"}
    )
    tmp = OUTPUT.with_suffix(".tmp")
    out.save(str(tmp), garbage=4, deflate=True, no_new_id=True)
    out.close()
    src.close()
    if tmp.stat().st_size > MAX_OUT_BYTES:
        tmp.unlink()
        sys.exit("output exceeds 40 MB")
    tmp.replace(OUTPUT)


def main() -> None:
    download()
    build()
    print(f"source sha256: {sha256_file(SOURCE)}")
    print(f"output {OUTPUT} bytes={OUTPUT.stat().st_size}")
    print(f"output sha256: {sha256_file(OUTPUT)}")


if __name__ == "__main__":
    main()
