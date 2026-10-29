"""Byte-stable OpenAPI dump (design 07 section 5.4)."""

from __future__ import annotations

import json
from pathlib import Path

from manuallabor.api.app import create_app

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "openapi.json"


def openapi_text() -> str:
    spec = create_app(None).openapi()
    return json.dumps(spec, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def export_openapi(out: Path = DEFAULT_OUT, *, check: bool = False) -> bool:
    """Write the spec. Returns True when the file is (now) up to date; with `check`, writes
    nothing and returns False on drift."""
    text = openapi_text()
    current = out.read_text(encoding="utf-8") if out.is_file() else None
    if current == text:
        return True
    if check:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return True
