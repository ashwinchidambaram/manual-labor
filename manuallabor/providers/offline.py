"""Runtime network guard for `MANUALLABOR_OFFLINE=1` (design 11 section 9, SPEC 11.8).

With the guard installed, a process can reach only the local model server (`OLLAMA_HOST`,
default 127.0.0.1:11434) and AF_UNIX sockets. Any other destination is appended to
`$MANUALLABOR_OFFLINE_LOG` (default `<tmp>/offline-violations.log`) and raises
`OSError("offline guard")`; the log catches violations a caller swallowed. This module is the
only place outside the providers' own clients that may import `socket`."""

from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = ["DEFAULT_HOST", "install_from_env", "install_guard", "ollama_endpoint", "violation_log"]

DEFAULT_HOST = "127.0.0.1:11434"
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})
_installed: list[bool] = []


def ollama_endpoint(raw: str | None = None) -> tuple[str, int]:
    """(host, port) of OLLAMA_HOST in any of its spellings (`host`, `host:port`, `http://...`)."""
    value = (raw if raw is not None else os.environ.get("OLLAMA_HOST")) or DEFAULT_HOST
    parsed = urlparse(value if "://" in value else f"//{value}")
    return parsed.hostname or "127.0.0.1", parsed.port or 11434


def violation_log() -> Path:
    return Path(
        os.environ.get("MANUALLABOR_OFFLINE_LOG")
        or Path(tempfile.gettempdir()) / "offline-violations.log"
    )


def _norm(host: object) -> str:
    return str(host).strip("[]").lower()


def install_guard(allowed: set[tuple[str, int]] | None = None, log: Path | None = None) -> None:
    """Patch the socket module for this process. Idempotent."""
    if _installed:
        return
    if allowed is None:
        allowed = {ollama_endpoint()}
    allow = {(_norm(h), p) for h, p in allowed}
    loopback_ok = {p for h, p in allow if h in _LOOPBACK}
    log_path = log or violation_log()

    def permitted(host: object, port: object) -> bool:
        try:
            p = int(port)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return False
        h = _norm(host)
        return (h, p) in allow or (h in _LOOPBACK and p in loopback_ok)

    def violate(host: object, port: object) -> None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{host}:{port}\n")
        except OSError:
            pass
        raise OSError(f"offline guard: connection to {host}:{port} is blocked")

    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection

    def check_addr(addr: Any) -> None:
        if isinstance(addr, tuple) and len(addr) >= 2 and not permitted(addr[0], addr[1]):
            violate(addr[0], addr[1])

    def getaddrinfo(host: Any, port: Any, *a: Any, **k: Any) -> Any:
        # resolving a loopback name is not egress (a local server binds through here)
        if host is not None and _norm(host) not in _LOOPBACK and not permitted(host, port):
            violate(host, port)
        return real_getaddrinfo(host, port, *a, **k)

    def connect(self: socket.socket, addr: Any) -> Any:
        check_addr(addr)  # AF_UNIX addresses are str/bytes, not tuples: always allowed
        return real_connect(self, addr)

    def connect_ex(self: socket.socket, addr: Any) -> Any:
        check_addr(addr)
        return real_connect_ex(self, addr)

    def create_connection(address: Any, *a: Any, **k: Any) -> Any:
        check_addr(address)
        return real_create_connection(address, *a, **k)

    socket.getaddrinfo = getaddrinfo
    socket.socket.connect = connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign,assignment]
    socket.create_connection = create_connection
    _installed.append(True)


def install_from_env() -> bool:
    """Install the guard when MANUALLABOR_OFFLINE=1 (called first thing by the CLI and the job
    worker). Also tells the model libraries not to look for the network."""
    if os.environ.get("MANUALLABOR_OFFLINE") != "1":
        return False
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    install_guard()
    return True
