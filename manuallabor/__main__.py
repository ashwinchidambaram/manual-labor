"""`python -m manuallabor ...` is `labor ...` (the guard matters: parse spawns an OCR pool)."""

from __future__ import annotations

if __name__ == "__main__":
    from manuallabor.cli import app

    app()
