"""Read everything an export needs from a project (the only I/O besides the zip and staging)."""

from __future__ import annotations

import json
from typing import Literal

import manuallabor
from manuallabor import ids
from manuallabor.cleanup.types import AttachFile
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockStatus, Task
from manuallabor.contracts.figure import FigureRecord, parse_figure_file
from manuallabor.contracts.io import read_json
from manuallabor.contracts.manifest import ExportMarks, ManifestDocLearning, ManifestLearning
from manuallabor.export.types import (
    ActiveOverride,
    AssembleInputs,
    DocInput,
    ExportError,
    FigureData,
    HumanDecision,
)
from manuallabor.figures.types import FigureReport
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import scores_current
from manuallabor.state.data import ProjectData
from manuallabor.state.models import ActionKind
from manuallabor.state.review import Derived, load_review_overlay
from manuallabor.state.store import Store, sha_text

__all__ = ["active_overrides", "doc_ready", "last_models", "load_inputs"]


def doc_ready(paths: ProjectPaths, slug: str) -> bool:
    """Every input of the export exists, and the scores are of this `SCORING_ALGO_VERSION`
    (a score file from before an upgrade is "not scored yet", design 03 section 2.10a)."""
    dp = paths.doc(slug)
    return (
        dp.blocks.is_file()
        and dp.clean.is_file()
        and dp.groups.is_file()
        and dp.attach.is_file()
        and scores_current(paths, slug)
    )


def active_overrides(store: Store, after_id: int) -> list[ActiveOverride]:
    out: list[ActiveOverride] = []
    for a in store.actions_of((ActionKind.export_override,), after_id):
        out.append(
            ActiveOverride(
                action_id=a.id,
                ts=a.ts,
                reason=str(a.payload.get("reason", "")),
                target_id=a.payload.get("target_id"),
                flag_id=a.payload.get("flag_id"),
            )
        )
    return out


def last_models(paths: ProjectPaths) -> dict[str, tuple[str, str]]:
    """Task -> (provider, model) of the last call logged for it."""
    out: dict[str, tuple[str, str]] = {}
    log = paths.llm_log
    if not log.is_file():
        return out
    valid = {t.value for t in Task}
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("task") in valid and o.get("provider") and o.get("model"):
            out[str(o["task"])] = (str(o["provider"]), str(o["model"]))
    return out


def human_decisions(overlay: list[tuple[Block, Derived]]) -> dict[str, HumanDecision]:
    """Block id -> the decision behind every approved or edited block: its time, and for an
    edited block whether a person wrote the text or accepted an agent proposal (section 20),
    when the edit was made and the raw text it replaced (section 20.12). The decision log holds
    the sha256 of the raw text each decision was made on; an edit whose hash is not the block's
    raw text is no proof of what it replaced, and the export refuses rather than guess."""
    out: dict[str, HumanDecision] = {}
    for b, r in overlay:
        if b.status not in (BlockStatus.approved, BlockStatus.edited) or r.decision is None:
            continue
        edited_by: Literal["person", "agent_proposal"] | None = None
        edited_at = None
        original = None
        if b.status == BlockStatus.edited:
            edit = r.edit if r.edit is not None else r.decision
            edited_by = "agent_proposal" if edit.source == "agent" else "person"
            if edit.raw_sha256 != sha_text(b.raw_text):
                raise ExportError(
                    f"{b.id}: its edit was made on other source text than the block's raw text "
                    "(the decision log's raw_sha256 differs); re-review the block in Verify"
                )
            edited_at = edit.decision.timestamp
            original = b.raw_text
        out[b.id] = HumanDecision(
            at=r.decision.decision.timestamp,
            edited_by=edited_by,
            edited_at=edited_at,
            original_text=original,
        )
    return out


def _load_figures(paths: ProjectPaths, slug: str) -> dict[str, FigureData]:
    dp = paths.doc(slug)
    if not dp.figure_report.is_file():
        return {}
    report = read_json(dp.figure_report, FigureReport)
    out: dict[str, FigureData] = {}
    for f in report.figures:
        sc = paths.figure_file(slug, f.figure_id, "json")
        if not sc.is_file():
            continue
        rec = read_json(sc, FigureRecord)
        target = parse_figure_file(rec.id, rec.file, ("png", "svg"))
        base = paths.figure_dir(slug)
        png = (base / rec.file).resolve()
        svg = (base / rec.svg).resolve() if rec.svg is not None else None
        out[rec.id] = FigureData(
            record=rec,
            caption_block_id=f.caption_block_id,
            canonical=None if target is None else target[1],
            png=png,
            svg=svg,
        )
    return out


def load_inputs(
    paths: ProjectPaths,
    store: Store,
    after_action_id: int = 0,
    marks: ExportMarks = "invisible",
) -> AssembleInputs:
    cfg = paths.load_config()
    data = ProjectData(paths, store)
    sel = data.selection()
    selected_all = set(sel.block_ids)
    docs: dict[str, DocInput] = {}
    learn_docs: dict[str, ManifestDocLearning] = {}
    for slug in paths.list_slugs():
        if not doc_ready(paths, slug):
            raise ExportError(f"stale: {slug}: not processed to score2 (run `labor run`)")
        gf = data.groups(slug)
        af: AttachFile | None = data.attach(slug)
        assert gf is not None and af is not None
        cf = data.clean_file(slug)
        learn_docs[slug] = ManifestDocLearning(
            group=gf.learning_snapshot, clean=cf.learning_snapshot if cf else "baseline"
        )
        overlay = load_review_overlay(paths, store, slug)
        docs[slug] = DocInput(
            doc=paths.load_document(slug),
            blocks=[b for b, _ in overlay],
            groups=gf,
            attach=af,
            figures=_load_figures(paths, slug),
            selected={b for b in selected_all if ids.parse_block_id(b)[0] == slug},
            scope=data.scope_ids(slug, selected_all),
            decisions=human_decisions(overlay),
        )
    return AssembleInputs(
        config=cfg,
        split=sel.article_split,
        docs=docs,
        flags=store.flags(),
        overrides=active_overrides(store, after_action_id),
        models=last_models(paths),
        learning=ManifestLearning(enabled=cfg.learning.enabled, docs=learn_docs),
        tool_version=manuallabor.__version__,
        marks=marks,
    )
