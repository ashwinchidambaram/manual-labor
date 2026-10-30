"""Two uploads of the same file name at the same moment must not share a temp file (code review
F16): they used to write `.uploads/.incoming-<sha(name)>` together, interleave bytes, and land a
corrupt file under a wrong content hash (or fail the second move)."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest

from manuallabor.api.routers.sources import _save_upload


class _Upload:
    """The part of `UploadFile` `_save_upload` uses; `on_first_chunk` runs mid-stream."""

    def __init__(self, name: str, data: bytes, on_first_chunk: Any = None) -> None:
        self.filename = name
        self._data = io.BytesIO(data)
        self._hook = on_first_chunk
        self.file = self

    def read(self, n: int = -1) -> bytes:
        chunk = self._data.read(min(n, 4))
        if self._hook is not None and chunk:
            hook, self._hook = self._hook, None
            hook()
        return chunk


def test_same_named_uploads_in_flight_together_both_land_intact(tmp_path: Path) -> None:
    uploads = tmp_path / ".uploads"
    a, b = b"first manual bytes", b"second, different manual"
    inner: list[Path] = []

    def second() -> None:
        inner.append(_save_upload(uploads, _Upload("manual.pdf", b)))  # type: ignore[arg-type]

    outer = _save_upload(uploads, _Upload("manual.pdf", a, second))  # type: ignore[arg-type]
    for path, data in ((outer, a), (inner[0], b)):
        assert path.read_bytes() == data
        assert path.parent.name == hashlib.sha256(data).hexdigest()
        assert path.name == "manual.pdf"
    leftovers = [p.name for p in uploads.iterdir() if p.is_file()]
    assert leftovers == [], leftovers


def test_a_failed_upload_leaves_no_temp_file(tmp_path: Path) -> None:
    uploads = tmp_path / ".uploads"

    def boom() -> None:
        raise ConnectionResetError("client went away")

    with pytest.raises(ConnectionResetError):
        _save_upload(uploads, _Upload("manual.pdf", b"partial bytes", boom))  # type: ignore[arg-type]
    assert list(uploads.iterdir()) == []
