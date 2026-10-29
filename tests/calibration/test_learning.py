"""Design 10 tests 23-28: mining, the learned scoring layer, snapshots, A/B and the global store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuallabor.calibration.ab import AbRow, ab_core
from manuallabor.calibration.global_store import load_global, publish_outcomes
from manuallabor.calibration.learn import (
    derive_agent,
    derive_calibration,
    derive_cleanup_v2,
    mine_bullet_rules,
    mine_confusions,
    mine_hyphen_rules,
    mine_lexicon,
)
from manuallabor.calibration.outcomes import outcomes
from manuallabor.calibration.types import (
    ConfusionPair,
    CriticalPromotion,
    LearnedCalibration,
    LexiconEntry,
)
from manuallabor.cleanup.rules import PassCtx, compose, plan_passes
from manuallabor.contracts.config import LearningConfig
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.io import write_json
from manuallabor.scoring.learned import LearnedScoring, active_lexicon
from manuallabor.scoring.pipeline import run_score, score_block
from manuallabor.state.errors import InvalidOp
from manuallabor.state.learning import LearningService
from manuallabor.state.models import ActionKind
from tests.agent.conftest import AEnv
from tests.calibration.helpers import add, example, record
from tests.conftest import ctx, make_block


def edits(pairs: list[tuple[str, str, str]], start: int = 1):  # type: ignore[no-untyped-def]
    return [
        record(
            start + i,
            ActionKind.edit,
            example(f"b-clean-p001-{i + 1:02d}", raw, shown=shown, final=final),
        )
        for i, (raw, shown, final) in enumerate(pairs)
    ]


def test_23_confusion_mining() -> None:
    acts = edits(
        [
            ("Torque 3S N·m", "Torque 3S N·m", "Torque 35 N·m"),
            ("Set 4S psi", "Set 4S psi", "Set 45 psi"),
        ]
    )
    pairs = mine_confusions(outcomes(acts))
    assert [(p.wrong, p.right, p.support) for p in pairs] == [("S", "5", 2)]
    assert pairs[0].examples == ["3S→35", "4S→45"]
    # an edit that also rewords is not a pure look-alike fix
    reword = edits(
        [
            ("Torque 3S N·m", "Torque 3S N·m", "Tighten 35 N·m"),
            ("Set 4S psi", "Set 4S psi", "Set 45 psi"),
        ]
    )
    assert mine_confusions(outcomes(reword)) == []
    # the reverse pair with at least half the support cancels it
    both = acts + edits(
        [("Set 35 psi", "Set 35 psi", "Set 3S psi"), ("Set 45 psi", "Set 45 psi", "Set 4S psi")],
        start=10,
    )
    assert mine_confusions(outcomes(both)) == []


def test_23_learned_confusion_queues_more_and_only_when_enabled() -> None:
    learned = LearnedScoring(
        "snapshot:001", "x", confusions=(ConfusionPair(id="c", wrong="S", right="5", support=2),)
    )
    b = make_block("Torque 4S N·m")
    base = score_block(b, ctx(), threshold=0.85)
    on = score_block(b, ctx(), threshold=0.85, learned=learned)
    assert on.status == "queued" and on.learned_why == ["learned: 'S' for '5'"]
    assert on.confidence == base.confidence  # more careful, never more confident
    plain = make_block("Check the drive belt.")
    assert score_block(plain, ctx(), threshold=0.85, learned=learned).status == "auto_approved"
    assert score_block(b, ctx(), threshold=0.85) == base  # off: the baseline, exactly


def test_24_lexicon() -> None:
    def flag(i: int, text: str, note: str, numeric: bool = False):  # type: ignore[no-untyped-def]
        return record(
            i,
            ActionKind.flag,
            example(
                f"b-clean-p001-{i:02d}",
                text,
                flag_category="wrong_text",
                flag_note=note,
                numeric=numeric,
            ),
        )

    acts = [
        flag(1, "Tighten 12 klik firmly", "unit 'klik' missed"),
        flag(2, "Back off 7 klik then lock", "unit 'klik' missed"),
        flag(3, "Back off 7 klik then lock", "unit 'zzz' missed"),  # absent from the text
        flag(4, "Use ZQ 4471 here", "part 'ZQ 4471'"),
        flag(5, "Use ZQ 9921 there", "part 'ZQ 9921'"),
    ]
    lex = mine_lexicon(acts)
    assert [(e.kind, e.value, e.support) for e in lex] == [
        ("part_keyword", "ZQ", 2),
        ("unit", "klik", 2),
    ]
    learned = LearnedScoring("snapshot:001", "x", lexicon=tuple(lex))
    b = make_block("Turn 15 klik more.")
    assert not score_block(b, ctx(), threshold=0.85).has_numeric_spec
    on = score_block(b, ctx(), threshold=0.85, learned=learned, lexicon=lex)
    assert on.has_numeric_spec and on.status == "queued" and on.numeric_specs
    # an entry matching more than 30 % of a document's blocks is ignored for that document
    blocks = [make_block(f"Turn {i} klik more.", n=i + 1) for i in range(5)]
    kept, ignored = active_lexicon(learned, blocks)
    assert [e.value for e in kept] == ["ZQ"] and len(ignored) == 1
    assert (
        mine_lexicon([flag(1, "Tighten 12 klik firmly", "unit 'klik' missed", numeric=True)]) == []
    )


def test_25_cleanup_rules() -> None:
    def ed(i: int, raw: str, shown: str, final: str, *, t: str = "paragraph", faith: bool = True):  # type: ignore[no-untyped-def]
        return record(
            i,
            ActionKind.edit,
            example(
                f"b-clean-p001-{i:02d}", raw, shown=shown, final=final, block_type=t, faith=faith
            ),
        )

    keep = [
        ed(
            i,
            f"A self-\ncontained unit {i}",
            f"A selfcontained unit {i}",
            f"A self-contained unit {i}",
        )
        for i in (1, 2, 3)
    ]
    rules = mine_hyphen_rules(keep)
    assert [(r.kind, r.value, r.support) for r in rules] == [("hyphen_keep", "self-contained", 3)]
    assert rules[0].id.startswith("rule-h-")
    assert mine_hyphen_rules(keep[:2]) == []
    conflict = keep + [ed(9, "B self-\ncontained x", "B self-contained x", "B selfcontained x")]
    assert mine_hyphen_rules(conflict) == []
    assert mine_hyphen_rules([a for a in keep if False]) == []
    # the mined rule is applied by the cleanup pass chain and named in its output
    passes = plan_passes(BlockType.paragraph, False, rules)
    assert any(p.name == f"learned:{rules[0].id}" for p in passes)
    res = compose("A self-\ncontained unit", passes, PassCtx(block_type=BlockType.paragraph))
    assert "self-contained" in res.text and f"learned:{rules[0].id}" in res.applied
    bullets = [
        ed(i, f"* item {i}\nmore", f"* item {i}\nmore", f"• item {i}\nmore") for i in (11, 12, 13)
    ]
    br = mine_bullet_rules(bullets)
    assert [(r.kind, r.value) for r in br] == [("bullet_glyph", "*")] and br[0].support == 3
    v2 = derive_cleanup_v2(keep + bullets, {}, "snapshot:001")
    assert {r.kind for r in v2.rules} == {"hyphen_keep", "bullet_glyph"}


def test_26_snapshot_provenance_and_reset(aenv: AEnv) -> None:  # noqa: F811
    for i, (raw, final) in enumerate(
        [("Torque 3S N·m", "Torque 35 N·m"), ("Set 4S psi", "Set 45 psi")]
    ):
        add(
            aenv.store,
            ActionKind.edit,
            example(f"b-clean-p001-{i + 1:02d}", raw, shown=raw, final=final),
        )
    svc = LearningService(aenv.paths, aenv.store)
    s1 = svc.snapshot("s1")
    files = {p.name for p in aenv.paths.snapshot_dir(s1.id).iterdir()}
    assert {
        "cleanup.json",
        "grouping.json",
        "calibration.json",
        "agent.json",
        "manifest.json",
    } <= files
    cal = LearnedCalibration.model_validate_json(
        (aenv.paths.snapshot_dir(s1.id) / "calibration.json").read_text()
    )
    assert [(c.wrong, c.right) for c in cal.confusions] == [("S", "5")]
    # the same rows give the same bytes
    again = svc.snapshot("s1b")
    for name in ("cleanup.json", "calibration.json", "agent.json", "grouping.json"):
        a = (aenv.paths.snapshot_dir(s1.id) / name).read_text().replace("snapshot:001", "X")
        b = (aenv.paths.snapshot_dir(again.id) / name).read_text().replace("snapshot:002", "X")
        assert a == b
    svc.activate(s1.id, "act-1")
    cid = cal.confusions[0].id
    child = svc.disable_item(cid, "dis-1")
    assert child.id == "003"
    kid = LearnedCalibration.model_validate_json(
        (aenv.paths.snapshot_dir("003") / "calibration.json").read_text()
    )
    assert kid.confusions == [] and kid.snapshot == "snapshot:003"
    with pytest.raises(InvalidOp):
        svc.disable_item(cid, "dis-2")
    # scoring records the snapshot it used; reset restores the baseline bytes
    base = {s: aenv.paths.doc(s).scores.read_bytes() for s in ("clean",)}
    cfg = aenv.paths.load_config()
    write_json(aenv.paths.config, cfg.model_copy(update={"learning": LearningConfig(enabled=True)}))
    svc.activate(s1.id, "act-2")
    assert run_score(aenv.paths, only="clean", force=True, emit=lambda _o: None) == []
    sf = json.loads(aenv.paths.doc("clean").scores.read_text())
    assert sf["learning_snapshot"] == "snapshot:001"
    svc.activate(child.id, "act-3")
    assert run_score(aenv.paths, only="clean", force=True, emit=lambda _o: None) == []
    assert (
        json.loads(aenv.paths.doc("clean").scores.read_text())["learning_snapshot"]
        == "snapshot:003"
    )
    svc.reset("reset-1")
    assert run_score(aenv.paths, only="clean", force=True, emit=lambda _o: None) == []
    assert aenv.paths.doc("clean").scores.read_bytes() == base["clean"]


def test_26_off_means_baseline_even_with_files(aenv: AEnv) -> None:  # noqa: F811
    base = aenv.paths.doc("clean").scores.read_bytes()
    lc = LearnedCalibration(
        snapshot="snapshot:009",
        confusions=[ConfusionPair(id="c", wrong="S", right="5", support=2)],
        lexicon=[LexiconEntry(id="l", kind="unit", value="N", support=2)],
        critical_promotions=[
            CriticalPromotion(
                id="p",
                signal="garbage_ratio",
                below=0.99,
                support=1,
                rate_below=0.5,
                rate_above=0.0,
            )
        ],
    )
    write_json(aenv.paths.learned_calibration, lc)
    assert run_score(aenv.paths, only="clean", force=True, emit=lambda _o: None) == []
    assert aenv.paths.doc("clean").scores.read_bytes() == base


def ab_rows(n: int, rule_hits: int, *, worse: bool = False) -> list[AbRow]:
    rows = []
    for i in range(n):
        hit = i < rule_hits
        final = "self-contained" if hit else "plain text"
        base = "selfcontained" if hit else "plain text"
        learn = "self-contained" if hit else "plain text"
        if worse and hit:
            base, learn = "self-contained", "selfcontained"
        rows.append(AbRow(final, base, learn, edited=hit, added=False))
    return rows


def test_27_ab_replay() -> None:
    better = ab_core(ab_rows(34, 4), snapshot="001", holdout=True)
    assert better.verdict == "learned_better" and better.method == "holdout"
    assert (better.discordant.c, better.discordant.b) == (4, 0)  # type: ignore[union-attr]
    assert better.baseline_edit_rate > better.learned_edit_rate  # type: ignore[operator]
    worse = ab_core(ab_rows(34, 4, worse=True), snapshot="001", holdout=True)
    assert worse.verdict == "learned_worse"
    assert ab_core(ab_rows(34, 1), snapshot="001", holdout=True).verdict == "no_difference"
    small = ab_core(ab_rows(10, 4), snapshot="001", holdout=True)
    assert small.verdict == "insufficient" and small.method == "in_sample"
    assert ab_core(ab_rows(40, 5), snapshot="001", holdout=False).verdict == "insufficient"


def test_28_global_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path))
    acts = edits([("SECRET raw text 35", "SECRET raw text 35", "SECRET raw text 36")])
    outs = outcomes(acts)
    publish_outcomes("proj-a", outs)
    publish_outcomes("proj-b", outs)
    text = (tmp_path / "calibration" / "proj-a.jsonl").read_text()
    assert "SECRET" not in text and "b-clean" not in text
    row = json.loads(text.splitlines()[0])
    assert set(row) == {"score", "edited", "numeric", "block_type", "doc_kind", "signals"}
    assert len(load_global()) == 2 and len(load_global("proj-a")) == 1


def test_28_publish_needs_contribute_global(
    aenv: AEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path / "home"))
    add(aenv.store, ActionKind.edit, example("b-clean-p001-01", "aa 1", shown="aa 1", final="aa 2"))
    LearningService(aenv.paths, aenv.store).snapshot("s1")
    assert not (tmp_path / "home" / "calibration").exists()  # not opted in
    write_json(
        aenv.paths.config,
        aenv.paths.load_config().model_copy(
            update={"learning": LearningConfig(contribute_global=True)}
        ),
    )
    LearningService(aenv.paths, aenv.store).snapshot("s2")
    assert len(load_global()) == 1


def test_derivers_are_pure_and_registered() -> None:
    acts = edits(
        [
            ("Torque 3S N·m", "Torque 3S N·m", "Torque 35 N·m"),
            ("Set 4S psi", "Set 4S psi", "Set 45 psi"),
        ]
    )
    a, b = derive_calibration(acts, {}, "s"), derive_calibration(acts, {}, "s")
    assert a.model_dump_json() == b.model_dump_json()
    assert derive_agent(acts, {}, "s").examples == []
