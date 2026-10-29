"""Advisory project locks (fcntl.flock; macOS and Linux only)."""

from __future__ import annotations

import fcntl
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from manuallabor.state.errors import LockHeld


def read_owner(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class ProjectLock:
    """Exclusive non-blocking lock on a file; the kernel releases it when the process dies."""

    def __init__(self, path: Path, cmd: str | None = None) -> None:
        self.path = Path(path)
        self.cmd = cmd if cmd is not None else " ".join(sys.argv)
        self._fd: int | None = None

    def acquire(self, *, nonblocking: bool = True) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        except OSError as exc:
            os.close(fd)
            raise LockHeld(read_owner(self.path)) from exc
        os.ftruncate(fd, 0)
        body = {
            "pid": os.getpid(),
            "cmd": self.cmd,
            "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        os.write(fd, json.dumps(body).encode("utf-8"))
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def __enter__(self) -> ProjectLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
