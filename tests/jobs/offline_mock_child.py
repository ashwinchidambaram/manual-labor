"""Child of test_g9: builds mock-mode providers for an all-ollama config under a socket guard
that records (and refuses) every connection attempt, then exercises every task."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

violations: list[str] = []


def _deny(*args: object, **kwargs: object) -> None:
    violations.append(repr(args[:2]))
    raise OSError("offline guard")


def main(root: str) -> None:
    socket.getaddrinfo = _deny  # type: ignore[assignment]
    socket.socket.connect = _deny  # type: ignore[method-assign,assignment]
    socket.create_connection = _deny  # type: ignore[assignment]

    from manuallabor.contracts.config import ProjectConfig
    from manuallabor.contracts.enums import Task
    from manuallabor.contracts.io import read_json
    from manuallabor.contracts.llm import Message
    from manuallabor.jobs.providers import MOCK_ONLY_FACTORIES, provider_set_factory
    from manuallabor.project import ProjectPaths
    from manuallabor.providers import MockProvider, build_provider_set
    from manuallabor.providers.base import ProviderError
    from manuallabor.providers.sinks import ListSink

    paths = ProjectPaths(Path(root))
    cfg = read_json(paths.config, ProjectConfig)
    assert all(
        getattr(cfg.models, t).provider == "ollama"
        for t in ("cleanup", "grouping", "vision", "embeddings")
    )
    sink = ListSink()
    ps = provider_set_factory(paths, cfg, "mock", sink)()
    assert ps.by_task and all(isinstance(p, MockProvider) for p in ps.by_task.values())
    ps.get(Task.cleanup).chat(Task.cleanup, [Message(role="user", content="<raw>x</raw>")])
    ps.get(Task.embeddings).embed(Task.embeddings, ["a", "b"])
    refused = False
    try:
        build_provider_set(cfg, cache_dir=None, sink=sink, factories=MOCK_ONLY_FACTORIES)
    except ProviderError:
        refused = True
    print(json.dumps({"violations": violations, "refused": refused, "calls": len(sink)}))


if __name__ == "__main__":
    main(sys.argv[1])
