"""Fetch the public-domain 1944 scanned TM and build an image-only PDF for live tests.

Usage: uv run python tests/fixtures/real/old-scan/fetch.py

Downloads the archive.org PDF into source/, verifies its sha256, then renders each
page to grayscale JPEG (min(source DPI, 300)) and writes old-scan.pdf with no text
layer. Idempotent; prints the output sha256. Nothing downloaded is executed.
"""

from __future__ import annotations

import hashlib
import io
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
IDENT = "micro_IA41152616_0619"
URL = f"https://archive.org/download/{IDENT}/{IDENT}.pdf"
SOURCE = HERE / "source" / f"{IDENT}.pdf"
OUTPUT = HERE / "old-scan.pdf"
SOURCE_SHA256 = "c4bf2b2d5fa2b7904c7ce97ec78501b1a4e461f0952b28b557f2357026fb2837"
MAX_DPI = 300
JPEG_QUALITY = 80
MAX_OUT_BYTES = 40 * 1024 * 1024
PDF_DATE = "D:20260101000000Z"
TITLE = "TM 11-427 Barometers ML-102 (real old scanned fixture)"


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
    req = urllib.request.Request(URL, headers={"User-Agent": "manual-labor-fixture-fetch/1"})
    with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as f:  # noqa: S310
        while chunk := r.read(1 << 20):
            f.write(chunk)
    got = sha256_file(tmp)
    if got != SOURCE_SHA256:
        tmp.unlink()
        sys.exit(f"sha256 mismatch for {URL}: expected {SOURCE_SHA256}, got {got}")
    tmp.replace(SOURCE)


def build() -> None:
    import pymupdf
    from PIL import Image

    src = pymupdf.open(str(SOURCE))
    out = pymupdf.open()
    for page in src:
        widths = [im[2] for im in page.get_images(full=True)]
        src_dpi = max(widths) / page.rect.width * 72.0 if widths else MAX_DPI
        dpi = int(min(MAX_DPI, round(src_dpi)))
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=False, subsampling=0)
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, stream=buf.getvalue())
    out.set_metadata(
        {
            "title": TITLE,
            "author": "Manual Labor fixtures",
            "subject": "Manual Labor live-only fixture (image-only)",
            "creator": "Manual Labor fixtures",
            "producer": "Manual Labor fixtures",
            "keywords": "",
            "creationDate": PDF_DATE,
            "modDate": PDF_DATE,
        }
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
