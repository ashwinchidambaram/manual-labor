"""Child process for T4: runs provider calls under a socket guard and reports violations."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

violations: list[str] = []
ALLOWED: tuple[str, int] | None = None


def _check(host: object, port: object) -> None:
    key = (str(host), int(port) if isinstance(port, int) or str(port).isdigit() else -1)
    if ALLOWED is None or key != ALLOWED:
        violations.append(f"{host}:{port}")
        raise OSError("offline guard")


def install_guard(allowed: tuple[str, int]) -> None:
    global ALLOWED
    ALLOWED = allowed
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection

    def getaddrinfo(host, port, *a, **k):  # type: ignore[no-untyped-def]
        _check(host, port)
        return real_getaddrinfo(host, port, *a, **k)

    def connect(self, addr):  # type: ignore[no-untyped-def]
        if isinstance(addr, tuple):
            _check(addr[0], addr[1])
        return real_connect(self, addr)

    def connect_ex(self, addr):  # type: ignore[no-untyped-def]
        if isinstance(addr, tuple):
            _check(addr[0], addr[1])
        return real_connect_ex(self, addr)

    def create_connection(address, *a, **k):  # type: ignore[no-untyped-def]
        _check(address[0], address[1])
        return real_create_connection(address, *a, **k)

    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    socket.socket.connect = connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign,assignment]
    socket.create_connection = create_connection  # type: ignore[assignment]


def main() -> None:
    port = int(os.environ["MANUALLABOR_STUB_PORT"])
    negative = "--negative" in sys.argv
    install_guard(("127.0.0.1", port))

    from manuallabor.contracts import Message, ModelRef, ProjectConfig, Task, TaskModels
    from manuallabor.providers import ListSink, build_provider_set

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d4944415478da63640000000600020c0a2db40000000049454e44ae426082"
    )
    cache_dir = Path(tempfile.mkdtemp())
    sink = ListSink()
    calls = 0
    if negative:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-NEGATIVE"
        ref = ModelRef(provider="anthropic", model="claude-haiku-4-5")
        cfg = ProjectConfig(
            name="x",
            models=TaskModels(
                cleanup=ref,
                grouping=ref,
                vision=ref,
                embeddings=ModelRef(provider="mock", model="mock-1"),
                verifier=ref,
            ),
        )
        ps = build_provider_set(cfg, cache_dir=cache_dir, sink=sink)
        with contextlib.suppress(Exception):
            ps.get(Task.cleanup).chat(Task.cleanup, [Message(role="user", content="hi")])
    else:
        oll = ModelRef(provider="ollama", model="llama3.2:1b")
        cfg = ProjectConfig(
            name="x",
            models=TaskModels(
                cleanup=oll,
                grouping=ModelRef(provider="mock", model="mock-1"),
                vision=ModelRef(provider="ollama", model="moondream"),
                embeddings=ModelRef(provider="ollama", model="nomic-embed-text"),
                verifier=oll,
            ),
        )
        ps = build_provider_set(cfg, cache_dir=cache_dir, sink=sink)
        schema = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}
        ps.get(Task.cleanup).chat(Task.cleanup, [Message(role="user", content="hi")])
        ps.get(Task.cleanup).chat(
            Task.cleanup, [Message(role="user", content="json")], json_schema=schema
        )
        ps.get(Task.vision).vision(Task.vision, png, "describe")
        ps.get(Task.embeddings).embed(Task.embeddings, ["a", "b"])
        ps.get(Task.cleanup).chat(Task.cleanup, [Message(role="user", content="hi")])  # cache hit
        ps.get(Task.grouping).chat(Task.grouping, [Message(role="user", content="x")])
        calls = len(sink)
    print(json.dumps({"violations": violations, "calls": calls}))


if __name__ == "__main__":
    main()
