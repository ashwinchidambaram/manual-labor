"""Module 10 review fixes: outcomes keep an edit that was later approved, the suggestion never
extrapolates below the data or past a bad sparse bucket, confusion mining learns look-alikes
only, and replaying a project-wide apply returns its job."""

from __future__ import annotations

from manuallabor.calibration.apply import CalibrationService
from manuallabor.calibration.learn import mine_confusions
from manuallabor.calibration.outcomes import outcomes
from manuallabor.calibration.suggest import suggest_threshold
from manuallabor.calibration.types import Outcome
from manuallabor.state.models import ActionKind, ReviewActionIn
from tests.agent.conftest import AEnv
from tests.calibration.helpers import example, record
from tests.calibration.test_gate import SPEC
from tests.calibration.test_pure import many, out

# -- item 3: an edit that was later approved is still an edit ------------------------------------


def test_edit_then_approve_counts_as_edited() -> None:
    bid = "b-clean-p001-01"
    acts = [
        record(
            1,
            ActionKind.edit,
            example(bid, "Torqe the bolt", shown="Torqe the bolt", final="Torque the bolt"),
        ),
        # K then A: the approval applies to the human edit
        record(
            2,
            ActionKind.approve,
            example(bid, "Torqe the bolt", shown="Torqe the bolt", final="Torque the bolt"),
        ),
    ]
    (o,) = outcomes(acts)
    assert o.action_id == 2 and o.edited


def test_edit_approve_on_other_raw_text_is_separate() -> None:
    bid = "b-clean-p001-01"
    acts = [
        record(1, ActionKind.edit, example(bid, "aa", shown="aa", final="ab")),
        record(2, ActionKind.approve, example(bid, "zz")),  # re-parsed text, approved as is
    ]
    by = {o.raw_sha: o for o in outcomes(acts)}
    assert sorted(o.edited for o in by.values()) == [False, True]


def test_noop_edit_then_approve_is_not_edited() -> None:
    bid = "b-clean-p001-01"
    acts = [
        record(1, ActionKind.edit, example(bid, "aa", shown="aa", final="aa")),
        record(2, ActionKind.approve, example(bid, "aa")),
    ]
    (o,) = outcomes(acts)
    assert not o.edited


def test_verify_edit_then_approve_is_edited(aenv: AEnv) -> None:
    bid = "b-figures-p006-03"
    blk = next(b for b in aenv.data.machine_blocks("figures") if b.id == bid)
    aenv.review.act(
        ReviewActionIn(
            kind="edit",
            block_id=bid,
            text=blk.raw_text + " plus",
            request_id="e1",
            confirm_content_change=True,
        )
    )
    aenv.review.act(ReviewActionIn(kind="approve", block_id=bid, request_id="a1"))
    mine = [o for o in outcomes(aenv.store.iter_actions()) if o.block_id == bid]
    assert len(mine) == 1 and mine[0].edited


# -- item 4: no extrapolation ------------------------------------------------------------------


def test_no_suggestion_below_the_lowest_populated_bucket() -> None:
    s, _w = suggest_threshold(many([(0.6, 140, 0)]), 0.02)
    assert s.suggested == 0.6 and s.reason == "ok"
    s, _w = suggest_threshold(many([(0.9, 200, 0)]), 0.02)
    assert s.suggested == 0.9
    # nothing reaches 20 decisions in any bucket: no suggestion at all
    spread = many([(0.5 + 0.05 * k + 0.01, 19, 0) for k in range(10)])
    s, _w = suggest_threshold(spread, 0.02)
    assert s.suggested is None


def test_a_bad_sparse_bucket_blocks_everything_below_it() -> None:
    rows = many([(0.6, 3000, 0), (0.97, 19, 19)])
    s, _w = suggest_threshold(rows, 0.02)
    assert s.suggested is None
    # a sparse bucket whose edits are not significant does not block
    rows = many([(0.6, 3000, 0), (0.97, 19, 1)])
    s, _w = suggest_threshold(rows, 0.02)
    assert s.suggested == 0.6


def test_the_gate_distribution_still_suggests_085() -> None:
    rows: list[Outcome] = []
    for lo, hi, n, edits in SPEC:
        nb = round((hi - lo) / 0.05)
        for k in range(n):
            b = k % nb
            score = round(lo + b * 0.05 + 0.025, 3) if hi < 1.0 or b < nb - 1 else 0.99
            edited = (k // nb) < edits // nb + (1 if b < edits % nb else 0)
            rows.append(out(score, edited, i=len(rows)))
    assert len(rows) == 400 and sum(o.edited for o in rows) == 41
    s, _w = suggest_threshold(rows, 0.02)
    assert (s.suggested, s.reason) == (0.85, "ok")


# -- item 6: look-alike confusions only; replayed apply ------------------------------------------


def _edits(pairs: list[tuple[str, str, str]]) -> list[Outcome]:
    acts = [
        record(i + 1, ActionKind.edit, example(bid, before, shown=before, final=after))
        for i, (bid, before, after) in enumerate(pairs)
    ]
    return outcomes(acts)


def test_confusions_learn_look_alikes_only() -> None:
    new_value = _edits([(f"b-clean-p001-0{i}", "Torque 35 N", "Torque 45 N") for i in (1, 2, 3)])
    assert mine_confusions(new_value) == []
    look = _edits([(f"b-clean-p001-0{i}", "Torque 3S N", "Torque 35 N") for i in (1, 2)])
    assert [(c.wrong, c.right, c.support) for c in mine_confusions(look)] == [("S", "5", 2)]
    mixed = _edits([(f"b-clean-p001-0{i}", "Gap 3S5 mm", "Gap 355 mm") for i in (1, 2)])
    assert [(c.wrong, c.right) for c in mine_confusions(mixed)] == [("S", "5")]
    # one look-alike plus one new digit in the same token: the token is not a look-alike
    both = _edits([(f"b-clean-p001-0{i}", "Gap 3S1 mm", "Gap 352 mm") for i in (1, 2)])
    assert mine_confusions(both) == []


def test_replayed_project_apply_returns_the_original_job(aenv: AEnv) -> None:
    cal = CalibrationService(aenv.paths, aenv.store, aenv.data, aenv.runner)
    thr, pinned, job = cal.apply(0.8, "project", "apply-p")
    assert job is not None and pinned == [] and thr == 0.8
    n_jobs = len(aenv.store.job_rows())
    thr2, pinned2, job2 = cal.apply(0.8, "project", "apply-p")
    assert job2 is not None and job2.id == job.id and (thr2, pinned2) == (thr, pinned)
    assert len(aenv.store.job_rows()) == n_jobs
