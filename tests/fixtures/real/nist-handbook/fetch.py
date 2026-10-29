"""Fetch the public-domain NIST Handbook 44 (2026) Section 2.20 Scales PDF for live tests.

Usage: uv run python tests/fixtures/real/nist-handbook/fetch.py

Downloads the born-digital PDF into source/, verifies its sha256 and copies it unchanged to
nist-handbook.pdf. Idempotent; prints the output sha256. Nothing downloaded is executed.
Note: NIST replaces Handbook 44 every year at this URL; a sha256 mismatch means the 2026
edition was superseded (the fixture and ground truth are pinned to the file hashed below).
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = "https://www.nist.gov/document/2026-nist-handbook-44-section-220"
SOURCE = HERE / "source" / "nist-hb44-section-2-20.pdf"
OUTPUT = HERE / "nist-handbook.pdf"
SOURCE_SHA256 = "6bfca74e62c7b324d640f1fc2ff916313944b40f4b5b91ea82d8f4448a60aaa9"
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
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 manual-labor-fixture-fetch/1"})
    with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as f:  # noqa: S310
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if tmp.read_bytes()[:5] != b"%PDF-":
        tmp.unlink()
        sys.exit(f"{URL} did not return a PDF")
    got = sha256_file(tmp)
    if got != SOURCE_SHA256:
        tmp.unlink()
        sys.exit(f"sha256 mismatch for {URL}: expected {SOURCE_SHA256}, got {got}")
    tmp.replace(SOURCE)


def build() -> None:
    if SOURCE.stat().st_size > MAX_OUT_BYTES:
        sys.exit("output exceeds 40 MB")
    shutil.copyfile(SOURCE, OUTPUT)


def main() -> None:
    download()
    build()
    print(f"source sha256: {sha256_file(SOURCE)}")
    print(f"output {OUTPUT} bytes={OUTPUT.stat().st_size}")
    print(f"output sha256: {sha256_file(OUTPUT)}")


if __name__ == "__main__":
    main()
