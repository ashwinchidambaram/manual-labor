"""Export JSON Schemas for the contract models."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from manuallabor.contracts.io import dump_json, write_text_atomic


def _models() -> tuple[type[BaseModel], ...]:
    from manuallabor.contracts import EXPORTED_MODELS

    return EXPORTED_MODELS


def render_schemas() -> dict[str, str]:
    models = _models()
    out = {
        f"{m.__name__}.json": dump_json(m.model_json_schema(mode="serialization")) for m in models
    }
    _, top = models_json_schema(
        [(m, "serialization") for m in models], title="ManualLaborContracts"
    )
    out["_all.json"] = dump_json(top)
    return out


def export_schemas(out_dir: Path, check: bool = False) -> list[Path]:
    """Write schemas; with check=True write nothing and return the paths that would change."""
    out_dir = Path(out_dir)
    rendered = render_schemas()
    changed: list[Path] = []
    for name, text in rendered.items():
        p = out_dir / name
        if not p.exists() or p.read_text(encoding="utf-8") != text:
            changed.append(p)
    stale = (
        [p for p in sorted(out_dir.glob("*.json")) if p.name not in rendered]
        if out_dir.exists()
        else []
    )
    if check:
        return changed + stale
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in changed:
        write_text_atomic(p, rendered[p.name])
    for p in stale:
        p.unlink()
    return [out_dir / n for n in rendered]
