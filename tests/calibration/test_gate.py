"""Design 10 test 19 (the gate): 400 seeded decisions -> the threshold suggestion is exactly
0.85, and project.json is byte-identical until an explicit apply."""

from __future__ import annotations

import hashlib
import json

from typer.testing import CliRunner

from manuallabor.calibration.apply import CalibrationService
from manuallabor.cli import app
from manuallabor.contracts.io import write_json
from manuallabor.state.learning import LearningService
from manuallabor.state.models import ActionKind
from tests.agent.conftest import AEnv
from tests.calibration.helpers import add, example

# (score range lo, hi, n, edits): the fixed counts of the design
SPEC = [
    (0.40, 0.60, 100, 30),
    (0.60, 0.75, 80, 8),
    (0.75, 0.80, 30, 2),
    (0.80, 0.85, 30, 1),
    (0.85, 1.00, 160, 0),
]


def seed_decisions(e: AEnv) -> None:
    i = 0
    for lo, hi, n, edits in SPEC:
        nb = round((hi - lo) / 0.05)
        for k in range(n):
            b = k % nb
            score = round(lo + b * 0.05 + 0.025, 3) if hi < 1.0 or b < nb - 1 else 0.99
            i += 1
            bid = f"b-clean-p{(i - 1) // 90 + 1:03d}-{(i - 1) % 90 + 1:02d}"
            edited = (k // nb) < edits // nb + (1 if b < edits % nb else 0) and k < n
            raw = f"synthetic text {i}"
            ex = example(bid, raw, score=score, shown=raw, final=raw + " x" if edited else raw)
            add(e.store, ActionKind.edit if edited else ActionKind.approve, ex)


def sha(p) -> str:  # type: ignore[no-untyped-def]
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_19_threshold_suggestion_from_400_decisions(aenv: AEnv) -> None:  # noqa: F811
    cfg = aenv.paths.load_config().model_copy(update={"threshold": 0.9})
    write_json(aenv.paths.config, cfg)
    seed_decisions(aenv)
    before = sha(aenv.paths.config)
    cal = CalibrationService(aenv.paths, aenv.store, aenv.data, aenv.runner)
    rep = cal.report()
    assert rep.n_outcomes == 400 and rep.n_numeric_excluded == 0
    assert sum(b.n for b in rep.buckets) == 400 and sum(b.edited for b in rep.buckets) == 41
    by = {(b.lo, b.hi): b for b in rep.buckets}
    assert (by[(0.4, 0.45)].n, by[(0.85, 0.9)].edited) == (25, 0)
    assert sum(b.n for b in rep.buckets if b.lo >= 0.85) == 160
    assert rep.suggested_threshold == 0.85 and rep.suggestion_reason == "ok"
    row = {r.t: r for r in rep.pooled}
    assert abs(row[0.8].hi - 0.0232) < 5e-4 and abs(row[0.85].hi - 0.0166) < 5e-4
    assert row[0.8].hi >= 0.02 > row[0.85].hi
    # reading, snapshotting and the CLI never write project.json
    LearningService(aenv.paths, aenv.store).snapshot("snap-1")
    aenv.close()
    res = CliRunner().invoke(app, ["calibration", str(aenv.paths.root), "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["suggested_threshold"] == 0.85
    assert sha(aenv.paths.config) == before
    aenv.store = type(aenv.store).open(aenv.paths, clock=aenv.store.clock)
    aenv.data.store = aenv.store
    cal = CalibrationService(aenv.paths, aenv.store, aenv.data, aenv.runner)
    aenv.runner.store = aenv.store
    # explicit apply, next documents: pins keep the old effective threshold, no job runs
    n_jobs = len(aenv.store.job_rows())
    thr, pinned, job = cal.apply(0.85, "next_docs", "apply-1")
    assert (thr, job) == (0.85, None) and pinned == ["clean", "figures"]
    new = aenv.paths.load_config()
    assert new.threshold == 0.85 and new.doc_thresholds == {"clean": 0.9, "figures": 0.9}
    assert new.threshold_for("clean") == 0.9
    hist = aenv.store.q("SELECT kind, old, new, reason FROM threshold_history")
    assert [tuple(r) for r in hist] == [("project", 0.9, 0.85, "calibration")]
    assert len(aenv.store.job_rows()) == n_jobs
    again = cal.apply(0.85, "next_docs", "apply-1")
    assert again[0] == 0.85 and len(aenv.store.q("SELECT 1 FROM threshold_history")) == 1
    # apply to the whole project: pins cleared, the restatus job is enqueued
    thr, pinned, job = cal.apply(0.8, "project", "apply-2")
    assert job is not None and pinned == []
    cfg2 = aenv.paths.load_config()
    assert cfg2.threshold == 0.8 and cfg2.doc_thresholds == {}
    assert json.loads(aenv.store.job_rows()[-1]["plan"])["to"] == "score2"
