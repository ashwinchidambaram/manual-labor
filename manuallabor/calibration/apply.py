"""The calibration report and the explicit threshold apply (design 10 sections 4.6, 6).

Computing a report never writes project.json; only `apply` does, and only on an explicit
request, as a recorded action with a threshold history row."""

from __future__ import annotations

from typing import Any, Literal

from manuallabor.calibration.ab import ab_replay, observed_by_provenance
from manuallabor.calibration.buckets import bucketize, pooled
from manuallabor.calibration.global_store import load_global
from manuallabor.calibration.learn import (
    derive_calibration,
    mine_bullet_rules,
    mine_hyphen_rules,
)
from manuallabor.calibration.outcomes import outcomes
from manuallabor.calibration.signals import promotions, signal_reliability
from manuallabor.calibration.suggest import suggest_threshold
from manuallabor.calibration.types import LearnPreview
from manuallabor.contracts.io import write_json
from manuallabor.project import ProjectPaths
from manuallabor.state.data import ProjectData
from manuallabor.state.errors import InvalidOp
from manuallabor.state.models import (
    ActionKind,
    CalibrationReport,
    JobInfo,
    RunPlanIn,
)
from manuallabor.state.store import Store

__all__ = ["CalibrationService"]


class CalibrationService:
    def __init__(self, paths: ProjectPaths, store: Store, data: ProjectData, runner: Any) -> None:
        self.paths = paths
        self.store = store
        self.data = data
        self.runner = runner
        self._memo: dict[tuple[Any, ...], CalibrationReport] = {}

    def report(
        self, scope: Literal["project", "global"] = "project", snapshot: str | None = None
    ) -> CalibrationReport:
        cfg = self.paths.load_config()
        active = self.store.active_snapshot()
        key = (
            self.store.max_action_id(),
            active.id if active else None,
            scope,
            snapshot,
            cfg.threshold,
            cfg.target_edit_rate,
            cfg.learning.use_global,
        )
        hit = self._memo.get(key)
        if hit is not None:
            return hit
        actions = list(self.store.iter_actions())
        outs = outcomes(actions)
        pool = outs
        if scope == "global" and cfg.learning.use_global:
            pool = [*outs, *load_global(self.store.meta("project_uuid"))]
        elif scope == "global":
            scope = "project"
        target = cfg.target_edit_rate
        sug, warnings = suggest_threshold(pool, target, cfg.threshold)
        rel = signal_reliability(pool, target)
        seq_of = {d.action_id: d.decision.seq for d in self.store.decisions()}
        derived = derive_calibration(actions, seq_of, "preview")
        ab = None
        sid = snapshot or (active.id if active else None)
        if sid is not None:
            snap = self.store.get_snapshot(sid)
            if snap is not None:
                ab = ab_replay(self.paths, self.data, sid, snap.source_last_action, outs)
                ab = ab.model_copy(update={"observed": observed_by_provenance(outs)})
        rules = [r.id for r in (*mine_hyphen_rules(actions), *mine_bullet_rules(actions))]
        rep = CalibrationReport(
            buckets=bucketize(pool),
            target_edit_rate=target,
            suggested_threshold=sug.suggested,
            ab=ab,
            scope=scope,
            current_threshold=cfg.threshold,
            n_outcomes=len(pool),
            n_numeric_excluded=sum(1 for o in pool if o.numeric),
            pooled=pooled(pool),
            suggestion_reason=sug.reason,
            suggestion_detail=sug.detail,
            warnings=warnings,
            signals=rel,
            learn_preview=LearnPreview(
                confusions=derived.confusions,
                lexicon=derived.lexicon,
                rules=rules,
                promotions=promotions(rel),
            ),
        )
        self._memo = {key: rep}
        return rep

    def apply(
        self,
        threshold: float,
        scope: Literal["next_docs", "project"],
        request_id: str,
    ) -> tuple[float, list[str], JobInfo | None]:
        prev = self.store.action_by_request(request_id)
        if prev is not None:
            o = prev.payload["_outcome"]
            prev_job = self.runner.get(o["job"]) if o.get("job") else None
            return float(o["threshold"]), list(o["pinned"]), prev_job
        if not 0.0 <= threshold <= 1.0:
            raise InvalidOp("threshold must be within 0..1")
        cfg = self.paths.load_config()
        old = cfg.threshold
        suggested = self.report().suggested_threshold
        slugs = self.paths.list_slugs()
        pinned: list[str] = []
        if scope == "next_docs":
            pinned = [s for s in slugs if s not in cfg.doc_thresholds]
            doc_thr = {**cfg.doc_thresholds, **{s: old for s in pinned}}
        else:
            doc_thr = {}
        new_cfg = cfg.model_copy(update={"threshold": threshold, "doc_thresholds": doc_thr})
        job: JobInfo | None = None
        with self.store.tx():
            if scope == "project":
                # enqueued in the same transaction, so the action records the job id and a
                # replay of this request returns it
                job = self.runner.enqueue(RunPlanIn(to="score2"))
            aid = self.store.next_action_id()
            self.store.append_action(
                ActionKind.threshold_project,
                "agent",
                payload={
                    "old": old,
                    "new": threshold,
                    "scope": scope,
                    "suggested": suggested,
                    "against_suggestion": suggested is not None and threshold != suggested,
                    "reason": "calibration",
                    "_outcome": {
                        "threshold": threshold,
                        "pinned": pinned,
                        "job": None if job is None else job.id,
                    },
                },
                request_id=request_id,
                action_id=aid,
            )
            self.store.add_threshold_history("project", old, threshold, "calibration", aid)
            self.store.after_commit(lambda: write_json(self.paths.config, new_cfg))
        return threshold, pinned, job
