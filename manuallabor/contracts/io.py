"""Canonical JSON serialization and atomic file IO."""

from __future__ import annotations

import json
import os
import uuid
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


TMP_SUFFIX = ".tmp"
"""Temp suffix for writers holding the worker lock (pipeline stages). The job's start-up cleaner
(`jobs.executor.clean_stray_tmp`) removes `*.tmp` leftovers under docs/, figures/, learning/."""

PART_SUFFIX = ".part"
"""Temp suffix for writers outside the worker lock (API projections, learning snapshots, page
renders, uploads). Only `jobs.executor.clean_stray_parts` removes `*.part` leftovers, at serve
start-up while both project locks are held (design 07 section 14.1)."""


def temp_path(path: Path, suffix: str = TMP_SUFFIX) -> Path:
    """A temp name next to `path`, unique per call: two writers of one file never share it."""
    return path.with_name(f"{path.name}.{uuid.uuid4().hex}{suffix}")


def fsync_dir(directory: Path) -> None:
    """Make a rename in `directory` durable (POSIX). Best effort where a dir cannot be opened."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_text_atomic(path: Path, text: str, *, suffix: str = TMP_SUFFIX) -> None:
    """Write `text` to a unique temp file, fsync it, rename it over `path`, fsync the directory.

    `suffix` says who may clean a leftover: `TMP_SUFFIX` under the worker lock, `PART_SUFFIX`
    outside it (see the two constants)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_path(path, suffix)
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    fsync_dir(path.parent)


def write_json(
    path: Path, obj: BaseModel | Sequence[Any] | Mapping[str, Any], *, suffix: str = TMP_SUFFIX
) -> None:
    write_text_atomic(path, dump_json(obj), suffix=suffix)


def read_json[M: BaseModel](path: Path, model: type[M]) -> M:
    return model.model_validate_json(Path(path).read_text(encoding="utf-8"))


def read_json_list[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    return TypeAdapter(list[model]).validate_json(Path(path).read_text(encoding="utf-8"))  # type: ignore[valid-type]
