"""Canonical JSON serialization and atomic file IO."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, Mapping):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def dump_json(obj: BaseModel | Sequence[Any] | Mapping[str, Any]) -> str:
    return json.dumps(to_jsonable(obj), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def canonical_json(obj: Any) -> bytes:
    return json.dumps(
        to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def write_json(path: Path, obj: BaseModel | Sequence[Any] | Mapping[str, Any]) -> None:
    write_text_atomic(path, dump_json(obj))


def read_json[M: BaseModel](path: Path, model: type[M]) -> M:
    return model.model_validate_json(Path(path).read_text(encoding="utf-8"))


def read_json_list[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    return TypeAdapter(list[model]).validate_json(Path(path).read_text(encoding="utf-8"))  # type: ignore[valid-type]
