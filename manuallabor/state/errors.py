"""Exceptions of the state layer. B maps them to HTTP: NotFound 404, OutOfScope 422,
EditConflictError 409, LockHeld 409, InvalidOp 422."""

from __future__ import annotations

from typing import Any

from manuallabor.state.models import EditConflict


class StateError(Exception):
    """project.db cannot be used (newer schema, corruption)."""


class NotFound(KeyError):
    pass


class OutOfScope(ValueError):
    """The block is not in review scope (not selected and not an attached figure)."""


class InvalidOp(ValueError):
    pass


class EditConflictError(Exception):
    def __init__(self, conflict: EditConflict) -> None:
        super().__init__("edit changes content; confirm_content_change=true to store it")
        self.conflict = conflict


class LockHeld(Exception):
    def __init__(self, owner: dict[str, Any]) -> None:
        super().__init__(f"project is locked by pid {owner.get('pid')} ({owner.get('cmd')})")
        self.owner = owner


class NoPageRender(Exception):
    """DOCX documents have no page render."""
