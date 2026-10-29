"""Scope service (design 07 section 5.3): selection ops, coverage, summary, regroup, models."""

from __future__ import annotations

import json
from typing import Any

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.enums import ArticleSplit, GroupView
from manuallabor.contracts.group import GroupOverride, GroupsFile
from manuallabor.contracts.io import read_json, write_json
from manuallabor.contracts.probe import ProbeResult
from manuallabor.contracts.selection import CoverageReport, ScopeSummary, Selection
from manuallabor.grouping import selection as sel_ops
from manuallabor.grouping.coverage import coverage
from manuallabor.project import ProjectPaths
from manuallabor.state import projections
from manuallabor.state.data import ProjectData
from manuallabor.state.errors import InvalidOp, NotFound
from manuallabor.state.models import (
    ActionKind,
    RegroupIn,
    SelectionOp,
    SelectionOut,
)
from manuallabor.state.store import Store

__all__ = ["ScopeService"]

_KIND = {
    "select": ActionKind.select,
    "deselect": ActionKind.deselect,
    "select_group": ActionKind.select_group,
    "deselect_group": ActionKind.deselect_group,
    "set_view": ActionKind.set_view,
    "set_split": ActionKind.set_split,
}


def _sel_json(sel: Selection) -> str:
    return json.dumps(sel.model_dump(mode="json"), sort_keys=True)


class ScopeService:
    def __init__(self, paths: ProjectPaths, store: Store, data: ProjectData) -> None:
        self.paths = paths
        self.store = store
        self.data = data

    # -- read ---------------------------------------------------------------------------------

    def groups(self, doc: str | None) -> list[dict[str, Any]]:
        sel = set(self.data.selection().block_ids)
        out: list[dict[str, Any]] = []
        for slug, gf in sorted(self.data.all_groups().items()):
            if doc is not None and slug != doc:
                continue
            out.append({"doc_id": slug, "groups": gf, "coverage": coverage(sel, gf)})
        return out

    def _coverage(self, sel: Selection, groups: dict[str, GroupsFile]) -> list[CoverageReport]:
        s = set(sel.block_ids)
        return [coverage(s, gf) for _slug, gf in sorted(groups.items())]

    def summary(self) -> ScopeSummary:
        return self._summary(self.data.selection(), self.data.all_groups())

    def _summary(self, sel: Selection, groups: dict[str, GroupsFile]) -> ScopeSummary:
        blocks: dict[str, list[Block]] = {}
        for slug in groups:
            if self.paths.doc(slug).scores.is_file():
                blocks[slug] = self.data.machine_blocks(slug)
        return sel_ops.scope_summary(
            sel, groups, blocks, threshold=self.paths.load_config().threshold
        )

    def get(self) -> SelectionOut:
        groups = self.data.all_groups()
        sel = self.data.selection()
        return SelectionOut(
            selection=sel,
            dropped=[],
            coverage=self._coverage(sel, groups),
            summary=self._summary(sel, groups),
        )

    # -- write --------------------------------------------------------------------------------

    def _apply(self, op: SelectionOp, sel: Selection, groups: dict[str, GroupsFile]) -> Selection:
        if op.op == "select":
            return sel_ops.select_blocks(sel, op.block_ids)
        if op.op == "deselect":
            return sel_ops.deselect_blocks(sel, op.block_ids)
        if op.op in ("select_group", "deselect_group"):
            if op.group_id is None:
                raise InvalidOp("group_id is required")
            gf = self._group_file(op, groups)
            fn = sel_ops.select_group if op.op == "select_group" else sel_ops.deselect_group
            try:
                return fn(sel, op.group_id, subtree=op.subtree, gf=gf)
            except KeyError as exc:
                raise NotFound(f"group {op.group_id}") from exc
        if op.op == "set_view":
            if op.view is None:
                raise InvalidOp("view is required")
            return sel_ops.set_view(sel, GroupView(op.view))
        if op.split is None:
            raise InvalidOp("split is required")
        return sel_ops.set_split(sel, ArticleSplit(op.split))

    @staticmethod
    def _group_file(op: SelectionOp, groups: dict[str, GroupsFile]) -> GroupsFile:
        if op.doc_id is not None:
            gf = groups.get(op.doc_id)
            if gf is None:
                raise NotFound(op.doc_id)
            return gf
        for gf in groups.values():
            if any(g.id == op.group_id for g in (*gf.structure, *gf.topics)):
                return gf
        raise NotFound(f"group {op.group_id}")

    def apply(self, op: SelectionOp) -> SelectionOut:
        groups = self.data.all_groups()
        # read-modify-write inside one write transaction (BEGIN IMMEDIATE + the store lock):
        # concurrent PUTs apply their ops one after the other instead of overwriting each other
        with self.store.tx():
            prev = self.store.action_by_request(op.request_id, tuple(_KIND.values()))
            if prev is not None:
                return SelectionOut.model_validate(prev.payload["_outcome"])
            before = self.data.selection()
            new = self._apply(op, before, groups)
            new, dropped = sel_ops.normalize_to(new, sel_ops.selectable_ids(groups))
            out = SelectionOut(
                selection=new,
                dropped=dropped,
                coverage=self._coverage(new, groups),
                summary=self._summary(new, groups),
            )
            aid = self.store.next_action_id()
            self.store.append_action(
                _KIND[op.op],
                "cli" if op.request_id.startswith("cli-") else "scope",
                doc_id=op.doc_id,
                target_id=op.group_id,
                payload={
                    "op": op.op,
                    "block_ids": op.block_ids,
                    "group_id": op.group_id,
                    "subtree": op.subtree,
                    "_outcome": out.model_dump(mode="json"),
                },
                before=_sel_json(before),
                after=_sel_json(new),
                request_id=op.request_id,
                action_id=aid,
            )
            self.store.set_selection_json(_sel_json(new), aid)
            self.store.after_commit(lambda: projections.project_selection(self.store, self.paths))
        return out

    def regroup(
        self, r: RegroupIn, *, screen: str = "scope", meta: dict[str, Any] | None = None
    ) -> GroupOverride:
        prev = self.store.action_by_request(
            r.request_id, (ActionKind.regroup_move, ActionKind.regroup_rename)
        )
        if prev is not None:
            return GroupOverride.model_validate(prev.payload["_outcome"])
        if r.doc_id not in self.paths.list_slugs():
            raise NotFound(r.doc_id)
        gf = self.data.groups(r.doc_id)
        if gf is None:
            raise NotFound(f"{r.doc_id}: not grouped yet")
        seq = self.store.next_override_seq("group_overrides")
        try:
            if r.kind == "move":
                if r.block_id is None or r.to_topic_slug is None:
                    raise InvalidOp("move requires block_id and to_topic_slug")
                ov = GroupOverride(
                    seq=seq, kind="move", block_id=r.block_id, to_topic_slug=r.to_topic_slug
                )
            else:
                if r.topic_slug is None or r.title is None:
                    raise InvalidOp("rename requires topic_slug and title")
                ov = GroupOverride(seq=seq, kind="rename", topic_slug=r.topic_slug, title=r.title)
        except ValueError as exc:
            if isinstance(exc, InvalidOp):
                raise
            raise InvalidOp(str(exc)) from exc
        topics = {t.slug: t for t in gf.topics}
        example: dict[str, Any] = {"doc_id": r.doc_id, "regroup": None}
        if meta is not None:
            example["proposal"] = meta.get("proposal")
        if r.kind == "move" and r.block_id is not None:
            frm = next((t for t in gf.topics if r.block_id in t.block_ids), None)
            to = topics.get(r.to_topic_slug or "")
            example["regroup"] = {
                "from_topic": frm.slug if frm else None,
                "from_title": frm.title if frm else None,
                "to_topic": r.to_topic_slug,
                "to_title": to.title if to else None,
                "summary": self._block_summary(r.doc_id, r.block_id),
            }
        elif r.kind == "rename" and r.topic_slug is not None:
            t = topics.get(r.topic_slug)
            example["regroup"] = {
                "from_topic": r.topic_slug,
                "from_title": t.title if t else None,
                "to_topic": r.topic_slug,
                "to_title": r.title,
                "summary": "",
            }
        with self.store.tx():
            aid = self.store.next_action_id()
            self.store.add_override(
                "group_overrides",
                seq,
                r.doc_id,
                json.dumps(ov.model_dump(mode="json"), sort_keys=True),
                aid,
            )
            self.store.append_action(
                ActionKind.regroup_move if r.kind == "move" else ActionKind.regroup_rename,
                screen,
                doc_id=r.doc_id,
                target_id=r.block_id or r.topic_slug,
                payload={
                    "override": ov.model_dump(mode="json"),
                    **{k: v for k, v in (meta or {}).items() if k != "proposal"},
                    "_outcome": ov.model_dump(mode="json"),
                },
                example=example,
                provenance=gf.learning_snapshot,
                request_id=r.request_id,
                action_id=aid,
            )
            self.store.after_commit(lambda: projections.project_overrides(self.store, self.paths))
        return ov

    def _block_summary(self, slug: str, block_id: str) -> str:
        for b in self.data.raw_blocks(slug):
            if b.id == block_id:
                return " ".join(b.raw_text.split())[:200]
        return ""

    def models(self) -> dict[str, Any]:
        cfg = self.paths.load_config()
        probe = None
        suggestions = None
        pj = self.paths.root / "probe.json"
        if pj.is_file():
            from manuallabor.providers.probe import suggest

            probe = read_json(pj, ProbeResult)
            suggestions = suggest(probe)
        return {"models": cfg.models, "probe": probe, "suggestions": suggestions}

    def set_project_threshold(self, value: float, reason: str, request_id: str) -> float:
        prev = self.store.action_by_request(request_id, (ActionKind.threshold_project,))
        if prev is not None:
            return float(prev.payload["_outcome"])
        if not 0.0 <= value <= 1.0:
            raise InvalidOp("threshold must be within 0..1")
        cfg: ProjectConfig = self.paths.load_config()
        old = cfg.threshold
        with self.store.tx():
            aid = self.store.next_action_id()
            self.store.append_action(
                ActionKind.threshold_project,
                "settings",
                payload={"old": old, "new": value, "reason": reason, "_outcome": value},
                request_id=request_id,
                action_id=aid,
            )
            self.store.add_threshold_history("project", old, value, reason, aid)
            self.store.after_commit(
                lambda: write_json(self.paths.config, cfg.model_copy(update={"threshold": value}))
            )
        return value


__all__ += ["ids"]
