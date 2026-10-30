"""Assemble and export as resumable, fingerprinted steps (design 11 section 6)."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from manuallabor.contracts.enums import FlagStatus
from manuallabor.contracts.io import canonical_json, read_json, write_json
from manuallabor.contracts.manifest import Manifest, Override
from manuallabor.export.assemble import assemble, truncate_clock
from manuallabor.export.gate import Gate, export_gate
from manuallabor.export.load import doc_ready, load_inputs
from manuallabor.export.types import (
    BLOCKER_LIMIT,
    EXPORT_ALGO_VERSION,
    MAX_ARTICLE_BYTES,
    Assembled,
    ExportError,
    GateLocked,
)
from manuallabor.export.validate import validate_zip
from manuallabor.export.zip import tree_files, write_tree, write_zip
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import utc_now
from manuallabor.state.data import ProjectData
from manuallabor.state.errors import InvalidOp
from manuallabor.state.models import (
    ActionKind,
    ExportFlagBlocker,
    ExportReviewSummary,
    ExportScopeCounts,
    ExportStatus,
    ExportSummary,
    NodeState,
)
from manuallabor.state.review import ReviewService, load_review_blocks
from manuallabor.state.store import Store

__all__ = [
    "EXPORT_RUN_EVENT",
    "ExportState",
    "export_cutoff",
    "export_status",
    "fingerprint",
    "node_states",
    "read_state",
    "record_export_run",
    "record_override",
    "resolve_clock",
    "run_assemble",
    "run_export",
    "summarize",
]

Emit = Callable[[dict[str, Any]], None]


class _Rec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssembleRecord(_Rec):
    fingerprint: str  # everything but the clock and the overrides
    override_ids: list[int] = []  # the export_override actions that were active at assemble
    # the exported blocks by bucket (design 11 section 14); None in a record written before it,
    # which is then rebuilt rather than skipped
    review: ExportReviewSummary | None = None


class ExportRecord(_Rec):
    fingerprint: str  # sha256 over the staging tree
    zip_path: str
    summary: ExportSummary


class ExportState(_Rec):
    """export/state.json: what the last assemble and export were built from. A cache for
    skipping work and for the Export screen only: the override cutoff (P3) is never read from
    here, it is the last `export_run` action in the store (`export_cutoff`)."""

    assemble: AssembleRecord | None = None
    export: ExportRecord | None = None


EXPORT_RUN_EVENT = "export_run"  # the worker's log event the supervisor turns into the action


def export_cutoff(store: Store) -> int:
    """P3: overrides count only when their action id is greater than this, the id of the last
    successful export (`export_run` action) in the action log; 0 before the first export."""
    runs = store.actions_of((ActionKind.export_run,))
    return runs[-1].id if runs else 0


def record_export_run(store: Store, payload: dict[str, Any], *, request_id: str | None) -> int:
    """Append the `export_run` action (inside its own transaction); idempotent per
    `request_id`, so a supervisor that re-reads a worker log records it once."""
    prev = store.action_by_request(request_id, (ActionKind.export_run,))
    if prev is not None:
        return prev.id
    with store.tx():
        return store.append_action(
            ActionKind.export_run, "export", payload=payload, request_id=request_id
        )


def read_state(paths: ProjectPaths) -> ExportState:
    if not paths.export_state.is_file():
        return ExportState()
    try:
        return read_json(paths.export_state, ExportState)
    except ValueError:
        return ExportState()


def _write_state(paths: ProjectPaths, st: ExportState) -> None:
    write_json(paths.export_state, st)


def resolve_clock(now: str | None = None) -> datetime:
    """The injected clock: `--now`, else $MANUALLABOR_NOW, else the wall clock."""
    from manuallabor.contracts._base import _parse_utc

    raw = now or os.environ.get("MANUALLABOR_NOW")
    if raw:
        v = _parse_utc(raw)
        if not isinstance(v, datetime):
            raise ExportError(f"not a UTC timestamp: {raw!r}")
        return truncate_clock(v)
    return truncate_clock(utc_now())


# -- freshness ---------------------------------------------------------------------------------


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


def _check_fresh(paths: ProjectPaths) -> None:
    from manuallabor.jobs import graph

    cfg = paths.load_config()
    slugs = paths.list_slugs()
    if not slugs:
        raise ExportError("stale: the project has no documents")
    for slug in slugs:
        for st in graph.doc_node_states(paths, slug, cfg):
            if st.state != "fresh":
                why = f" ({st.reason})" if st.reason else ""
                raise ExportError(f"stale: {slug}:{st.node} is {st.state}{why}")
        if not doc_ready(paths, slug):
            raise ExportError(f"stale: {slug}: not processed to score2")


def fingerprint(paths: ProjectPaths, store: Store) -> str:
    """Everything an assemble depends on except the clock (a new clock is a skip) and the
    overrides, which `_assemble_fresh` compares separately so that the export that spends
    them does not make its own output stale."""
    from manuallabor.export.load import last_models

    cfg = paths.load_config()
    docs: dict[str, Any] = {}
    for slug in paths.list_slugs():
        dp = paths.doc(slug)
        figs = {
            p.name: _sha_file(p) for p in sorted(paths.figure_dir(slug).glob("*")) if p.is_file()
        }
        decs = store.decisions(doc_id=slug)
        docs[slug] = {
            "files": {
                f.name: _sha_file(f)
                for f in (
                    dp.document,
                    dp.blocks,
                    dp.scores,
                    dp.clean,
                    dp.attach,
                    dp.groups,
                    dp.figure_report,
                )
            },  # fmt: skip
            "figures": figs,
            "decisions": decs[-1].decision.seq if decs else 0,
            "n_decisions": len(decs),
        }
    payload = {
        "algo": EXPORT_ALGO_VERSION,
        "docs": docs,
        "figures_index": _sha_file(paths.figures_index),
        "selection": store.get_selection_json() or "",
        "open_flags": sorted(f.id for f in store.flags() if f.status.value == "open"),
        "models": last_models(paths),
        "config": {
            "name": cfg.name,
            "threshold": cfg.threshold,
            "split": cfg.article_split.value,
            "learning": cfg.learning.enabled,
            "models": cfg.models.model_dump(mode="json"),
        },
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _active_ids(store: Store, cutoff: int) -> list[int]:
    from manuallabor.export.load import active_overrides

    return [o.action_id for o in active_overrides(store, cutoff)]


def _assemble_fresh(rec: AssembleRecord, fp: str, active: list[int], cutoff: int) -> bool:
    """The staging tree is current when its inputs are unchanged and no override was added
    since it was built; overrides it used that an export has since spent do not count."""
    return rec.fingerprint == fp and [i for i in rec.override_ids if i > cutoff] == active


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for name, p in sorted(tree_files(root).items()):
        h.update(name.encode("utf-8") + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


# -- the gate and the status -------------------------------------------------------------------


def _gate(
    paths: ProjectPaths, store: Store, cutoff: int, review: ReviewService | None = None
) -> Gate:
    from manuallabor.export.load import active_overrides

    if review is None:
        review = ReviewService(paths, store, ProjectData(paths, store))
    data = review.data
    selected = set(data.selection().block_ids)
    blocks = {}
    scope = {}
    for slug in paths.list_slugs():
        if doc_ready(paths, slug) and data.scored(slug):
            blocks[slug] = review.review_blocks(slug)
            scope[slug] = data.scope_ids(slug, selected)
    return export_gate(blocks, scope, store.flags(), active_overrides(store, cutoff))


def _gate_signature(paths: ProjectPaths, review: ReviewService) -> tuple[Any, ...] | None:
    """Everything the gate reads: per document the files of the machine view, its groups
    (selection) and attachments (figure scope), and the action log, which every decision, flag,
    selection change, override and export run appends to. None inside a transaction."""
    files: list[Path] = []
    slugs = paths.list_slugs()
    for slug in slugs:
        dp = paths.doc(slug)
        files += [dp.blocks, dp.scores, dp.clean, dp.groups, dp.attach]
    sg = review.data.db_signature(*files)
    return None if sg is None else (tuple(slugs), *sg)


def _status_parts(
    paths: ProjectPaths, store: Store, review: ReviewService
) -> tuple[Gate, list[Override]]:
    from manuallabor.export.load import active_overrides

    cutoff = export_cutoff(store)
    g = _gate(paths, store, cutoff, review)
    overrides = [
        Override(target_id=o.target_id, flag_id=o.flag_id, reason=o.reason, at=o.ts)
        for o in active_overrides(store, cutoff)
    ]
    return g, overrides


def export_status(
    paths: ProjectPaths, store: Store, review: ReviewService | None = None
) -> ExportStatus:
    """The Export screen's gate. The API passes its `ReviewService`: the gate and overrides are
    then cached on `_gate_signature`, so a poll with nothing changed costs a few stats and one
    `MAX(id)` (review F4); the CLI builds a throwaway service."""
    if review is None:
        review = ReviewService(paths, store, ProjectData(paths, store))
    sg = _gate_signature(paths, review)
    g: Gate
    overrides: list[Override]
    if sg is None:
        g, overrides = _status_parts(paths, store, review)
    else:
        g, overrides = review.data.memo(
            "export_gate", "", sg, lambda: _status_parts(paths, store, review)
        )
    st = read_state(paths)
    zip_path = None
    summary = None
    if st.export is not None and Path(st.export.zip_path).is_file():
        zip_path, summary = st.export.zip_path, st.export.summary
    return ExportStatus(
        unlocked=g.unlocked,
        open_flags=g.open_flags,
        overrides=list(overrides),
        queued=g.queued,
        blockers=g.blockers[:BLOCKER_LIMIT],
        flag_blockers=[
            ExportFlagBlocker(flag_id=f.id, block_id=b, category=f.category, note=f.note)
            for f, b in g.flag_blockers
        ],
        counts=ExportScopeCounts(**g.counts),
        summary=summary,
        zip_path=zip_path,
    )


def record_override(
    paths: ProjectPaths,
    store: Store,
    reason: str,
    *,
    target_id: str | None = None,
    flag_id: str | None = None,
    request_id: str | None = None,
) -> int:
    """Append an `export_override` action (idempotent per `request_id`); returns its id."""
    if not reason.strip():
        raise InvalidOp("an override needs a reason")
    prev = store.action_by_request(request_id)
    if prev is not None:
        return prev.id
    if target_id is not None:
        block_of: dict[str, str] = {}  # block or figure id -> block id
        for slug in paths.list_slugs():
            if doc_ready(paths, slug):
                for b in load_review_blocks(paths, store, slug):
                    block_of[b.id] = b.id
                    if b.figure_id is not None:
                        block_of[str(b.figure_id)] = b.id
        if target_id not in block_of:
            raise InvalidOp(f"unknown block or figure: {target_id}")
        if flag_id is None:
            # design 11 section 14: a block override never covers a flag, so recording one on a
            # flagged block would look like a decision about the flag and change nothing
            fig_of = {v: k for k, v in block_of.items() if k != v}
            mine = {block_of[target_id], fig_of.get(block_of[target_id])}
            open_ids = sorted(
                f.id for f in store.flags() if f.status == FlagStatus.open and f.target_id in mine
            )
            if open_ids:
                raise InvalidOp(
                    f"{target_id} has an open flag ({', '.join(open_ids)}): a block override "
                    "does not cover a flag; resolve the flag, or override it by its flag id"
                )
    if flag_id is not None and store.get_flag(flag_id) is None:
        raise InvalidOp(f"unknown flag: {flag_id}")
    with store.tx():
        return store.append_action(
            ActionKind.export_override,
            "export",
            target_id=target_id,
            payload={"reason": reason, "target_id": target_id, "flag_id": flag_id},
            request_id=request_id,
        )


# -- assemble ----------------------------------------------------------------------------------


def _open_readonly(paths: ProjectPaths) -> Store:
    if not paths.db.is_file():
        raise ExportError("no project.db: open the project and select what to export first")
    return Store.open(paths, readonly=True)


def _verify_files(asm: Assembled) -> None:
    """A figure file that is missing or does not decode is an error, never skipped."""
    from PIL import Image

    for f in asm.figures:
        for p in (f.png, f.svg):
            if p is None:
                continue
            if not p.is_file():
                raise ExportError(f"{f.id}: image file {p} is missing")
            if p.suffix == ".png":
                try:
                    with Image.open(io.BytesIO(p.read_bytes())) as im:
                        im.verify()
                except Exception as exc:
                    raise ExportError(f"{f.id}: {p.name} does not decode: {exc}") from exc


def run_assemble(
    paths: ProjectPaths,
    store: Store | None = None,
    *,
    clock: datetime | None = None,
    emit: Emit = lambda _o: None,
    force: bool = False,
) -> str:
    """Build the staging tree `export/assembled/`. Returns "built" or "skip"."""
    _check_fresh(paths)
    st = store if store is not None else _open_readonly(paths)
    try:
        state = read_state(paths)
        cutoff = export_cutoff(st)
        # the gate first, also before a skip: a spent override never re-covers anything
        gate = _gate(paths, st, cutoff)
        if not gate.allowed:
            raise GateLocked(gate.open_flags, gate.queued, gate.blockers)
        fp = fingerprint(paths, st)
        active = _active_ids(st, cutoff)
        staged = paths.assembled / "manifest.json"
        if (
            not force
            and state.assemble is not None
            and state.assemble.review is not None
            and _assemble_fresh(state.assemble, fp, active, cutoff)
            and staged.is_file()
        ):
            emit({"stage": "assemble", "status": "skip", "doc": ""})
            return "skip"
        inputs = load_inputs(paths, st, cutoff)
        asm = assemble(inputs, clock if clock is not None else resolve_clock())
        _verify_files(asm)
        tmp = paths.export_dir / ".assembled.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        write_tree(asm.files, tmp)
        shutil.rmtree(paths.assembled, ignore_errors=True)
        os.replace(tmp, paths.assembled)
        state = read_state(paths)
        state.assemble = AssembleRecord(fingerprint=fp, override_ids=active, review=asm.review)
        _write_state(paths, state)
        emit(
            {
                "stage": "assemble",
                "status": "built",
                "doc": "",
                "articles": len(asm.articles),
                "figures": len(asm.figures),
            }
        )
        return "built"
    finally:
        if store is None:
            st.close()


def summarize(
    root: Path, zip_bytes: int, zip_sha256: str, review: ExportReviewSummary
) -> ExportSummary:
    """The Export-screen summary: the counts of a staging tree (so a resumed export gets the
    same one) and its exported-block buckets, recorded when the tree was assembled."""
    m = read_json(root / "manifest.json", Manifest)
    warnings = []
    for a in m.articles:
        n = (root / a.path).stat().st_size
        if n > MAX_ARTICLE_BYTES:
            warnings.append(f"article {a.id} is {n} bytes (over {MAX_ARTICLE_BYTES})")
    return ExportSummary(
        articles=len(m.articles),
        figures=len(m.figures),
        pages_covered=len({(a.source_doc, p) for a in m.articles for p in a.pages}),
        docs=len(m.docs),
        review=review,
        warnings=warnings,
        zip_bytes=zip_bytes,
        zip_sha256=zip_sha256,
        generated_at=m.project.generated_at,
    )


def run_export(
    paths: ProjectPaths,
    store: Store | None = None,
    *,
    clock: datetime | None = None,
    emit: Emit = lambda _o: None,
    force: bool = False,
    out: Path | None = None,
) -> ExportRecord:
    """Assemble (if needed), zip the staging tree, validate the zip and record the export. A
    zip that does not validate is left as `<zip>.rejected` and raises ExportError."""
    run_assemble(paths, store, clock=clock, emit=emit, force=force)
    state = read_state(paths)
    assert state.assemble is not None and state.assemble.review is not None
    tree_fp = _tree_hash(paths.assembled)
    dest = Path(out) if out is not None else paths.zip_path
    cand = dest.with_name(dest.name + ".candidate")
    for stray in (cand, cand.with_name(cand.name + ".tmp"), dest.with_name(dest.name + ".tmp")):
        stray.unlink(missing_ok=True)
    prev = state.export
    if (
        not force
        and prev is not None
        and prev.fingerprint == tree_fp
        and prev.zip_path == str(dest)
        and dest.is_file()
    ):
        emit(
            {"stage": "export", "status": "skip", "doc": "", "zip_sha256": prev.summary.zip_sha256}
        )
        return prev
    write_zip(tree_files(paths.assembled), cand)
    problems = validate_zip(cand)
    if problems:
        rejected = dest.with_name(dest.name + ".rejected")
        os.replace(cand, rejected)
        shown = "; ".join(str(p) for p in problems[:5])
        raise ExportError(f"the export zip does not validate ({len(problems)}): {shown}")
    os.replace(cand, dest)
    data = dest.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    rec = ExportRecord(
        fingerprint=tree_fp,
        zip_path=str(dest),
        summary=summarize(paths.assembled, len(data), sha, state.assemble.review),
    )
    state.export = rec
    _write_state(paths, state)
    dest.with_name(dest.name + ".rejected").unlink(missing_ok=True)
    run_payload: dict[str, Any] = {
        "zip_sha256": sha,
        "articles": rec.summary.articles,
        "figures": rec.summary.figures,
        "overrides": rec.summary.review.overrides,
    }
    if store is not None and store.writer:
        record_export_run(store, run_payload, request_id=None)
    else:
        # no DB writer here (a job worker): the supervisor, the single writer, records the
        # action from this log event (idempotent per job), which moves the override cutoff
        emit({"event": EXPORT_RUN_EVENT, "doc": "", "payload": run_payload})
    emit(
        {
            "stage": "export",
            "status": "built",
            "doc": "",
            "articles": rec.summary.articles,
            "figures": rec.summary.figures,
            "zip_sha256": sha,
        }
    )
    return rec


def node_states(paths: ProjectPaths, store: Store | None = None) -> list[NodeState]:
    """State of the two project-level nodes (`assemble`, `export`)."""
    state = read_state(paths)
    out: list[NodeState] = []
    try:
        _check_fresh(paths)
    except ExportError as exc:
        why = str(exc)
        return [NodeState(node="assemble", state="stale", reason=why),
                NodeState(node="export", state="stale", reason=why)]  # fmt: skip
    own = store is None
    st = store if store is not None else (_open_readonly(paths) if paths.db.is_file() else None)
    try:
        if state.assemble is None or not (paths.assembled / "manifest.json").is_file():
            out.append(NodeState(node="assemble", state="missing"))
        elif st is None:
            out.append(NodeState(node="assemble", state="stale", reason="no project.db"))
        else:
            cutoff = export_cutoff(st)
            fresh = _assemble_fresh(
                state.assemble, fingerprint(paths, st), _active_ids(st, cutoff), cutoff
            )
            out.append(
                NodeState(node="assemble", state="fresh")
                if fresh
                else NodeState(node="assemble", state="stale", reason="inputs changed")
            )
    finally:
        if own and st is not None:
            st.close()
    if state.export is None or not Path(state.export.zip_path).is_file():
        out.append(NodeState(node="export", state="missing"))
    elif out[0].state != "fresh":
        out.append(NodeState(node="export", state="stale", reason="assemble is not fresh"))
    elif _tree_hash(paths.assembled) != state.export.fingerprint:
        out.append(NodeState(node="export", state="stale", reason="staging tree changed"))
    else:
        out.append(NodeState(node="export", state="fresh"))
    return out
