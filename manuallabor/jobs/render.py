"""Plain-text rendering of `labor status`."""

from __future__ import annotations

from manuallabor.jobs.graph import DOC_NODES
from manuallabor.state.models import ProjectStatus

__all__ = ["render_status"]

_MARK = {"fresh": "fresh", "stale": "STALE", "missing": "missing", "failed": "FAILED"}


def render_status(st: ProjectStatus, *, verbose: bool = False) -> str:
    cols = [n for n in DOC_NODES if n != "ingest"]
    width = max([len(d.doc_id) for d in st.docs] + [8])
    lines = [f"project: {st.project}"]
    lines.append(f"{'doc':<{width}}  " + "  ".join(f"{c:<8}" for c in cols))
    for d in st.docs:
        by = {n.node: n for n in d.nodes}
        lines.append(f"{d.doc_id:<{width}}  " + "  ".join(f"{_MARK[by[c].state]:<8}" for c in cols))
        lines.append(
            f"{'':<{width}}  learning: group={d.learning.group} clean={d.learning.clean}"
            + (f"  orphaned_decisions={d.orphaned_decisions}" if d.orphaned_decisions else "")
        )
        if verbose:
            for n in d.nodes:
                if n.state != "fresh" and n.reason:
                    lines.append(f"{'':<{width}}    {n.node}: {n.state} ({n.reason})")
    if st.unregistered_sources:
        lines.append("unregistered sources: " + ", ".join(st.unregistered_sources))
    for j in st.jobs_running:
        lines.append(f"job {j.id} {j.status} {j.units_done}/{j.units_total}")
    return "\n".join(lines) + "\n"
