"""The learning layer (design 07 section 9; findings "Learning must be reversible").

Learned state is a separate, versioned layer: numbered immutable snapshots under
`<project>/learning/snapshots/NNN/`, one active pointer (the DB row), materialized into the
paths modules 4 and 5 already read. Learning never writes models, thresholds or any other
config key; the baseline is never edited. Reset removes only the materialized copies."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from manuallabor.cleanup.learned import OCR_SOURCES
from manuallabor.cleanup.types import FewShotExample, LearnedCleanup
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.io import dump_json, write_json, write_text_atomic
from manuallabor.grouping.learning import LearnedGrouping, RegroupExample
from manuallabor.project import ProjectPaths
from manuallabor.state import projections
from manuallabor.state.errors import InvalidOp, NotFound
from manuallabor.state.models import ActionKind, ActionRecord, LearningState, SnapshotInfo
from manuallabor.state.store import Store, fmt_ts, parse_ts

__all__ = [
    "DERIVERS",
    "LearningService",
    "derive_snapshot_files",
    "global_home",
    "project_learning",
    "provenance_for",
]

EXAMPLES_MAX = 200
MATERIALIZED = ("cleanup.json", "grouping.json", "calibration.json")


def global_home() -> Path:
    return Path(os.environ.get("MANUALLABOR_HOME", "~/.manuallabor")).expanduser()


def _global_dir() -> Path:
    return global_home() / "learning" / "snapshots"


def latest_global() -> str | None:
    d = _global_dir()
    if not d.is_dir():
        return None
    names = sorted(p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith("."))
    return names[-1] if names else None


# -- derivers (pure over action rows; module 10 registers more) --------------------------------


def derive_cleanup(
    actions: list[ActionRecord], seq_of_action: dict[int, int], snap: str
) -> LearnedCleanup:
    latest: dict[str, ActionRecord] = {}
    for a in actions:
        if a.kind in (ActionKind.approve, ActionKind.edit) and a.example is not None:
            latest[str(a.example["block_id"])] = a
    items: list[tuple[int, FewShotExample]] = []
    for a in latest.values():
        ex = a.example or {}
        raw = ex.get("raw_text")
        if not isinstance(raw, str):
            continue
        if a.kind == ActionKind.edit:
            if ex.get("faith_passed") is not True:
                continue
            clean = ex.get("clean_after")
        else:
            clean = ex.get("clean_before")
        if not isinstance(clean, str) or clean == raw:
            continue
        try:
            btype = BlockType(ex["block_type"])
        except (KeyError, ValueError):
            continue
        entry = ex.get("cleanup_entry") or {}
        items.append(
            (
                a.id,
                FewShotExample(
                    id=f"ex-{seq_of_action.get(a.id, a.id)}",
                    block_type=btype,
                    ocr=ex.get("raw_source") in OCR_SOURCES,
                    residual=list(entry.get("residual", [])),
                    raw=raw,
                    clean=clean,
                ),
            )
        )
    items.sort(key=lambda t: t[0])
    return LearnedCleanup(snapshot=snap, rules=[], examples=[e for _i, e in items[-EXAMPLES_MAX:]])


def derive_grouping(
    actions: list[ActionRecord], seq_of_action: dict[int, int], snap: str
) -> LearnedGrouping:
    out: list[RegroupExample] = []
    for a in actions:
        if a.kind not in (ActionKind.regroup_move, ActionKind.regroup_rename) or a.example is None:
            continue
        rg = a.example.get("regroup")
        if not isinstance(rg, dict) or not rg.get("from_title") or not rg.get("to_title"):
            continue
        out.append(
            RegroupExample(
                doc_id=str(a.doc_id),
                summary=str(rg.get("summary") or ""),
                from_title=str(rg["from_title"]),
                to_title=str(rg["to_title"]),
                kind="move" if a.kind == ActionKind.regroup_move else "rename",
            )
        )
    return LearnedGrouping(snapshot=snap, examples=out[-EXAMPLES_MAX:], do_not_merge=[])


DERIVERS: dict[str, Callable[[list[ActionRecord], dict[int, int], str], Any]] = {
    "cleanup": derive_cleanup,
    "grouping": derive_grouping,
}


def derive_snapshot_files(store: Store, snap_label: str) -> tuple[dict[str, str], dict[str, int]]:
    """{filename: text}, counts. Same action rows -> byte-identical files."""
    actions = list(store.iter_actions())
    seq_of_action = {d.action_id: d.decision.seq for d in store.decisions()}
    files: dict[str, str] = {}
    counts: dict[str, int] = {}
    for name, fn in DERIVERS.items():
        model = fn(actions, seq_of_action, snap_label)
        files[f"{name}.json"] = dump_json(model)
        counts[name] = len(model.examples) + len(getattr(model, "rules", []))
    return files, counts


def provenance_for(cfg: ProjectConfig, active: str | None, use_global_id: str | None) -> str:
    if not cfg.learning.enabled:
        return "baseline"
    if active is not None:
        return f"snapshot:{active}"
    if cfg.learning.use_global and use_global_id is not None:
        return f"global:{use_global_id}"
    return "baseline"


# -- materialization ---------------------------------------------------------------------------


def project_learning(store: Store, paths: ProjectPaths) -> None:
    """Make learning/{cleanup,grouping,calibration,active}.json match the active snapshot."""
    if not paths.config.is_file():
        return
    cfg = paths.load_config()
    active = store.active_snapshot()
    src: Path | None = None
    prov = ""
    if active is not None:
        src, prov = paths.snapshot_dir(active.id), f"snapshot:{active.id}"
    elif cfg.learning.use_global:
        gid = latest_global()
        if gid is not None:
            src, prov = _global_dir() / gid, f"global:{gid}"
    if src is None:
        if paths.learning_active.is_file():
            clear_materialized(paths)
        return
    for name in MATERIALIZED:
        target = paths.learning / name
        f = src / name
        if f.is_file():
            projections.write_if_differs(target, f.read_text(encoding="utf-8"))
        elif target.is_file():
            target.unlink()
    projections.write_if_differs(
        paths.learning_active,
        json.dumps({"id": prov.split(":", 1)[1], "provenance": prov}, sort_keys=True, indent=2)
        + "\n",
    )


def clear_materialized(paths: ProjectPaths) -> None:
    for name in (*MATERIALIZED, "active.json"):
        p = paths.learning / name
        if p.is_file():
            p.unlink()


# -- the service -------------------------------------------------------------------------------


class LearningService:
    def __init__(self, paths: ProjectPaths, store: Store) -> None:
        self.paths = paths
        self.store = store

    def state(self) -> LearningState:
        cfg = self.paths.load_config()
        act = self.store.active_snapshot()
        gid = latest_global()
        return LearningState(
            enabled=cfg.learning.enabled,
            use_global=cfg.learning.use_global,
            contribute_global=cfg.learning.contribute_global,
            active=act.id if act else None,
            provenance=provenance_for(cfg, act.id if act else None, gid),
            snapshots=self.store.snapshots(),
        )

    def _replay(self, request_id: str) -> ActionRecord | None:
        return self.store.action_by_request(request_id)

    def set_flags(
        self,
        enabled: bool | None,
        use_global: bool | None,
        contribute_global: bool | None,
        request_id: str,
    ) -> LearningState:
        if self._replay(request_id) is not None:
            return self.state()
        cfg = self.paths.load_config()
        upd = {
            k: v
            for k, v in (
                ("enabled", enabled),
                ("use_global", use_global),
                ("contribute_global", contribute_global),
            )
            if v is not None
        }
        new_cfg = cfg.model_copy(update={"learning": cfg.learning.model_copy(update=upd)})

        def write() -> None:
            write_json(self.paths.config, new_cfg)
            project_learning(self.store, self.paths)

        with self.store.tx():
            aid = self.store.next_action_id()
            self.store.append_action(
                ActionKind.learning_toggle,
                "settings",
                payload={"set": upd, "before": cfg.learning.model_dump(mode="json")},
                request_id=request_id,
                action_id=aid,
            )
            self.store.after_commit(write)
        return self.state()

    def _write_snapshot(
        self,
        sid: str,
        files: dict[str, str],
        parent: str | None,
        first: int | None,
        last: int | None,
        counts: dict[str, int],
        origin: str = "project",
    ) -> Path:
        final = self.paths.snapshot_dir(sid)
        if final.exists():
            if self.store.get_snapshot(sid) is not None:
                raise InvalidOp(f"snapshot {sid} already exists")
            shutil.rmtree(final)  # left by a kill between the rename and the DB commit
        tmp = final.with_name(f".tmp-{sid}")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for name, text in files.items():
            write_text_atomic(tmp / name, text)
        manifest = {
            "id": sid,
            "created_at": self.store.now(),
            "parent": parent,
            "origin": origin,
            "source_action_range": [first, last],
            "derivers": {k: "v1" for k in DERIVERS},
            "counts": counts,
        }
        write_text_atomic(
            tmp / "manifest.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        )
        os.rename(tmp, final)
        return final

    def snapshot(self, request_id: str) -> SnapshotInfo:
        prev = self._replay(request_id)
        if prev is not None:
            return self._info(str(prev.payload["snapshot"]))
        sid = self.store.next_snapshot_id()
        files, counts = derive_snapshot_files(self.store, f"snapshot:{sid}")
        last = self.store.max_action_id()
        first = 1 if last else None
        act = self.store.active_snapshot()
        snaps = self.store.snapshots()
        parent = act.id if act else (snaps[-1].id if snaps else None)
        with self.store.tx():
            aid = self.store.next_action_id()
            path = self._write_snapshot(sid, files, parent, first, last or None, counts)
            self.store.add_snapshot(
                id_=sid, parent=parent, origin="project", first=first, last=last or None,
                counts=counts, path=str(path.relative_to(self.paths.root)),
            )  # fmt: skip
            self.store.append_action(
                ActionKind.learning_snapshot,
                "settings",
                payload={"snapshot": sid, "counts": counts},
                request_id=request_id,
                action_id=aid,
            )
        return self._info(sid)

    def _info(self, sid: str) -> SnapshotInfo:
        s = self.store.get_snapshot(sid)
        if s is None:
            raise NotFound(f"snapshot {sid}")
        return s

    def activate(self, snapshot_id: str, request_id: str) -> LearningState:
        if self._replay(request_id) is not None:
            return self.state()
        if self.store.get_snapshot(snapshot_id) is None:
            raise NotFound(f"snapshot {snapshot_id}")
        before = self.store.active_snapshot()
        with self.store.tx():
            aid = self.store.next_action_id()
            self.store.set_active_snapshot(snapshot_id)
            self.store.append_action(
                ActionKind.learning_activate,
                "settings",
                payload={"snapshot": snapshot_id, "before": before.id if before else None},
                request_id=request_id,
                action_id=aid,
            )
            self.store.after_commit(lambda: project_learning(self.store, self.paths))
        return self.state()

    rollback = activate

    def reset(self, request_id: str) -> LearningState:
        """Disable the learned layer; snapshots and every decision are kept."""
        if self._replay(request_id) is not None:
            return self.state()
        before = self.store.active_snapshot()
        with self.store.tx():
            aid = self.store.next_action_id()
            self.store.set_active_snapshot(None)
            self.store.append_action(
                ActionKind.learning_reset,
                "settings",
                payload={"before": before.id if before else None},
                request_id=request_id,
                action_id=aid,
            )
            self.store.after_commit(lambda: self._after_reset())
        return self.state()

    def _after_reset(self) -> None:
        clear_materialized(self.paths)
        project_learning(self.store, self.paths)  # use_global may still materialize global

    def disable_item(self, item_id: str, request_id: str) -> SnapshotInfo:
        prev = self._replay(request_id)
        if prev is not None:
            return self._info(str(prev.payload["snapshot"]))
        act = self.store.active_snapshot()
        if act is None:
            raise InvalidOp("no active snapshot")
        src = self.paths.snapshot_dir(act.id)
        sid = self.store.next_snapshot_id()
        files: dict[str, str] = {}
        found = False
        counts: dict[str, int] = {}
        for name in ("cleanup.json", "grouping.json", "calibration.json"):
            f = src / name
            if not f.is_file():
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            data["snapshot"] = f"snapshot:{sid}"
            for key in ("rules", "examples"):
                items = data.get(key)
                if isinstance(items, list):
                    kept = [
                        i for i in items if not (isinstance(i, dict) and i.get("id") == item_id)
                    ]
                    found = found or len(kept) != len(items)
                    data[key] = kept
            files[name] = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
            counts[name.split(".")[0]] = len(data.get("rules", [])) + len(data.get("examples", []))
        if not found:
            raise InvalidOp(f"no item {item_id} in snapshot {act.id}")
        with self.store.tx():
            aid = self.store.next_action_id()
            path = self._write_snapshot(
                sid, files, act.id, act.source_first_action, act.source_last_action, counts
            )
            self.store.add_snapshot(
                id_=sid, parent=act.id, origin="project", first=act.source_first_action,
                last=act.source_last_action, counts=counts,
                path=str(path.relative_to(self.paths.root)),
            )  # fmt: skip
            self.store.set_active_snapshot(sid)
            self.store.append_action(
                ActionKind.learning_disable_item,
                "verify",
                payload={"snapshot": sid, "item": item_id, "parent": act.id},
                request_id=request_id,
                action_id=aid,
            )
            self.store.after_commit(lambda: project_learning(self.store, self.paths))
        return self._info(sid)

    def publish(self, snapshot_id: str, request_id: str) -> SnapshotInfo:
        cfg = self.paths.load_config()
        prev = self._replay(request_id)
        if prev is not None:
            return self._info(snapshot_id)
        if not cfg.learning.contribute_global:
            raise InvalidOp("publishing needs learning.contribute_global")
        info = self._info(snapshot_id)
        src = self.paths.snapshot_dir(snapshot_id)
        gdir = _global_dir()
        gdir.mkdir(parents=True, exist_ok=True)
        n = 0 if latest_global() is None else int(str(latest_global()))
        gid = f"{n + 1:03d}"
        tmp = gdir / f".tmp-{gid}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        for name in (*MATERIALIZED, "manifest.json"):
            f = src / name
            if not f.is_file():
                continue
            if name == "manifest.json":
                m = json.loads(f.read_text(encoding="utf-8"))
                m.update(
                    {
                        "id": gid,
                        "origin": f"project:{cfg.name}",
                        "published_at": fmt_ts(parse_ts(self.store.now())),
                    }
                )
                text = json.dumps(m, sort_keys=True, indent=2) + "\n"
            else:
                d = json.loads(f.read_text(encoding="utf-8"))
                d["snapshot"] = f"global:{gid}"
                text = json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
            write_text_atomic(tmp / name, text)
        os.rename(tmp, gdir / gid)
        with self.store.tx():
            aid = self.store.next_action_id()
            self.store.append_action(
                ActionKind.learning_publish,
                "settings",
                payload={"snapshot": snapshot_id, "global_id": gid},
                request_id=request_id,
                action_id=aid,
            )
        return info.model_copy(update={"origin": f"global:{gid}"})
