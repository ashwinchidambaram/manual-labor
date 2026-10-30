"""In-memory implementations of the state/job Protocols (design 07 section 11.2) for API tests.

They model only what the HTTP layer needs: shapes, persistence across app instances, the
queue/next/trail algorithm of design 5.3, and the 409 edit conflict."""

# ruff: noqa: E501

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from manuallabor.cleanup.types import AttachOverride
from manuallabor.contracts import (
    CoverageReport,
    FigureRecord,
    Flag,
    GroupOverride,
    GroupsFile,
    Selection,
    TaskModels,
)
from manuallabor.contracts.decision import Decision
from manuallabor.contracts.enums import (
    AttachRule,
    BlockStatus,
    BlockType,
    DecisionAction,
    Extraction,
    FlagStatus,
)
from manuallabor.contracts.selection import ReviewLoad, ScopeSummary
from manuallabor.grouping.types import default_params
from manuallabor.state.errors import EditConflictError, NotFound, OutOfScope
from manuallabor.state.interfaces import AppServices
from manuallabor.state.models import (
    ActionKind,
    ActionRecord,
    BlockDetail,
    Cursor,
    DecisionRecord,
    DocReadiness,
    EditConflict,
    FigureRailItem,
    JobInfo,
    LearningState,
    LearningUse,
    PageRef,
    QueueItem,
    QueuePage,
    QueueSort,
    RegroupIn,
    ReviewActionIn,
    ReviewActionOut,
    ReviewCounts,
    RunPlanIn,
    SelectionOp,
    SelectionOut,
    SnapshotInfo,
)
from tests.conftest import make_block

NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)


def bid(n: int, page: int = 1) -> str:
    return f"b-doc-p{page:03d}-{n:02d}"


FIG = "FIG-doc-p001-01"


def _items() -> list[QueueItem]:
    spec = [(1, 1, 0.2), (2, 1, 0.4), (3, 2, 0.5), (4, 2, 0.6), (5, 3, 0.7), (6, 3, 0.8)]
    items = [
        QueueItem(
            block_id=bid(n, p),
            doc_id="doc",
            page=p,
            type=BlockType.paragraph,
            confidence=c,
            status=BlockStatus.queued,
            reasons=["agreement"],
        )
        for n, p, c in spec
    ]
    items.append(
        QueueItem(
            block_id=bid(1, 4),
            doc_id="doc",
            page=4,
            type=BlockType.paragraph,
            confidence=0.9,
            status=BlockStatus.auto_approved,
        )
    )
    return items


class FakeState:
    """Everything the fakes persist; a new app built on the same state sees the same data."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.actions: list[ActionRecord] = []
        self.items = {i.block_id: i for i in _items()}
        self.decided: dict[str, BlockStatus] = {}
        self.cursor = Cursor(current_block_id=bid(1, 1))
        self.seen_requests: dict[str, ReviewActionOut] = {}
        self.selection = Selection(block_ids=[])
        self.open_flags = 0
        self.flags: list[Flag] = []
        self.threshold_history: list[tuple[float | None, float]] = []
        self.learning = LearningState()
        self.jobs: dict[str, JobInfo] = {}
        self.job_n = 0
        self.attach_seq = 0
        self.bboxes: dict[str, list[float]] = {}
        self.enqueued: list[tuple[str, RunPlanIn, list[Path]]] = []
        self.job_delay = 0.0

    def log(self, kind: ActionKind, target: str | None = None, **payload: Any) -> ActionRecord:
        rec = ActionRecord(
            id=len(self.actions) + 1,
            ts=NOW,
            screen="verify",
            kind=kind,
            target_id=target,
            payload=payload,
        )
        self.actions.append(rec)
        return rec


class FakeStore:
    def __init__(self, st: FakeState) -> None:
        self.st = st
        self.closed = False
        self.meta_rows: dict[str, str] = {}

    def meta(self, key: str) -> str | None:
        return self.meta_rows.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self.meta_rows[key] = value

    def tx(self) -> AbstractContextManager[None]:
        return nullcontext()

    def now(self) -> str:
        return "2026-10-29T00:00:00Z"

    def iter_actions(self) -> Iterator[ActionRecord]:
        return iter(list(self.st.actions))

    def open_flag_count(self) -> int:
        return self.st.open_flags

    def close(self) -> None:
        self.closed = True


def _key(item: QueueItem, sort: QueueSort) -> tuple[Any, ...]:
    if sort == QueueSort.by_page:
        return (item.page, item.block_id)
    return (item.confidence if item.confidence is not None else -1.0, item.block_id)


class FakeReview:
    def __init__(self, st: FakeState) -> None:
        self.st = st

    def _pending(
        self, sort: QueueSort, vt: float | None, doc: str | None = None
    ) -> list[QueueItem]:
        out = []
        for it in self.st.items.values():
            if it.block_id in self.st.decided:
                continue
            if doc and it.doc_id != doc:
                continue
            if sort == QueueSort.figures_only and it.type != BlockType.figure:
                continue
            machine_queued = it.status == BlockStatus.queued
            shown_auto = (
                it.status == BlockStatus.auto_approved
                and vt is not None
                and (it.confidence or 0.0) < vt
            )
            if machine_queued or shown_auto:
                out.append(it)
        return sorted(out, key=lambda i: _key(i, sort))

    def _counts(self) -> ReviewCounts:
        d = list(self.st.decided.values())
        return ReviewCounts(
            pending=len(self._pending(self.st.cursor.sort, None)),
            auto_approved=1,
            approved=d.count(BlockStatus.approved),
            edited=d.count(BlockStatus.edited),
            flagged_open=self.st.open_flags,
            in_scope=len(self.st.items),
        )

    def queue(
        self,
        sort: QueueSort | None,
        view_threshold: float | None,
        doc: str | None,
        limit: int,
        offset: int,
    ) -> QueuePage:
        cur = self.st.cursor
        items = self._pending(
            sort or cur.sort,
            view_threshold if view_threshold is not None else cur.view_threshold,
            doc,
        )
        return QueuePage(
            items=items[offset : offset + limit],
            total=len(items),
            counts=self._counts(),
            docs=[DocReadiness(doc_id="doc", state="ready")],
            cursor=cur,
        )

    def cursor(self) -> Cursor:
        return self.st.cursor

    def set_cursor(self, c: Cursor, request_id: str) -> Cursor:
        old = self.st.cursor.view_threshold
        if c.view_threshold != old:
            self.st.threshold_history.append((old, c.view_threshold or 0.0))
        self.st.cursor = c
        self.st.log(ActionKind.cursor, request_id=request_id)
        return c

    def detail(self, block_id: str) -> BlockDetail:
        if block_id not in self.st.items:
            raise NotFound(block_id)
        if block_id == bid(9, 9):
            raise OutOfScope(block_id)
        block = make_block("Torque to 35 Nm.", n=int(block_id[-2:]), page=int(block_id[7:10]))
        return BlockDetail(
            block=block,
            page=PageRef(
                doc_id="doc", page=1, width=612, height=792, render_url="/x.png", source_url="/s"
            ),
            learning=LearningUse(),
        )

    def _out(self, rec: ActionRecord, nxt: QueueItem | None, **kw: Any) -> ReviewActionOut:
        return ReviewActionOut(
            action_id=rec.id, next=nxt, cursor=self.st.cursor, counts=self._counts(), **kw
        )

    def act(self, a: ReviewActionIn) -> ReviewActionOut:
        if a.request_id in self.st.seen_requests:
            return self.st.seen_requests[a.request_id]
        cur = self.st.cursor
        if a.kind == "back":
            rec = self.st.log(ActionKind.back)
            if cur.trail:
                prev = cur.trail[-1]
                self.st.cursor = cur.model_copy(update={"trail": cur.trail[:-1]})
                self.st.cursor.current_block_id = prev
            nid = self.st.cursor.current_block_id
            out = self._out(rec, self.st.items.get(nid) if nid else None)
            self.st.seen_requests[a.request_id] = out
            return out
        assert a.block_id is not None
        item = self.st.items.get(a.block_id)
        if item is None:
            raise NotFound(a.block_id)
        decision = None
        flag = None
        if a.kind == "edit":
            assert a.text is not None
            if "36" in a.text and not a.confirm_content_change:
                raise EditConflictError(
                    EditConflict(violations=[], numeric_changes=["35 → 36"], diff=[])
                )
        if a.kind == "flag":
            self.st.open_flags += 1
            flag = Flag(
                id=f"flag-{self.st.open_flags:06d}",
                target_id=a.block_id,
                category=a.flag.category if a.flag else "other",  # type: ignore[arg-type]
                created_at=NOW,
            )
            self.st.flags.append(flag)
        action = {
            "approve": DecisionAction.approve,
            "edit": DecisionAction.edit,
            "flag": DecisionAction.flag,
            "skip": DecisionAction.skip,
        }[a.kind]
        rec = self.st.log(ActionKind(a.kind), a.block_id)
        decision = DecisionRecord(
            decision=Decision(
                seq=rec.id,
                block_id=a.block_id,
                action=action,
                score=item.confidence,
                threshold=0.85,
                signals=[],
                edited_text=a.text if a.kind == "edit" else None,
                flag_id=flag.id if flag else None,
                timestamp=NOW,
            ),
            action_id=rec.id,
            doc_id="doc",
            raw_sha256="0" * 64,
            shown_text_sha256="0" * 64,
            faith_passed=True if a.kind == "edit" else None,
        )
        status = {
            "approve": BlockStatus.approved,
            "edit": BlockStatus.edited,
            "flag": BlockStatus.flagged,
        }.get(a.kind)
        if status is not None:
            self.st.decided[a.block_id] = status
        pending = self._pending(cur.sort, cur.view_threshold, cur.doc_filter)
        k = _key(item, cur.sort)
        nxt = next((p for p in pending if _key(p, cur.sort) > k), pending[0] if pending else None)
        self.st.cursor = Cursor(
            sort=cur.sort,
            view_threshold=cur.view_threshold,
            doc_filter=cur.doc_filter,
            current_block_id=nxt.block_id if nxt else None,
            trail=([*cur.trail, a.block_id])[-50:],
        )
        out = self._out(rec, nxt, decision=decision, flag=flag, block_status=status)
        self.st.seen_requests[a.request_id] = out
        return out

    def flags(self, status: FlagStatus | None) -> list[Flag]:
        return [f for f in self.st.flags if status is None or f.status == status]

    def resolve_flag(self, flag_id: str, resolution: str, request_id: str) -> Flag:
        for i, f in enumerate(self.st.flags):
            if f.id == flag_id:
                done = f.model_copy(
                    update={
                        "status": FlagStatus.resolved,
                        "resolved_at": NOW,
                        "resolution": resolution,
                    }
                )
                self.st.flags[i] = done
                self.st.open_flags -= 1
                self.st.log(ActionKind.resolve_flag, f.target_id)
                return done
        raise NotFound(flag_id)

    def render_page(self, slug: str, page: int, dpi: int) -> Path:
        p = self.st.root / "render.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        return p

    def page_blocks(self, slug: str, page: int) -> list[dict[str, Any]]:
        return [
            {"block_id": bid(1), "bbox": [0, 0, 10, 10], "type": "paragraph", "status": "queued"}
        ]

    def block_statuses(self, slug: str) -> dict[str, BlockStatus]:
        return {it.block_id: it.status for it in self.st.items.values() if it.doc_id == slug}

    def titles(self, block_ids: Sequence[str]) -> list[dict[str, Any]]:
        return [
            {
                "block_id": it.block_id,
                "doc_id": it.doc_id,
                "page": it.page,
                "type": it.type.value,
                "section_title": it.section_title,
            }
            for b in dict.fromkeys(block_ids)
            if (it := self.st.items.get(b)) is not None
        ]


class FakeScope:
    def __init__(self, st: FakeState) -> None:
        self.st = st

    def _out(self, dropped: list[str] | None = None) -> SelectionOut:
        return SelectionOut(
            selection=self.st.selection,
            dropped=dropped or [],
            coverage=[
                CoverageReport(
                    doc_id="doc",
                    selected=len(self.st.selection.block_ids),
                    selectable=7,
                    structure=[],
                    topics=[],
                )
            ],
            summary=self.summary(),
        )

    def groups(self, doc: str | None) -> list[dict[str, Any]]:
        gf = GroupsFile(
            doc_id="doc",
            algo_version="t",
            fingerprint="0" * 64,
            embedding_model="m",
            embedding_dim=0,
            grouping_model="mock",
            learning_snapshot="baseline",
            params=default_params(),
            structure=[],
            topics=[],
            unassigned=[],
            stragglers=[],
            overlap=[],
            title_sources={},
            topic_status="ok",
            overrides_applied=0,
            overrides_stale=[],
        )
        cov = CoverageReport(doc_id="doc", selected=0, selectable=7, structure=[], topics=[])
        return [
            {"doc_id": "doc", "groups": gf.model_dump(mode="json"), "coverage": cov.model_dump()}
        ]

    def get(self) -> SelectionOut:
        return self._out()

    def apply(self, op: SelectionOp) -> SelectionOut:
        sel = self.st.selection
        ids = list(sel.block_ids)
        if op.op == "select":
            ids += op.block_ids
        elif op.op == "deselect":
            ids = [i for i in ids if i not in op.block_ids]
        elif op.op in ("select_group", "deselect_group"):
            grp = [bid(1), bid(2)] + ([bid(3)] if op.subtree else [])
            ids = ids + grp if op.op == "select_group" else [i for i in ids if i not in grp]
        view = sel.active_view
        split = sel.article_split
        if op.op == "set_view" and op.view:
            view = op.view  # type: ignore[assignment]
        if op.op == "set_split" and op.split:
            split = op.split  # type: ignore[assignment]
        self.st.selection = Selection(block_ids=ids, active_view=view, article_split=split)
        self.st.log(ActionKind(op.op))
        return self._out()

    def summary(self) -> ScopeSummary:
        n = len(self.st.selection.block_ids)
        return ScopeSummary(
            docs=1,
            articles_per_topic=1,
            articles_per_document=1,
            articles=1,
            blocks=n,
            figures=0,
            pages=1,
            review_load=ReviewLoad(queued=n, numeric_queued=0, threshold=0.85),
        )

    def regroup(self, r: RegroupIn) -> GroupOverride:
        self.st.log(ActionKind.regroup_move if r.kind == "move" else ActionKind.regroup_rename)
        if r.kind == "move":
            return GroupOverride(
                seq=1, kind="move", block_id=r.block_id, to_topic_slug=r.to_topic_slug
            )
        return GroupOverride(seq=1, kind="rename", topic_slug=r.topic_slug, title=r.title)

    def models(self) -> dict[str, Any]:
        return {"models": TaskModels().model_dump(mode="json"), "probe": None, "suggestions": None}

    def set_project_threshold(self, value: float, reason: str, request_id: str) -> float:
        self.st.log(ActionKind.threshold_project, value=value)
        return value


class FakeFigures:
    def __init__(self, st: FakeState) -> None:
        self.st = st

    def _record(self) -> FigureRecord:
        return FigureRecord(
            id=FIG,
            file=f"{FIG}.png",
            svg=None,
            source_doc="doc",
            product_model=None,
            page=1,
            bbox=[0, 0, 10, 10],
            extraction=Extraction.native,
            width=10,
            height=10,
            phash="0" * 16,
            caption_original=None,
            description_generated=None,
            tags=[],
            articles=["doc"],
            attach_rule=AttachRule.proximity,
            confidence=0.9,
            review=BlockStatus.queued,
        )

    def rail(self, article_id: str) -> list[FigureRailItem]:
        return [
            FigureRailItem(
                figure_id=FIG,
                block_id=bid(5, 1),
                record=self._record(),
                image_url=f"/api/figures/{FIG}/image",
                status=BlockStatus.queued,
            )
        ]

    def image_path(self, figure_id: str) -> Path:
        if figure_id != FIG:
            raise NotFound(figure_id)
        p = self.st.root / f"{FIG}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        return p

    def _ov(self, op: str, fid: str, article: str, anchor: str | None) -> AttachOverride:
        self.st.attach_seq += 1
        self.st.log(ActionKind(op), fid)
        return AttachOverride(
            seq=self.st.attach_seq,
            op=op,  # type: ignore[arg-type]
            figure_id=fid,
            article_id=article,
            anchor_block_id=anchor,
        )

    def attach(
        self, figure_id: str, article_id: str, anchor: str | None, request_id: str
    ) -> AttachOverride:
        return self._ov("attach", figure_id, article_id, anchor)

    def detach(self, figure_id: str, article_id: str, request_id: str) -> AttachOverride:
        return self._ov("detach", figure_id, article_id, None)

    def set_bbox(self, figure_id: str, bbox: list[float], request_id: str) -> None:
        self.st.bboxes[figure_id] = bbox
        self.st.log(ActionKind.crop_bbox, figure_id)


class FakeLearning:
    def __init__(self, st: FakeState) -> None:
        self.st = st

    def state(self) -> LearningState:
        return self.st.learning

    def set_flags(
        self,
        enabled: bool | None,
        use_global: bool | None,
        contribute_global: bool | None,
        request_id: str,
    ) -> LearningState:
        ls = self.st.learning
        upd = {
            k: v
            for k, v in (
                ("enabled", enabled),
                ("use_global", use_global),
                ("contribute_global", contribute_global),
            )
            if v is not None
        }
        self.st.learning = ls.model_copy(update=upd)
        self.st.log(ActionKind.learning_toggle)
        return self.st.learning

    def snapshot(self, request_id: str) -> SnapshotInfo:
        n = len(self.st.learning.snapshots) + 1
        snap = SnapshotInfo(id=f"{n:03d}", created_at=NOW, parent=f"{n - 1:03d}" if n > 1 else None)
        self.st.learning = self.st.learning.model_copy(
            update={"snapshots": [*self.st.learning.snapshots, snap]}
        )
        self.st.log(ActionKind.learning_snapshot)
        return snap

    def _activate(self, sid: str | None) -> LearningState:
        snaps = [s.model_copy(update={"active": s.id == sid}) for s in self.st.learning.snapshots]
        self.st.learning = self.st.learning.model_copy(
            update={
                "snapshots": snaps,
                "active": sid,
                "provenance": f"snapshot:{sid}" if sid else "baseline",
            }
        )
        return self.st.learning

    def activate(self, snapshot_id: str, request_id: str) -> LearningState:
        if snapshot_id not in {s.id for s in self.st.learning.snapshots}:
            raise NotFound(snapshot_id)
        self.st.log(ActionKind.learning_activate)
        return self._activate(snapshot_id)

    def reset(self, request_id: str) -> LearningState:
        self.st.log(ActionKind.learning_reset)
        return self._activate(None)

    def disable_item(self, item_id: str, request_id: str) -> SnapshotInfo:
        s = self.snapshot(request_id)
        self._activate(s.id)
        return s

    def publish(self, snapshot_id: str, request_id: str) -> SnapshotInfo:
        for s in self.st.learning.snapshots:
            if s.id == snapshot_id:
                self.st.log(ActionKind.learning_publish)
                return s
        raise NotFound(snapshot_id)


class FakeRunner:
    def __init__(self, st: FakeState) -> None:
        self.st = st
        self.started = False
        self.stopped = False

    def enqueue(
        self,
        plan: RunPlanIn,
        kind: str = "run",
        files: Sequence[Path] = (),
        request_id: str | None = None,
    ) -> JobInfo:
        if request_id is not None:
            for j in self.st.jobs.values():
                if j.plan.get("request_id") == request_id:
                    return j
        self.st.job_n += 1
        extra = {} if request_id is None else {"request_id": request_id}
        job = JobInfo(
            id=f"job-{self.st.job_n:06d}",
            kind=kind,
            plan={**plan.model_dump(mode="json"), **extra},
            status="queued",
            created_at=NOW,
        )
        self.st.jobs[job.id] = job
        self.st.enqueued.append((kind, plan, list(files)))
        if self.st.job_delay:
            threading.Thread(target=self._run, args=(job.id,), daemon=True).start()
        return job

    def _run(self, job_id: str) -> None:
        self.st.jobs[job_id] = self.st.jobs[job_id].model_copy(update={"status": "running"})
        time.sleep(self.st.job_delay)  # a blocking "stage" in a worker thread
        if self.st.jobs[job_id].status == "running":
            self.st.jobs[job_id] = self.st.jobs[job_id].model_copy(
                update={"status": "done", "progress": 1.0}
            )

    def get(self, job_id: str) -> JobInfo:
        if job_id not in self.st.jobs:
            raise NotFound(job_id)
        return self.st.jobs[job_id]

    def list(self, status: set[str] | None = None) -> list[JobInfo]:
        return [j for j in self.st.jobs.values() if status is None or j.status in status]

    def cancel(self, job_id: str) -> JobInfo:
        job = self.get(job_id).model_copy(update={"status": "cancelled"})
        self.st.jobs[job_id] = job
        return job

    def log(self, job_id: str, after_line: int, limit: int = 500) -> list[dict[str, Any]]:
        self.get(job_id)
        lines = [{"event": "job_start", "units": 1}, {"event": "job_end", "status": "done"}]
        return lines[after_line : after_line + limit]

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def make_services(paths: Any, st: FakeState, mock: bool = True) -> AppServices:
    return AppServices(
        paths=paths,
        store=FakeStore(st),
        review=FakeReview(st),
        scope=FakeScope(st),
        figures=FakeFigures(st),
        learning=FakeLearning(st),
        runner=FakeRunner(st),
        mock=mock,
    )
