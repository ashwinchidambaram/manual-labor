"""`write_text_atomic` is durable: the data reaches the disk before the rename that publishes it
(code review F14). Without the file fsync, a crash can make the rename durable while the data is
not, leaving a zero-length `blocks.json` or `document.json` behind the new name."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from manuallabor.contracts import io as cio


class _Recorder:
    """`os` for the io module, recording fsync and replace in order."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def fsync(self, fd: int) -> None:
        mode = os.fstat(fd).st_mode
        self.events.append(("fsync", "dir" if stat.S_ISDIR(mode) else "file"))
        os.fsync(fd)

    def replace(self, src: object, dst: object) -> None:
        self.events.append(("replace", Path(str(dst)).name))
        os.replace(src, dst)  # type: ignore[arg-type]

    def __getattr__(self, name: str) -> object:
        return getattr(os, name)


def test_write_text_atomic_fsyncs_the_file_before_the_rename_and_the_dir_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _Recorder()
    monkeypatch.setattr(cio, "os", rec)
    target = tmp_path / "sub" / "blocks.json"
    cio.write_text_atomic(target, "[]\n")
    assert target.read_text(encoding="utf-8") == "[]\n"
    assert rec.events == [("fsync", "file"), ("replace", "blocks.json"), ("fsync", "dir")]
    assert sorted(p.name for p in target.parent.iterdir()) == ["blocks.json"]


def test_a_failed_write_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Boom(_Recorder):
        def replace(self, src: object, dst: object) -> None:
            raise OSError("disk full")

    monkeypatch.setattr(cio, "os", _Boom())
    target = tmp_path / "x.json"
    with pytest.raises(OSError, match="disk full"):
        cio.write_text_atomic(target, "{}\n")
    assert list(tmp_path.iterdir()) == []
