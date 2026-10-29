"""Agent-layer errors; the API maps `AgentConflict` to HTTP 409 with its code."""

from __future__ import annotations


class AgentConflict(Exception):
    """A precondition of an agent action failed (HTTP 409). `code` is stable and documented:
    `no_open_flags`, `not_pending`, `stale_proposal`, `checks_failed`."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
