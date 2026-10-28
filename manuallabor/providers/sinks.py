"""Log sinks for LLM call records."""

from __future__ import annotations

import json
from pathlib import Path

from manuallabor.contracts.llm import LLMCallLog


class ListSink(list[LLMCallLog]):
    """A list that is also a LogSink: calling it appends the record."""

    def __call__(self, log: LLMCallLog) -> None:
        self.append(log)


class JsonlSink:
    """Appends one compact, sorted-keys JSON line per call, flushing per call."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def __call__(self, log: LLMCallLog) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            log.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
            f.flush()
