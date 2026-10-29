"""Coverage mapping between the views (design tests 20-22)."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from manuallabor.grouping.coverage import coverage, overlap
from tests.grouping.conftest import Grouped

FOREIGN = "b-other-p001-01"


@settings(
    max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(data=st.data())
def test_coverage_sum_property(grouped: Grouped, stem: str, data: st.DataObject) -> None:
    gf, blocks = grouped.gf(stem), grouped.blocks(stem)
    selectable = sorted(b for g in gf.structure for b in g.block_ids)
    hf = [b.id for b in blocks if b.type.value in ("header", "footer")]
    picked = data.draw(st.sets(st.sampled_from(selectable)))
    noise = data.draw(st.sets(st.sampled_from([*hf, FOREIGN]))) if hf else {FOREIGN}
    rep = coverage(picked | noise, gf)
    assert rep.selected == len(picked) and rep.selectable == len(selectable)
    assert sum(c.selected for c in rep.structure) == len(picked)
    assert sum(c.selected for c in rep.topics) == len(picked)
    for c in [*rep.structure, *rep.topics]:
        assert 0 <= c.selected <= c.total
        assert (c.fraction is None) == (c.total == 0)
    for c in rep.structure:
        assert c.subtree_selected is not None and c.subtree_total is not None
        assert c.selected <= c.subtree_selected <= c.subtree_total


def test_coverage_symmetry(grouped: Grouped, stem: str) -> None:
    gf = grouped.gf(stem)
    table = {(o.topic_id, o.section_id): o.blocks for o in gf.overlap}
    for t in gf.topics:
        rep = coverage(set(t.block_ids), gf)
        assert {c.group_id: c.selected for c in rep.structure if c.selected} == {
            s: n for (tid, s), n in table.items() if tid == t.id
        }
        assert {c.group_id: c.selected for c in rep.topics if c.selected} == (
            {t.id: t.block_count} if t.block_count else {}
        )
        assert sum(n for (tid, _), n in table.items() if tid == t.id) == t.block_count
    for s in gf.structure:
        rep = coverage(set(s.block_ids), gf)
        assert {c.group_id: c.selected for c in rep.topics if c.selected} == {
            t: n for (t, sid), n in table.items() if sid == s.id
        }
        assert sum(n for (_, sid), n in table.items() if sid == s.id) == s.block_count
    assert overlap(gf.structure, gf.topics) == gf.overlap


def test_subtree_coverage_on_clean(grouped: Grouped) -> None:
    gf = grouped.gf("clean")
    section2 = {
        g.id for g in gf.structure if g.section_number and g.section_number.split(".")[0] == "2"
    }
    picked = {b for g in gf.structure if g.id in section2 for b in g.block_ids}
    rep = coverage(picked, gf)
    by_title = {g.title: c for g, c in zip(gf.structure, rep.structure, strict=True)}
    two = by_title["2. Drive Assembly"]
    assert two.subtree_fraction == 1.0 and two.fraction == 1.0
    one = by_title["1. Safety and Preparation"]
    assert one.subtree_fraction == 0.0 and one.fraction == 0.0
    assert by_title["2.1 Belt Inspection"].fraction == 1.0
