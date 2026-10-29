"""agent/outcomes.json: the latest non-proposal outcome per flag (machine output, file only).

It is derived from job events, never read by a stage, and rewritten with canonical bytes so two
runs over the same inputs produce the same file."""

from __future__ import annotations

import json
from typing import Any

from manuallabor.contracts.io import dump_json
from manuallabor.project import ProjectPaths
from manuallabor.state.projections import write_if_differs

__all__ = ["project_outcomes_file"]


def project_outcomes_file(
    paths: ProjectPaths, change: dict[str, dict[str, Any] | None]
) -> dict[str, dict[str, Any]]:
    """Apply `change` (flag id -> entry, or None to drop it) and return the file's content."""
    cur: dict[str, dict[str, Any]] = {}
    if paths.agent_outcomes.is_file():
        try:
            cur = json.loads(paths.agent_outcomes.read_text(encoding="utf-8"))
        except ValueError:
            cur = {}
    new = dict(cur)
    for fid, entry in change.items():
        if entry is None:
            new.pop(fid, None)
        else:
            new[fid] = entry
    if new != cur:
        write_if_differs(paths.agent_outcomes, dump_json(dict(sorted(new.items()))))
    return new
