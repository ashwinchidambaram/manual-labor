"""Tests 23-30: figure attachment (rules, overrides, sidecar projection)."""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pytest

from manuallabor import ids
from manuallabor.cleanup.attach import FigureInfo, attach_document, figure_projection
from manuallabor.cleanup.refs import find_refs
from manuallabor.cleanup.types import AttachFile, AttachOverride
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import ArticleSplit, AttachRule, BlockType, SignalName
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import read_json, write_json
from manuallabor.figures.pipeline import run_figures
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import load_scored_blocks, run_score
from tests.cleanup.conftest import Proj, gf_of, gt, mk, nfc, quiet
from tests.conftest import copy_project

GATE_FIXTURES = ("clean", "twocol", "figures", "scanned", "manual")
REF_TYPES = (
    BlockType.paragraph,
    BlockType.list,
    BlockType.heading,
    BlockType.table,
    BlockType.other,
)


def _contained(part: str, whole: str) -> float:
    a, b = " ".join(nfc(part).split()), " ".join(nfc(whole).split())
    if not a:
        return 0.0
    sm = SequenceMatcher(None, a, b, autojunk=False)
    return sum(m.size for m in sm.get_matching_blocks()) / len(a)


def referencing_blocks(g: dict[str, Any], blocks: list[Block], number: str) -> list[Block]:
    """The parsed blocks on the GT block's page that carry the GT block's text (a parser may
    split it) and reference figure ``number``."""
    return [
        b
        for b in blocks
        if b.page == g["page"]
        and b.type in REF_TYPES
        and number in [r.number for r in find_refs(b.raw_text, False)]
        and _contained(b.raw_text, g["text"]) >= 0.8
    ]


def article_of(proj: Proj, slug: str, block_id: str) -> str:
    for t in proj.gf(slug).topics:
        if block_id in t.block_ids:
            return ids.article_id(slug, t.slug)
    raise AssertionError(f"{block_id} is in no topic")


def sidecar(proj: Proj, slug: str, fid: str) -> FigureRecord:
    return read_json(proj.paths.figure_file(slug, fid, "json"), FigureRecord)


def attachments(af: AttachFile) -> dict[tuple[str, str], Any]:
    return {(a.article_id, f.figure_id): f for a in af.articles for f in a.figures}


# -- 23 gate --------------------------------------------------------------------------------


@pytest.mark.acc3
@pytest.mark.parametrize("slug", GATE_FIXTURES)
def test_23_gate_caption_refs(cleanedproj: Proj, slug: str) -> None:
    g = gt(slug)
    by_index = {b["index"]: b for b in g["blocks"]}
    blocks = cleanedproj.blocks(slug)
    att = attachments(cleanedproj.attach(slug))
    want = hits = 0
    for f in g["figures"]:
        for idx in f["referenced_by"]:
            want += 1
            refs = referencing_blocks(by_index[idx], blocks, str(f["number"]))
            assert refs, (slug, f["expected_id"], idx)
            fid = f["expected_id"]
            sc = sidecar(cleanedproj, slug, fid)
            for b in refs:
                art = article_of(cleanedproj, slug, b.id)
                a = att.get((art, fid))
                assert a is not None and a.rule == AttachRule.caption_ref, (slug, fid, b.id, art)
                assert a.confidence == 1.0
                assert art in sc.articles
            assert sc.attach_rule == AttachRule.caption_ref
            hits += 1
    print(f"\n{slug}: caption_ref {hits}/{want} GT references")
    print(f"ATTACH ok {hits}/{want} ({slug})")  # SPEC 11.3 evidence
    assert hits == want
    assert want == {"clean": 3, "twocol": 3, "figures": 12, "scanned": 3, "manual": 2}[slug]


# -- 24 specific figures ---------------------------------------------------------------------


def test_24_figures_and_clean_specifics(cleanedproj: Proj) -> None:
    assert (
        sidecar(cleanedproj, "figures", "FIG-figures-p005-02").attach_rule != AttachRule.caption_ref
    )
    assert (
        sidecar(cleanedproj, "figures", "FIG-figures-p003-01").attach_rule == AttachRule.proximity
    )
    att = attachments(cleanedproj.attach("clean"))
    ref_art = article_of(cleanedproj, "clean", "b-clean-p006-03")
    blocks = {b.figure_id: b for b in cleanedproj.blocks("clean") if b.figure_id}
    for fid in ("FIG-clean-p005-01", "FIG-clean-p006-01", "FIG-clean-p006-02"):
        own = article_of(cleanedproj, "clean", blocks[fid].id)
        assert own != ref_art
        assert att[(ref_art, fid)].rule == AttachRule.caption_ref
        assert att[(ref_art, fid)].anchor_block_id == "b-clean-p006-03"
        assert att[(own, fid)].rule == AttachRule.proximity
        assert sorted(sidecar(cleanedproj, "clean", fid).articles) == sorted([ref_art, own])


# -- 25 caption_match (synthetic) -----------------------------------------------------------

CAP = "Figure 1. Gearbox housing bolt sequence."


def _doc(p1_text: str, *, p2_text: str = "Unrelated text here.", cap: str = CAP) -> tuple[Any, ...]:
    h = mk(1, 1, "1 Gearbox", BlockType.heading)
    p1 = mk(1, 2, p1_text)
    f = mk(1, 3, "", BlockType.figure)
    c = mk(1, 4, cap, BlockType.caption)
    p2 = mk(1, 5, p2_text)
    h2 = mk(2, 1, "2 Other", BlockType.heading)
    p3 = mk(2, 2, "Tighten the gearbox housing bolt in sequence.")
    blocks = [h, p1, f, c, p2, h2, p3]
    gf = gf_of(
        [[h.id, p1.id, f.id, c.id, p2.id], [h2.id, p3.id]],
        [("a", [p1.id, p3.id]), ("b", [h.id, f.id, c.id, h2.id]), ("c", [p2.id])],
    )
    info = [FigureInfo(str(f.figure_id), f.id, cap, False)]
    return blocks, gf, info, f


def _att(blocks: Any, gf: Any, info: Any, sel: set[str] | None = None, **kw: Any) -> AttachFile:
    sel = {b.id for b in blocks} if sel is None else sel
    return attach_document(
        "doc", blocks, gf, sel, kw.pop("split", ArticleSplit.per_topic), info, **kw
    )


def test_25_caption_match() -> None:
    blocks, gf, info, f = _doc("Check the gearbox housing bolt torque.")  # 3/4 = 0.75
    att = attachments(_att(blocks, gf, info))
    m = att[("doc--a", f.figure_id)]
    assert m.rule == AttachRule.caption_match and m.confidence == 0.9
    assert m.anchor_block_id == "b-doc-p001-02" and m.evidence.tokens == [
        "bolt",
        "gearbox",
        "housing",
    ]
    assert att[("doc--b", f.figure_id)].rule == AttachRule.proximity
    # 2/4 = 0.5: proximity only
    blocks, gf, info, f = _doc("Check the gearbox housing.")
    assert {k: v.rule for k, v in attachments(_att(blocks, gf, info)).items()} == {
        ("doc--b", f.figure_id): AttachRule.proximity
    }
    # |C| = 1: never a match
    blocks, gf, info, f = _doc("Gearbox gearbox gearbox.", cap="Figure 1. Gearbox.")
    assert len(attachments(_att(blocks, gf, info))) == 1
    # only another section matches (p3 is in section 2): none
    blocks, gf, info, f = _doc("Nothing relevant.")
    assert len(attachments(_att(blocks, gf, info))) == 1


def test_25_tie_goes_to_the_nearest_block() -> None:
    text = "Check the gearbox housing bolt torque."
    blocks, gf, info, f = _doc(text, p2_text=text)  # p1 (n=2) and p2 (n=5) tie; f is n=3
    att = attachments(_att(blocks, gf, info))
    assert att[("doc--a", f.figure_id)].rule == AttachRule.caption_match
    assert ("doc--c", f.figure_id) not in att
    far = {"b-doc-p001-02": 900}  # p1 moves away from the figure: p2 is now nearest
    blocks = [
        b.model_copy(update={"reading_order": far.get(b.id, b.reading_order)}) for b in blocks
    ]
    att = attachments(_att(blocks, gf, info))
    assert att[("doc--c", f.figure_id)].rule == AttachRule.caption_match


# -- 26 selection ---------------------------------------------------------------------------


def _refdoc() -> tuple[Any, ...]:
    p1 = mk(1, 1, "The pump is shown (see Figure 1).")
    f1 = mk(1, 2, "", BlockType.figure)
    c1 = mk(1, 3, "Figure 1. Pump.", BlockType.caption)
    f2 = mk(2, 1, "", BlockType.figure)
    c2 = mk(2, 2, "Figure 2. Valve.", BlockType.caption)
    f3 = mk(2, 3, "", BlockType.figure)
    blocks = [p1, f1, c1, f2, c2, f3]
    gf = gf_of(
        [[b.id for b in blocks]], [("a", [p1.id]), ("b", [f1.id, c1.id, f2.id, c2.id, f3.id])]
    )
    info = [
        FigureInfo(str(f1.figure_id), f1.id, "Figure 1. Pump.", False),
        FigureInfo(str(f2.figure_id), f2.id, "Figure 2. Valve.", False),
        FigureInfo(str(f3.figure_id), f3.id, None, True),
    ]
    return blocks, gf, info


def test_26_selection() -> None:
    blocks, gf, info = _refdoc()
    af = _att(blocks, gf, info, sel={"b-doc-p001-01"})
    att = attachments(af)
    assert {k: v.rule for k, v in att.items()} == {
        ("doc--a", "FIG-doc-p001-02"): AttachRule.caption_ref
    }
    un = {u.figure_id: u.reason for u in af.unattached}
    assert un == {"FIG-doc-p002-01": "not_selected", "FIG-doc-p002-03": "extraction_failed"}
    # per_document: one article, strongest rule per figure
    af = _att(blocks, gf, info, split=ArticleSplit.per_document)
    proj = figure_projection(af)
    assert [a.article_id for a in af.articles] == ["doc"]
    assert proj["FIG-doc-p001-02"] == (["doc"], AttachRule.caption_ref)
    assert proj["FIG-doc-p002-01"] == (["doc"], AttachRule.proximity)


# -- 27 ambiguous numbers --------------------------------------------------------------------


def test_27_ambiguous_numbers() -> None:
    s1 = [
        mk(1, 1, "See Figure 1 here."),
        mk(1, 2, "", BlockType.figure),
        mk(1, 3, "Figure 1. A.", BlockType.caption),
    ]
    s2 = [
        mk(2, 1, "See Figure 1 there."),
        mk(2, 2, "", BlockType.figure),
        mk(2, 3, "Figure 1. B.", BlockType.caption),
    ]
    s3 = [mk(3, 1, "Compare Figure 1 and Figure 99.")]
    blocks = [*s1, *s2, *s3]
    gf = gf_of(
        [[b.id for b in s1], [b.id for b in s2], [b.id for b in s3]],
        [("t", [b.id for b in blocks])],
    )
    info = [
        FigureInfo("FIG-doc-p001-02", "b-doc-p001-02", "Figure 1. A.", False),
        FigureInfo("FIG-doc-p002-02", "b-doc-p002-02", "Figure 1. B.", False),
    ]
    af = _att(blocks, gf, info)
    a = attachments(af)
    assert a[("doc--t", "FIG-doc-p001-02")].anchor_block_id == "b-doc-p001-01"
    assert a[("doc--t", "FIG-doc-p002-02")].anchor_block_id == "b-doc-p002-01"
    assert [(u.block_id, u.ref, u.reason) for u in af.unresolved_refs] == [
        ("b-doc-p003-01", "1", "ambiguous_number"),
        ("b-doc-p003-01", "99", "no_such_figure"),
    ]


# -- 28 overrides ---------------------------------------------------------------------------


def _write_overrides(paths: ProjectPaths, slug: str, ovs: list[AttachOverride]) -> None:
    write_json(paths.doc(slug).attach_overrides, ovs)


def test_28_overrides(grouped_copy: ProjectPaths, collect: Any) -> None:
    p = grouped_copy
    failed, _ = collect(p, only="figures")
    assert failed == []
    af = read_json(p.doc("figures").attach, AttachFile)
    arts = [a.article_id for a in af.articles]
    fid = "FIG-figures-p005-02"
    have = {x.article_id for x in af.articles if any(f.figure_id == fid for f in x.figures)}
    target = next(a for a in arts if a not in have)
    drop = next(
        x.article_id
        for x in af.articles
        if any(f.figure_id == "FIG-figures-p001-01" for f in x.figures)
    )
    _write_overrides(
        p,
        "figures",
        [
            AttachOverride(seq=1, op="attach", figure_id=fid, article_id=target),
            AttachOverride(seq=2, op="detach", figure_id="FIG-figures-p001-01", article_id=drop),
            AttachOverride(seq=3, op="attach", figure_id=fid, article_id="figures--no-such-topic"),
        ],
    )
    for force in (False, True):
        failed, lines = collect(p, only="figures", force=force)
        assert failed == []
        af = read_json(p.doc("figures").attach, AttachFile)
        a = attachments(af)
        assert a[(target, fid)].rule == AttachRule.human and a[(target, fid)].confidence == 1.0
        assert (drop, "FIG-figures-p001-01") not in a
        assert af.overrides_applied == 2 and af.overrides_stale == [3]
        rec = read_json(p.figure_file("figures", fid, "json"), FigureRecord)
        assert rec.attach_rule == AttachRule.human and target in rec.articles
        assert (
            drop
            not in read_json(
                p.figure_file("figures", "FIG-figures-p001-01", "json"), FigureRecord
            ).articles
        )
        stage = {x["stage"]: x for x in lines}
        assert stage["attach"]["overrides_stale"] == 1


# -- 29 sidecar projection, caption_original, figures --force --------------------------------


def test_29_sidecars(cleanedproj: Proj, groupedproj: Proj, tmp_path: Path) -> None:
    for slug in cleanedproj.paths.list_slugs():
        proj = figure_projection(cleanedproj.attach(slug))
        for b in cleanedproj.blocks(slug):
            if b.figure_id is None:
                continue
            p = cleanedproj.paths.figure_file(slug, b.figure_id, "json")
            if not p.is_file():
                continue
            rec = read_json(p, FigureRecord)
            before = read_json(
                groupedproj.paths.figure_file(slug, b.figure_id, "json"), FigureRecord
            )
            assert rec.caption_original == before.caption_original
            arts, rule = proj.get(b.figure_id, ([], AttachRule.none))
            assert rec.articles == arts and rec.attach_rule == rule
            sig = {s.name: s for s in b.signals}
            assert SignalName.figure_attach_rule in sig, b.id
    root = tmp_path / "p"
    copy_project(cleanedproj.paths.root, root)
    paths = ProjectPaths(root)
    before = {
        f.name: json.loads(f.read_text()) for f in sorted((root / "figures").rglob("FIG-*.json"))
    }
    assert run_figures(paths, force=True, emit=quiet) == []
    assert run_score(paths, emit=quiet) == []
    after = {
        f.name: json.loads(f.read_text()) for f in sorted((root / "figures").rglob("FIG-*.json"))
    }
    assert before == after


# -- 30 manual.docx -------------------------------------------------------------------------


def test_30_manual(cleanedproj: Proj) -> None:
    att = attachments(cleanedproj.attach("manual"))
    for fid, ref in (
        ("FIG-manual-p001-01", "b-manual-p001-04"),
        ("FIG-manual-p002-01", "b-manual-p002-02"),
    ):
        art = article_of(cleanedproj, "manual", ref)
        assert att[(art, fid)].rule == AttachRule.caption_ref
        assert att[(art, fid)].anchor_block_id == ref
        rec = sidecar(cleanedproj, "manual", fid)
        assert rec.description_generated is not None and rec.description_generated.startswith(
            "Generated description (mock) of image "
        )
        assert rec.tags == ["figure", "mock"]


def test_scored_blocks_carry_the_attach_signal(cleanedproj: Proj) -> None:
    for b in load_scored_blocks(cleanedproj.paths, "figures"):
        if b.type == BlockType.figure:
            sig = {s.name: s for s in b.signals}[SignalName.figure_attach_rule]
            assert sig.value in (1.0, 0.9, 0.6)
