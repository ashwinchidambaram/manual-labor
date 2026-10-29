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
    ExportReviewSummary,
    ExportStatus,
    ExportSummary,
    NodeState,
)
from manuallabor.state.review import load_review_blocks
from manuallabor.state.store import Store

__all__ = [
    "ExportState",
    "export_status",
    "fingerprint",
    "node_states",
    "read_state",
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
    fingerprint: str
    max_action_id: int  # the newest action the assemble saw; an export moves the cutoff here


class ExportRecord(_Rec):
    fingerprint: str  # sha256 over the staging tree
    zip_path: str
    summary: ExportSummary


class ExportState(_Rec):
    """export/state.json: what the last assemble and export were built from."""

    assemble: AssembleRecord | None = None
    export: ExportRecord | None = None
    after_action_id: int = 0  # overrides at or below this id belong to an earlier export


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


def fingerprint(paths: ProjectPaths, store: Store, after_action_id: int) -> str:
    """Everything an assemble depends on except the clock (a new clock is a skip)."""
    from manuallabor.export.load import active_overrides, last_models

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
        "overrides": [o.action_id for o in active_overrides(store, after_action_id)],
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


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for name, p in sorted(tree_files(root).items()):
        h.update(name.encode("utf-8") + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


# -- the gate and the status -------------------------------------------------------------------


def _gate(paths: ProjectPaths, store: Store, after_action_id: int) -> Gate:
    from manuallabor.export.load import active_overrides

    data = ProjectData(paths, store)
    selected = set(data.selection().block_ids)
    blocks = {}
    scope = {}
    for slug in paths.list_slugs():
        if doc_ready(paths, slug):
            blocks[slug] = load_review_blocks(paths, store, slug)
            scope[slug] = data.scope_ids(slug, selected)
    return export_gate(blocks, scope, store.flags(), active_overrides(store, after_action_id))


def export_status(paths: ProjectPaths, store: Store) -> ExportStatus:
    st = read_state(paths)
    g = _gate(paths, store, st.after_action_id)
    from manuallabor.export.load import active_overrides

    overrides = [
        Override(target_id=o.target_id, flag_id=o.flag_id, reason=o.reason, at=o.ts)
        for o in active_overrides(store, st.after_action_id)
    ]
    zip_path = None
    summary = None
    if st.export is not None and Path(st.export.zip_path).is_file():
        zip_path, summary = st.export.zip_path, st.export.summary
    return ExportStatus(
        unlocked=g.unlocked,
        open_flags=g.open_flags,
        overrides=overrides,
        queued=g.queued,
        blockers=g.blockers[:BLOCKER_LIMIT],
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
        known: set[str] = set()
        for slug in paths.list_slugs():
            if doc_ready(paths, slug):
                for b in load_review_blocks(paths, store, slug):
                    known.add(b.id)
                    if b.figure_id is not None:
                        known.add(str(b.figure_id))
        if target_id not in known:
            raise InvalidOp(f"unknown block or figure: {target_id}")
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
        cutoff = state.after_action_id
        fp = fingerprint(paths, st, cutoff)
        staged = paths.assembled / "manifest.json"
        if (
            not force
            and state.assemble is not None
            and state.assemble.fingerprint == fp
            and staged.is_file()
        ):
            emit({"stage": "assemble", "status": "skip", "doc": ""})
            return "skip"
        max_action = st.max_action_id()
        inputs = load_inputs(paths, st, cutoff)
        gate = _gate(paths, st, cutoff)
        if not gate.allowed:
            raise GateLocked(gate.open_flags, gate.queued, gate.blockers)
        asm = assemble(inputs, clock if clock is not None else resolve_clock())
        _verify_files(asm)
        tmp = paths.export_dir / ".assembled.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        write_tree(asm.files, tmp)
        shutil.rmtree(paths.assembled, ignore_errors=True)
        os.replace(tmp, paths.assembled)
        state = read_state(paths)
        state.assemble = AssembleRecord(fingerprint=fp, max_action_id=max_action)
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


def summarize(root: Path, zip_bytes: int, zip_sha256: str) -> ExportSummary:
    """The Export-screen summary, recomputed from a staging tree (so a resumed export gets
    the same one)."""
    m = read_json(root / "manifest.json", Manifest)
    rs = m.review_stats
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
        review=ExportReviewSummary(
            auto_approved=rs.auto_approved,
            approved=rs.approved,
            edited=rs.edited,
            overrides=rs.overrides,
            numbers_verified=len(rs.numbers_verified_blocks),
        ),
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
    assert state.assemble is not None
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
        summary=summarize(paths.assembled, len(data), sha),
    )
    state.export = rec
    state.after_action_id = state.assemble.max_action_id
    _write_state(paths, state)
    dest.with_name(dest.name + ".rejected").unlink(missing_ok=True)
    if store is not None and store.writer:
        with store.tx():
            store.append_action(
                ActionKind.export_run,
                "export",
                payload={
                    "zip_sha256": sha,
                    "articles": rec.summary.articles,
                    "figures": rec.summary.figures,
                    "overrides": rec.summary.review.overrides,
                },
            )
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
        elif fingerprint(paths, st, state.after_action_id) != state.assemble.fingerprint:
            out.append(NodeState(node="assemble", state="stale", reason="inputs changed"))
        else:
            out.append(NodeState(node="assemble", state="fresh"))
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
