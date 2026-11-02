"""Removing a manual (design 07 section 22).

The log is append-only: decisions, flags, proposals and overrides on the manual's blocks are
kept and become orphaned (no document of that slug exists to read them). Everything derived
from the file is deleted, the selection loses the manual's blocks and its `known_docs` entry,
and a `remove_source` action records it. One service behind `DELETE /api/sources/{slug}` and
`labor remove`."""

from __future__ import annotations

import json
import secrets
import shutil
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Any

from manuallabor import ids
from manuallabor.agent.data import target_slug
from manuallabor.contracts.enums import FlagStatus
from manuallabor.contracts.selection import Selection
from manuallabor.project import ProjectPaths
from manuallabor.state import projections
from manuallabor.state import selection_log as sel_log
from manuallabor.state.errors import Conflict, LockHeld, NotFound
from manuallabor.state.lock import ProjectLock
from manuallabor.state.models import ActionKind, RemovedDoc, SourceRemoval
from manuallabor.state.store import Store

__all__ = ["removal", "remove_source", "removed_docs"]

RUNNING = "A job is running. Remove the manual when it has finished."
QUEUED = "A job waiting to run will read this manual. Remove it when that job has finished."
LOCKED = "Another process is working on this project. Remove the manual when it has finished."


def _covers(plan: dict[str, Any], slug: str) -> bool:
    docs = plan.get("docs")
    return not docs or slug in docs


def _blocked_by(store: Store, slug: str) -> str | None:
    """Why a removal cannot be done now: any running job (a worker writes project-wide files,
    such as the figure index and the selection projection, whatever its documents), or a queued
    job that will read this manual."""
    for row in store.job_rows({"running", "queued"}):
        if row["status"] == "running":
            return RUNNING
        if _covers(json.loads(row["plan"]), slug):
            return QUEUED
    return None


def _flags_of(store: Store, slug: str) -> list[Any]:
    out = []
    for f in store.flags():
        try:
            if target_slug(f.target_id) == slug:
                out.append(f)
        except ValueError:
            continue
    return out


def _selection(paths: ProjectPaths, store: Store) -> Selection:
    from manuallabor.state.data import ProjectData

    return ProjectData(paths, store).selection()


def removal(paths: ProjectPaths, store: Store, slug: str) -> SourceRemoval:
    """The preview: what removing `slug` deletes and orphans, and why it cannot be done now."""
    if slug not in paths.list_slugs():
        raise NotFound(slug)
    doc = paths.load_document(slug)
    flags = _flags_of(store, slug)
    flag_ids = {f.id for f in flags}
    return SourceRemoval(
        doc_id=slug,
        filename=doc.filename,
        blocks=len(doc.block_ids),
        selected_blocks=sum(
            1 for b in _selection(paths, store).block_ids if ids.parse_block_id(b)[0] == slug
        ),
        decisions=len(store.decisions(doc_id=slug)),
        flags=len(flags),
        open_flags=sum(1 for f in flags if f.status == FlagStatus.open),
        proposals=sum(1 for p in store.proposals() if p.flag_id in flag_ids),
        blocked_by=_blocked_by(store, slug),
    )


@contextmanager
def _worker_lock(paths: ProjectPaths, slug: str) -> Iterator[None]:
    lock = ProjectLock(paths.worker_lock, cmd=f"remove {slug}")
    try:
        lock.acquire(nonblocking=True)
    except LockHeld as exc:
        raise Conflict("job_active", LOCKED) from exc
    try:
        yield
    finally:
        lock.release()


def remove_source(
    paths: ProjectPaths,
    store: Store,
    slug: str,
    request_id: str,
    *,
    screen: str = "scope",
    hold: Callable[[], AbstractContextManager[Any]] | None = None,
) -> SourceRemoval:
    """Remove `slug` (design 07 section 22). `hold` keeps the job runner from starting a job
    meanwhile (the serve process passes its runner's; the CLI holds the project lock). Raises
    NotFound for an unknown manual and Conflict while a job could touch it. Idempotent per
    `request_id`: a replay returns the first answer."""
    with hold() if hold is not None else nullcontext():
        prev = store.action_by_request(request_id, (ActionKind.remove_source,))
        if prev is not None:
            return SourceRemoval.model_validate(prev.payload["_outcome"])
        preview = removal(paths, store, slug)
        if preview.blocked_by is not None:
            raise Conflict("job_active", preview.blocked_by)
        with _worker_lock(paths, slug):
            return _remove(paths, store, slug, request_id, screen, preview)


def _remove(
    paths: ProjectPaths,
    store: Store,
    slug: str,
    request_id: str,
    screen: str,
    preview: SourceRemoval,
) -> SourceRemoval:
    doc = paths.load_document(slug)
    out = preview.model_copy(update={"removed": True, "blocked_by": None})
    # 1. the log and the selection, one transaction
    with store.tx():
        stored = (
            Selection.model_validate_json(body) if (body := store.get_selection_json()) else None
        )
        new = None
        if stored is not None:
            new = Selection.model_validate(
                {
                    **stored.model_dump(mode="json"),
                    "block_ids": [b for b in stored.block_ids if ids.parse_block_id(b)[0] != slug],
                    "known_docs": None
                    if stored.known_docs is None
                    else [d for d in stored.known_docs if d != slug],
                }
            )
        aid = store.next_action_id()
        store.append_action(
            ActionKind.remove_source,
            screen,
            doc_id=slug,
            payload={
                "filename": doc.filename,
                "sha256": doc.sha256,
                "delta": sel_log.selection_delta(stored, new) if new is not None else None,
                "_outcome": out.model_dump(mode="json"),
            },
            request_id=request_id,
            action_id=aid,
        )
        if new is not None:
            store.set_selection_json(json.dumps(new.model_dump(mode="json"), sort_keys=True), aid)
            store.after_commit(lambda: projections.project_selection(store, paths))
        _drop_job_rows(paths, store, slug, doc.filename)
    # 2. the files: the document's directory leaves list_slugs at once (an atomic rename),
    # then everything derived from it, the figure index, and last the source file
    _purge_leftovers(paths)
    dp = paths.doc(slug)
    if dp.root.is_dir():
        gone = paths.docs / f".removed-{slug}-{secrets.token_hex(4)}"
        dp.root.rename(gone)
        shutil.rmtree(gone, ignore_errors=True)
    shutil.rmtree(paths.figure_dir(slug), ignore_errors=True)
    from manuallabor.figures.pipeline import rebuild_index

    rebuild_index(paths, set(), lambda _o: None)
    paths.source(doc.filename).unlink(missing_ok=True)
    return out


def _purge_leftovers(paths: ProjectPaths) -> None:
    """`.removed-*` directories a crash left behind (list_slugs never lists them)."""
    if paths.docs.is_dir():
        for p in paths.docs.iterdir():
            if p.is_dir() and p.name.startswith(".removed-"):
                shutil.rmtree(p, ignore_errors=True)


def _drop_job_rows(paths: ProjectPaths, store: Store, slug: str, filename: str) -> None:
    """Finished job rows whose plan names only this manual, and their logs. A project-wide row
    is history of the other manuals too and stays."""
    drop: list[str] = []
    for row in store.job_rows():
        if row["status"] in ("queued", "running", "merged"):
            continue
        plan = json.loads(row["plan"])
        job_id = f"job-{row['n']:06d}"
        docs = plan.get("docs")
        only_mine = bool(docs) and set(docs) == {slug}
        if row["kind"] == "ingest_run":
            try:
                spec = json.loads(paths.job_plan(job_id).read_text(encoding="utf-8"))
                files = [str(f).rsplit("/", 1)[-1] for f in spec.get("files", [])]
            except (OSError, ValueError):
                files = []
            only_mine = files == [filename]
        if only_mine:
            drop.append(job_id)
    if not drop:
        return
    store.delete_jobs(drop)
    for job_id in drop:
        for p in (paths.job_log(job_id), paths.job_plan(job_id)):
            p.unlink(missing_ok=True)
        paths.job_log(job_id).with_suffix(".stderr").unlink(missing_ok=True)


def removed_docs(paths: ProjectPaths, store: Store) -> list[RemovedDoc]:
    """Manuals removed by a `remove_source` action and not present now, with their orphaned
    decisions and open flags counted live (an added-again manual is no longer listed)."""
    live = set(paths.list_slugs())
    seen: dict[str, str] = {}
    for a in store.actions_of((ActionKind.remove_source,)):
        if a.doc_id and a.doc_id not in live:
            seen[a.doc_id] = str(a.payload.get("filename", a.doc_id))
    if not seen:
        return []
    open_by: dict[str, int] = {}
    for f in store.flags(FlagStatus.open):
        try:
            s = target_slug(f.target_id)
        except ValueError:
            continue
        open_by[s] = open_by.get(s, 0) + 1
    return [
        RemovedDoc(
            doc_id=slug,
            filename=name,
            orphaned_decisions=len(store.decisions(doc_id=slug)),
            open_flags=open_by.get(slug, 0),
        )
        for slug, name in sorted(seen.items())
    ]
