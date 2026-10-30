"""DB -> file projections (design 07 section 2.4) and `reconcile`.

The DB is the truth; the files are what stages read. A projection is written after COMMIT;
`reconcile` runs at every writer `Store.open` and rewrites any file whose bytes differ, so a
crash between commit and file write heals on the next open."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from manuallabor.cleanup.types import AttachOverride
from manuallabor.contracts.group import GroupOverride
from manuallabor.contracts.io import PART_SUFFIX, dump_json, write_text_atomic
from manuallabor.contracts.selection import Selection
from manuallabor.project import ProjectPaths
from manuallabor.state.models import ActionKind

if TYPE_CHECKING:
    from manuallabor.state.store import Store

__all__ = [
    "project_all",
    "project_figure_overrides",
    "project_overrides",
    "project_proposals",
    "project_selection",
    "reconcile",
    "write_if_differs",
]


def write_if_differs(path: Path, text: str) -> bool:
    """Projections are written by the serve process outside the worker lock, so they use a
    `.part` temp file the job's start-up cleaner never matches (design 07 section 14.1)."""
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    write_text_atomic(path, text, suffix=PART_SUFFIX)
    return True


def project_selection(store: Store, paths: ProjectPaths) -> bool:
    body = store.get_selection_json()
    if body is None:
        return False
    return write_if_differs(paths.selection, dump_json(Selection.model_validate_json(body)))


def _override_docs(store: Store, table: str) -> list[str]:
    return sorted({d for _, d, _ in store.overrides(table)})


def project_overrides(store: Store, paths: ProjectPaths) -> int:
    n = 0
    for doc in _override_docs(store, "group_overrides"):
        rows = [
            GroupOverride.model_validate_json(b)
            for _, _, b in store.overrides("group_overrides", doc)
        ]
        n += write_if_differs(paths.doc(doc).group_overrides, dump_json(rows))
    for doc in _override_docs(store, "attach_overrides"):
        arows = [
            AttachOverride.model_validate_json(b)
            for _, _, b in store.overrides("attach_overrides", doc)
        ]
        n += write_if_differs(paths.doc(doc).attach_overrides, dump_json(arows))
    return n


def figure_override_rows(store: Store, doc: str) -> list[dict[str, object]]:
    """Latest bbox override per figure of the document, by figure id."""
    latest: dict[str, tuple[int, list[float]]] = {}
    for seq, _doc, fid, bbox in store.figure_overrides(doc):
        latest[fid] = (seq, bbox)
    return [
        {"seq": seq, "figure_id": fid, "bbox": bbox} for fid, (seq, bbox) in sorted(latest.items())
    ]


def project_figure_overrides(store: Store, paths: ProjectPaths) -> int:
    docs = sorted({d for _, d, _, _ in store.figure_overrides()})
    n = 0
    for doc in docs:
        text = json.dumps(figure_override_rows(store, doc), sort_keys=True, indent=2) + "\n"
        n += write_if_differs(paths.doc(doc).figure_overrides, text)
    return n


def project_proposals(store: Store, paths: ProjectPaths) -> bool:
    """agent/proposals.json: every proposal by id, canonical bytes (module 10). Not written
    while there are none, so a project that never ran the agent is unchanged."""
    rows = store.proposals()
    if not rows:
        return False
    body = dump_json([p.model_dump(mode="json") for p in rows])
    return write_if_differs(paths.agent_proposals, body)


def project_all(store: Store, paths: ProjectPaths) -> None:
    project_selection(store, paths)
    project_overrides(store, paths)
    project_figure_overrides(store, paths)
    project_proposals(store, paths)
    from manuallabor.state.learning import project_learning

    project_learning(store, paths)


def import_legacy(store: Store, paths: ProjectPaths) -> int:
    """A project built before module 7: file contents become `import` actions once."""
    n = 0
    sel_file = paths.selection
    todo_sel = store.get_selection_json() is None and sel_file.is_file()
    group_docs = [
        s
        for s in paths.list_slugs()
        if paths.doc(s).group_overrides.is_file() and not store.overrides("group_overrides", s)
    ]
    attach_docs = [
        s
        for s in paths.list_slugs()
        if paths.doc(s).attach_overrides.is_file() and not store.overrides("attach_overrides", s)
    ]
    if not (todo_sel or group_docs or attach_docs):
        return 0
    with store.tx():
        if todo_sel:
            sel = Selection.model_validate_json(sel_file.read_text(encoding="utf-8"))
            body = dump_json(sel)
            aid = store.append_action(
                ActionKind.import_, "cli", payload={"what": "selection"}, after=body
            )
            store.set_selection_json(json.dumps(sel.model_dump(mode="json"), sort_keys=True), aid)
            n += 1
        for doc in group_docs:
            raw = json.loads(paths.doc(doc).group_overrides.read_text(encoding="utf-8"))
            for row in sorted(
                TypeAdapter(list[GroupOverride]).validate_python(raw), key=lambda o: o.seq
            ):
                seq = store.next_override_seq("group_overrides")
                o = row.model_copy(update={"seq": seq})
                aid = store.append_action(
                    ActionKind.import_, "cli", doc_id=doc, payload={"what": "group_override"}
                )
                store.add_override(
                    "group_overrides",
                    seq,
                    doc,
                    json.dumps(o.model_dump(mode="json"), sort_keys=True),
                    aid,
                )
                n += 1
        for doc in attach_docs:
            raw = json.loads(paths.doc(doc).attach_overrides.read_text(encoding="utf-8"))
            for arow in sorted(
                TypeAdapter(list[AttachOverride]).validate_python(raw), key=lambda o: o.seq
            ):
                seq = store.next_override_seq("attach_overrides")
                ao = arow.model_copy(update={"seq": seq})
                aid = store.append_action(
                    ActionKind.import_, "cli", doc_id=doc, payload={"what": "attach_override"}
                )
                store.add_override(
                    "attach_overrides",
                    seq,
                    doc,
                    json.dumps(ao.model_dump(mode="json"), sort_keys=True),
                    aid,
                )
                n += 1
    return n


def reconcile(store: Store, paths: ProjectPaths) -> None:
    import_legacy(store, paths)
    project_all(store, paths)
