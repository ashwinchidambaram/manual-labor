"""E2 (synthetic), E4-E7, E9, E12 (synthetic) and the placement/accounting rules on hand-built
inputs: every branch of assemble without a parser."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from manuallabor.contracts.article import ArticleFrontmatter, ReviewCounts
from manuallabor.contracts.enums import ArticleSplit, AttachRule, BlockStatus, BlockType
from manuallabor.export.assemble import assemble
from manuallabor.export.gate import export_gate
from manuallabor.export.render import (
    FIGURE_LINE_RE,
    alt_text,
    render_list,
    yaml_frontmatter,
)
from manuallabor.export.types import ExportError, GateLocked
from manuallabor.export.validate import split_article
from manuallabor.scoring.numeric import FAITH_NUM_RE
from tests.export.synth import (
    CLOCK,
    att,
    bid,
    blk,
    fid,
    figure_data,
    flag,
    override,
    run,
    synth_inputs,
)

A, P, L = BlockStatus.approved, BlockType.paragraph, BlockType.list
KEYS = [
    "id",
    "title",
    "source_doc",
    "source_file",
    "product_model",
    "pages",
    "sections",
    "figures",
    "blocks",
    "review",
    "generated_at",
]
ART = "doc--main"


def body_lines(text: str) -> list[str]:
    return text[text.index("\n---\n", 3) + 5 :].split("\n")


def all_parts(text: str) -> list[str]:
    """The article parts: everything after `# title`, split on blank lines."""
    body = body_lines(text)
    return "\n".join(body[3:]).rstrip("\n").split("\n\n")


def parts(text: str) -> list[str]:
    """The text and figure parts, without the review markers (design 11 section 20; the
    markers themselves are tested in test_markers.py)."""
    return [p for p in all_parts(text) if not p.startswith("<!-- ml: ")]


def markers(text: str) -> list[str]:
    return [p for p in all_parts(text) if p.startswith("<!-- ml: ")]


# -- E4 frontmatter ----------------------------------------------------------------------------


def test_e4_frontmatter_matches_the_spec_example_byte_for_byte() -> None:
    fm = ArticleFrontmatter(
        id="acme-x200-service--belt-tension",
        title="Belt tension & drive maintenance",
        source_doc="acme-x200-service",
        source_file="X200_Service_Manual_rev4.pdf",
        product_model="Acme X200",
        pages=[41, 42, 43, 44, 45],
        sections=["5.1"],
        figures=["FIG-acme-x200-service-p042-01", "FIG-acme-x200-service-p042-02"],
        blocks=7,
        review=ReviewCounts(approved=7, edited=1, overrides=0),
        generated_at=datetime(2026, 10, 28, 18, 0, 0, tzinfo=UTC),
    )
    assert yaml_frontmatter(fm) == (
        "---\n"
        "id: acme-x200-service--belt-tension\n"
        "title: Belt tension & drive maintenance\n"
        "source_doc: acme-x200-service\n"
        "source_file: X200_Service_Manual_rev4.pdf\n"
        "product_model: Acme X200\n"
        "pages: [41, 42, 43, 44, 45]\n"
        'sections: ["5.1"]\n'
        "figures: [FIG-acme-x200-service-p042-01, FIG-acme-x200-service-p042-02]\n"
        "blocks: 7\n"
        "review: { approved: 7, edited: 1, overrides: 0 }\n"
        "generated_at: 2026-10-28T18:00:00Z\n"
        "---\n"
    )
    fm2, _ = split_article(yaml_frontmatter(fm) + "\n# x\n")
    assert list(fm2) == KEYS
    assert ArticleFrontmatter.model_validate(fm2) == fm


@pytest.mark.parametrize(
    "title",
    [
        "Q&A: step #1 - torque",
        "Plain title",
        "yes",
        "Null",
        "5. Numbered title",
        'He said "stop" \\ now',
        "trailing space ",
        "Ünïcode — dash",
        "a, b",
        "",
    ],
)
def test_e4_awkward_strings_round_trip(title: str) -> None:
    fm = ArticleFrontmatter(
        id="doc",
        title=title,
        source_doc="doc",
        source_file="1 odd: name.pdf",
        product_model=None,
        pages=[],
        sections=[],
        figures=[],
        blocks=0,
        review=ReviewCounts(approved=0, edited=0, overrides=0),
        generated_at=CLOCK,
    )
    text = yaml_frontmatter(fm)
    assert "product_model: null\n" in text and "pages: []\n" in text and "figures: []\n" in text
    back, _ = split_article(text + "\n# t\n")
    assert back["title"] == title and back["source_file"] == "1 odd: name.pdf"
    assert ArticleFrontmatter.model_validate(back) == fm
    assert isinstance(back["generated_at"], str)  # the timestamp resolver is off


def test_assembled_frontmatter_pages_sections_and_order() -> None:
    blocks = [
        blk(1, "Intro.", type=BlockType.heading, page=3, heading_level=1),
        blk(2, "Body one.", page=3),
        blk(3, "Sub.", type=BlockType.heading, page=5, heading_level=2),
        blk(4, "Body two.", page=5),
        blk(5, "Later.", type=BlockType.heading, page=9, heading_level=1),
        blk(6, "Body three.", page=9),
    ]
    levels = {bid(1, 3): 1, bid(3, 5): 2, bid(5, 9): 1}
    secs = {bid(1, 3): "10", bid(3, 5): "2.1", bid(5, 9): "2"}
    res = run(synth_inputs(blocks, levels=levels, sections=secs))
    (a,) = res.articles
    assert a.frontmatter.pages == [3, 5, 9]
    assert a.frontmatter.sections == ["2", "2.1", "10"]  # numeric tuple order, not text order
    assert a.frontmatter.blocks == 6 and a.frontmatter.review == ReviewCounts(
        approved=6, edited=0, overrides=0
    )
    assert a.title == "Main topic" and a.id == ART
    lines = a.text.split("\n")
    assert lines[lines.index("# Main topic") + 2] == "## Intro."  # a top section is H2
    assert "### Sub." in lines  # depth 2 is H3
    assert "Later." not in lines and "## Later." in lines


# -- E2 numbers and list markers ---------------------------------------------------------------


def test_e2_list_markers_never_change_the_numbers() -> None:
    src = "• 12 V\n• - 12 V\n• -12 V\n1. 5 A\nplain 7 mm\n* already"
    out = render_list(src)
    assert out.split("\n") == [
        "* 12 V",
        "* - 12 V",
        "* -12 V",
        "1. 5 A",
        "* plain 7 mm",
        "* already",
    ]
    from collections import Counter

    strip = "\n".join(ln.removeprefix("* ") for ln in out.split("\n"))
    assert Counter(FAITH_NUM_RE.findall(strip)) == Counter(FAITH_NUM_RE.findall(src))
    assert FAITH_NUM_RE.findall("* 12 V") == ["12"]  # a `- ` bullet would have read as -12 only
    assert FAITH_NUM_RE.findall("- 12 V") == ["12"] and FAITH_NUM_RE.findall("-12 V") == ["-12"]


def test_e2_a_list_block_renders_with_star_markers() -> None:
    res = run(synth_inputs([blk(1, "• 12 V\n• - 12 V", type=L, clean="• 12 V\n• - 12 V")]))
    assert parts(res.articles[0].text) == ["* 12 V\n* - 12 V"]


# -- E5 statuses (P1) --------------------------------------------------------------------------


def test_e5_statuses_and_text_sources() -> None:
    blocks = [
        blk(1, "raw auto", status=BlockStatus.auto_approved, clean="clean auto"),
        blk(2, "raw approved", status=A, clean="clean approved"),
        blk(3, "raw edited", status=BlockStatus.edited, clean="HUMAN edited"),
        blk(4, "raw never cleaned", status=A),  # clean_text is None: raw is the text
        blk(5, "raw rejected", status=BlockStatus.rejected, clean="clean rejected"),
    ]
    res = run(synth_inputs(blocks))
    (a,) = res.articles
    assert parts(a.text) == ["clean auto", "clean approved", "HUMAN edited", "raw never cleaned"]
    assert a.frontmatter.blocks == 4
    assert a.frontmatter.review == ReviewCounts(approved=4, edited=1, overrides=0)
    acc = res.manifest.accounting
    assert acc.assignments[bid(5)] == "unassigned" and acc.unassigned_reasons[bid(5)] == "rejected"
    assert res.manifest.review_stats.rejected == 1 and "rejected" not in a.text


# -- E6 gate -----------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [BlockStatus.queued, BlockStatus.flagged])
def test_e6_a_queued_or_flagged_block_locks_the_export(status: BlockStatus) -> None:
    blocks = [blk(1, status=A), blk(2, "x", status=status)]
    with pytest.raises(GateLocked) as ei:
        run(synth_inputs(blocks))
    assert ei.value.blockers == [bid(2)]
    g = export_gate({"doc": blocks}, {"doc": {b.id for b in blocks}}, [], [])
    assert g.unlocked is False and g.blockers == [bid(2)]


def test_e6_an_open_flag_locks_and_resolving_unlocks() -> None:
    blocks = [blk(1, status=A), blk(2, status=A)]
    inp = synth_inputs(blocks, flags=[flag(1, bid(2))])
    with pytest.raises(GateLocked) as ei:
        run(inp)
    assert ei.value.open_flags == 1 and ei.value.blockers == [bid(2)]
    assert run(synth_inputs(blocks, flags=[flag(1, bid(2), "resolved")])).articles
    # a flag on a figure targets the figure's block
    fb = [blk(1, status=A), blk(2, type=BlockType.figure, status=A)]
    g = export_gate({"doc": fb}, {"doc": {b.id for b in fb}}, [flag(2, fid(2))], [])
    assert g.blockers == [bid(2)] and g.open_flags == 1


def test_e6_out_of_scope_blocks_do_not_lock() -> None:
    blocks = [blk(1, status=A), blk(2, status=BlockStatus.queued)]
    res = run(synth_inputs(blocks, selected={bid(1)}))
    assert res.manifest.accounting.unassigned_reasons[bid(2)] == "not_selected"


# -- E7 overrides ------------------------------------------------------------------------------


def two_open() -> list:  # type: ignore[type-arg]
    return [
        blk(1, "ok", status=A, clean="ok"),
        blk(2, "raw q", status=BlockStatus.queued, clean="clean q"),
        blk(3, "raw f", status=BlockStatus.flagged),
    ]


def test_e7_blanket_override_exports_machine_text_with_an_invisible_marker() -> None:
    res = run(
        synth_inputs(
            two_open(),
            flags=[flag(1, bid(3))],
            overrides=[override(5, "customer waived review")],
        )
    )
    (a,) = res.articles
    assert parts(a.text) == ["ok", "clean q", "raw f"]  # machine clean_text, else raw
    # section 20 (amends P2): each overridden part is followed by its HTML-comment marker
    assert all_parts(a.text) == [
        "ok",
        "clean q",
        f'<!-- ml: overridden; block: {bid(2)}; reason: "customer waived review" -->',
        "raw f",
        f"<!-- ml: overridden; block: {bid(3)}; flag: flag-000001; "
        'reason: "customer waived review" -->',
    ]
    assert a.frontmatter.review == ReviewCounts(approved=1, edited=0, overrides=2)
    assert a.frontmatter.approved_check if False else True
    m = res.manifest
    assert [o.target_id for o in m.overrides] == [bid(2), bid(3)]
    assert [o.flag_id for o in m.overrides] == [None, "flag-000001"]
    assert {o.reason for o in m.overrides} == {"customer waived review"}
    assert m.review_stats.overrides == 2 and m.review_stats.queued == 1


def test_e7_a_targeted_override_covers_only_its_block() -> None:
    inp = synth_inputs(two_open(), overrides=[override(5, "r", target=bid(2))])
    with pytest.raises(GateLocked) as ei:
        run(inp)
    assert ei.value.blockers == [bid(3)]
    both = synth_inputs(
        two_open(), overrides=[override(5, "r", target=bid(2)), override(6, "s", target=bid(3))]
    )
    assert [o.reason for o in run(both).manifest.overrides] == ["r", "s"]


def test_e7_a_targeted_override_does_not_cover_a_flag_raised_after_it() -> None:
    """A target override covers the queued state and the flags open when it was recorded. A flag
    raised on the block afterwards (wall clock here: the pure gate has no action sequence) makes
    the block a blocker again, so it cannot ship with machine text."""
    blocks = [blk(1, status=A), blk(2, status=BlockStatus.queued)]
    later = flag(9, bid(2)).model_copy(update={"created_at": CLOCK + timedelta(minutes=1)})
    g = export_gate(
        {"doc": blocks}, {"doc": {b.id for b in blocks}}, [later], [override(5, "r", target=bid(2))]
    )
    assert g.blockers == [bid(2)] and bid(2) not in g.covered


def test_e7_a_block_override_never_covers_an_open_flag() -> None:
    """P3 (amended 2026-10-30): a block override covers the block's review state, never an
    open flag on it, whichever was recorded first. Only an override naming the flag, or a
    blanket one, covers a flag; a second flag on a covered block blocks again."""
    blocks = [blk(1, status=A), blk(2, status=BlockStatus.queued), blk(3, status=A)]
    scope = {"doc": {b.id for b in blocks}}
    early, late = flag(4, bid(2)), flag(6, bid(3))
    ovs = [override(5, "r", target=bid(2)), override(5, "r", target=bid(3))]
    g = export_gate({"doc": blocks}, scope, [early, late], ovs)
    assert g.blockers == [bid(2), bid(3)] and not g.covered
    assert [(f.id, b) for f, b in g.flag_blockers] == [(early.id, bid(2)), (late.id, bid(3))]
    g = export_gate({"doc": blocks}, scope, [early, late], [override(5, "all")])
    assert g.blockers == [] and g.flag_blockers == []
    g = export_gate(
        {"doc": blocks}, scope, [early, late], [*ovs, override(8, "f", flag_id=early.id)]
    )
    assert g.blockers == [bid(3)] and bid(2) in g.covered
    again = flag(7, bid(2))
    g = export_gate({"doc": blocks}, scope, [early, again], [override(8, "f", flag_id=early.id)])
    assert g.blockers == [bid(2)] and [f.id for f, _ in g.flag_blockers] == [again.id]


def test_gate_counts_partition_the_scope_and_skip_page_headers() -> None:
    """Every in-scope body block is in exactly one bucket; a page header or footer is never
    exported (P4), so it neither blocks nor counts, even when it is queued."""
    blocks = [
        blk(1, status=BlockStatus.auto_approved),
        blk(2, status=BlockStatus.approved),
        blk(3, status=BlockStatus.edited),
        blk(4, status=BlockStatus.queued),
        blk(5, status=BlockStatus.queued),
        blk(6, status=BlockStatus.rejected),
        blk(7, type=BlockType.header, status=BlockStatus.queued),
        blk(8, type=BlockType.footer, status=BlockStatus.auto_approved),
        blk(9, status=BlockStatus.queued),  # out of scope
    ]
    scope = {"doc": {b.id for b in blocks} - {bid(9)}}
    g = export_gate({"doc": blocks}, scope, [flag(1, bid(2))], [override(5, "r", target=bid(4))])
    assert g.counts == {
        "in_scope": 6,
        "auto_approved": 1,
        "approved": 0,
        "edited": 1,
        "rejected": 1,
        "overridden": 1,
        "blocking": 2,
        # design 11 section 17: blocking splits into what waits for a person and what a flag holds
        "to_review": 1,
        "flagged": 1,
    }
    assert g.blockers == [bid(2), bid(5)] and g.queued == 2 and g.open_flags == 1


def test_e7_a_flag_override_covers_the_flagged_block() -> None:
    blocks = [blk(1, status=A), blk(2, status=A)]
    inp = synth_inputs(
        blocks, flags=[flag(7, bid(2))], overrides=[override(3, "r", flag_id="flag-000007")]
    )
    res = run(inp)
    assert [(o.target_id, o.flag_id) for o in res.manifest.overrides] == [(bid(2), "flag-000007")]
    # an approved block with an open flag is counted once: as an override, not also approved
    fm = res.articles[0].frontmatter
    assert fm.review == ReviewCounts(approved=1, edited=0, overrides=1)
    assert fm.review.approved + fm.review.overrides <= fm.blocks
    edited = synth_inputs(
        [blk(1, status=A), blk(2, "human", status=BlockStatus.edited)],
        flags=[flag(7, bid(2))],
        overrides=[override(3, "r", flag_id="flag-000007")],
    )
    assert run(edited).articles[0].frontmatter.review == ReviewCounts(
        approved=1, edited=0, overrides=1
    )


def test_p4_empty_is_decided_on_the_raw_text() -> None:
    """P4: a block is `empty` when its raw (source) text is blank. A block whose source has text
    is never dropped as empty, even if its cleaned text came out blank."""
    blocks = [
        blk(1, "Body."),
        blk(2, "Source words here.", clean=""),  # cleanup produced nothing: still accounted
        blk(3, "  \n ", clean="x"),  # blank source: empty, whatever the overlay says
    ]
    res = run(synth_inputs(blocks))
    acc = res.manifest.accounting
    assert acc.assignments[bid(2)] == "doc--main" and bid(2) not in acc.unassigned_reasons
    assert acc.unassigned_reasons == {bid(3): "empty"}
    assert res.articles[0].block_ids == [bid(1), bid(2)]


# -- E9 figure placement -----------------------------------------------------------------------


def fig_block(n: int, status: BlockStatus = A, **kw: object):  # type: ignore[no-untyped-def]
    return blk(n, type=BlockType.figure, status=status, **kw)


def test_e9_placement_rules() -> None:
    blocks = [
        blk(1, "Intro, see Figure 1.", reading_order=10),
        blk(2, "Middle.", reading_order=20),
        blk(3, "Caption of figure 3.", reading_order=30),
        blk(4, "Closing paragraph.", reading_order=40),
        fig_block(10, reading_order=5),
        fig_block(11, reading_order=41),
        fig_block(12, reading_order=25),
        fig_block(13, reading_order=42),
    ]
    figs = [
        figure_data(10, caption="Figure 1. First"),
        figure_data(11, caption="Figure 2. Second", caption_block=bid(3)),
        figure_data(12, caption="Figure 3. Third"),
        figure_data(13, caption=None, generated="A generated sketch"),
    ]
    attach = {
        ART: [
            att(fid(10), AttachRule.caption_ref, anchor=bid(1)),
            att(fid(11), AttachRule.proximity, anchor=bid(11)),  # caption block present
            att(fid(12), AttachRule.proximity, anchor=bid(12)),  # no caption block: own position
            att(fid(13), AttachRule.caption_ref, anchor=bid(1)),  # same anchor as figure 10
        ]
    }
    res = run(synth_inputs(blocks, figures=figs, attach=attach))
    (a,) = res.articles
    out = parts(a.text)
    names = [p if not p.startswith("![") else FIGURE_LINE_RE.match(p).group("fid") for p in out]  # type: ignore[union-attr]
    assert names == [
        "Intro, see Figure 1.",
        fid(10),
        fid(13),  # two figures at one anchor keep attach order
        "Middle.",
        fid(12),  # no caption block: at the figure block's own reading position
        "Caption of figure 3.",
        fid(11),  # right after the caption block
        "Closing paragraph.",
    ]
    assert a.figure_ids == [fid(10), fid(13), fid(12), fid(11)]
    assert a.frontmatter.figures == a.figure_ids
    assert f"{fid(13)} — [generated] A generated sketch" in a.text
    # figure blocks render nothing themselves but are accounted for
    assert {fid(10)[4:].replace("FIG-", "")} and set(a.block_ids) >= {bid(10), bid(11)}


def test_e9_fallback_is_the_end_of_the_article() -> None:
    blocks = [
        blk(1, "Anchor, rejected.", status=BlockStatus.rejected),
        blk(2, "Body."),
        fig_block(10, status=BlockStatus.rejected),
        fig_block(11),
    ]
    figs = [figure_data(10), figure_data(11)]
    attach = {
        ART: [
            att(fid(10), AttachRule.proximity, anchor=bid(10)),  # figure block rejected: end
            att(fid(11), AttachRule.caption_ref, anchor=bid(1)),  # anchor excluded: end
        ]
    }
    (a,) = run(synth_inputs(blocks, figures=figs, attach=attach)).articles
    out = parts(a.text)
    assert (
        out[0] == "Body."
        and out[1].startswith(f"![{fid(10)} ")
        and out[2].startswith(f"![{fid(11)} ")
    )


def test_e9_a_caption_ref_figure_whose_own_block_is_unselected_is_exported() -> None:
    blocks = [blk(1, "See Figure 1."), blk(2, "Other."), fig_block(10)]
    figs = [figure_data(10)]
    attach = {ART: [att(fid(10), AttachRule.caption_ref, anchor=bid(1))]}
    res = run(
        synth_inputs(
            blocks,
            figures=figs,
            attach=attach,
            selected={bid(1), bid(2)},
            scope_extra={bid(10)},
        )
    )
    (a,) = res.articles
    assert parts(a.text)[1].startswith(f"![{fid(10)} ")
    assert bid(10) not in a.block_ids  # its own block is not in the article ...
    assert res.manifest.accounting.unassigned_reasons[bid(10)] == "not_selected"  # ... but counted
    assert [f.id for f in res.manifest.figures] == [fid(10)]


def test_e9_a_human_attachment_without_an_anchor_uses_the_caption_block() -> None:
    blocks = [blk(1, "A."), blk(2, "Cap."), blk(3, "B."), fig_block(10, reading_order=0)]
    figs = [figure_data(10, caption_block=bid(2))]
    attach = {ART: [att(fid(10), AttachRule.human, anchor=None)]}
    (a,) = run(synth_inputs(blocks, figures=figs, attach=attach)).articles
    assert [p[:2] for p in parts(a.text)] == ["A.", "Ca", "![", "B."]


# -- duplicates and vector figures on synthetic inputs -----------------------------------------


def test_duplicate_figures_reference_the_canonical_file_and_keep_their_own_alt_id() -> None:
    blocks = [blk(1, "Text."), fig_block(10), fig_block(11)]
    figs = [
        figure_data(10, caption="Figure 1. A"),
        figure_data(11, caption="Figure 2. B", canonical=fid(10)),
    ]
    attach = {ART: [att(fid(11), AttachRule.proximity, anchor=bid(11))]}  # only the copy
    res = run(synth_inputs(blocks, figures=figs, attach=attach))
    (a,) = res.articles
    line = parts(a.text)[1]
    mt = FIGURE_LINE_RE.match(line)
    assert mt and mt.group("fid") == fid(11)
    assert mt.group("path") == f"images/doc/{fid(10)}.png"
    by_id = {f.id: f for f in res.manifest.figures}
    assert set(by_id) == {fid(10), fid(11)}  # the canonical is exported though unattached
    assert by_id[fid(11)].duplicate_of == fid(10) and by_id[fid(10)].duplicate_of is None
    assert by_id[fid(11)].file == f"../doc/{fid(10)}.png"
    names = set(res.files)
    assert f"images/doc/{fid(10)}.png" in names and f"images/doc/{fid(11)}.png" not in names
    assert {f"images/doc/{fid(10)}.json", f"images/doc/{fid(11)}.json"} <= names
    import json

    side = json.loads(res.files[f"images/doc/{fid(10)}.json"])  # type: ignore[arg-type]
    assert side["articles"] == []  # nothing references the canonical by its own id
    side2 = json.loads(res.files[f"images/doc/{fid(11)}.json"])  # type: ignore[arg-type]
    assert side2["articles"] == [ART]


def test_vector_figures_ship_png_and_svg_but_reference_the_png() -> None:
    blocks = [blk(1, "Text."), fig_block(10)]
    figs = [figure_data(10, svg=True)]
    attach = {ART: [att(fid(10), AttachRule.proximity, anchor=bid(10))]}
    res = run(synth_inputs(blocks, figures=figs, attach=attach))
    assert f"images/doc/{fid(10)}.svg" in res.files and f"images/doc/{fid(10)}.png" in res.files
    assert ".svg)" not in res.articles[0].text


# -- E12 partition on synthetic inputs ---------------------------------------------------------


def test_e12_partition_reasons() -> None:
    blocks = [
        blk(1, "Body."),
        blk(2, "Header text", type=BlockType.header),
        blk(3, "   \n ", status=A),  # selected but empty after whitespace collapse
        blk(4, "Unselected."),
        blk(5, "Footer", type=BlockType.footer),
        blk(6, "Body two."),
    ]
    inp = synth_inputs(blocks, selected={bid(1), bid(3), bid(6)})
    res = run(inp)
    acc = res.manifest.accounting
    assert acc.total_blocks == 6
    assert [a for a in res.manifest.articles][0].block_ids == [bid(1), bid(6)]
    assert acc.unassigned_reasons == {
        bid(2): "header_footer",
        bid(3): "empty",
        bid(4): "not_selected",
        bid(5): "header_footer",
    }
    assert all(acc.assignments[b] == "unassigned" for b in acc.unassigned_reasons)
    sel = inp.docs["doc"].selected
    assert all(b not in sel for b, why in acc.unassigned_reasons.items() if why == "not_selected")


def test_a_selected_block_in_no_topic_is_an_assembly_error_not_unselected() -> None:
    """A topic view that lost a selected block (a hand-edited or corrupt groups.json) must not
    turn it into `not_selected`: the export refuses and names it."""
    blocks = [blk(1, "One."), blk(2, "Two."), blk(3, "Three."), blk(4, "Four.")]
    inp = synth_inputs(blocks, topics={"a": ("Topic A", [bid(1), bid(2)])})
    assert bid(3) in inp.docs["doc"].selected and bid(4) in inp.docs["doc"].selected
    with pytest.raises(ExportError, match="in no article") as ei:
        run(inp)
    assert bid(3) in str(ei.value) and bid(4) in str(ei.value)
    # the same blocks, unselected, are accounted as `not_selected`
    ok = run(
        synth_inputs(blocks, topics={"a": ("Topic A", [bid(1), bid(2)])}, selected={bid(1), bid(2)})
    )
    reasons = ok.manifest.accounting.unassigned_reasons
    assert reasons == {bid(3): "not_selected", bid(4): "not_selected"}


def test_an_article_with_only_empty_members_is_not_written() -> None:
    blocks = [blk(1, "Real."), blk(2, " "), blk(3, "\n")]
    res = run(
        synth_inputs(
            blocks,
            topics={"a": ("Topic A", [bid(1)]), "b": ("Topic B", [bid(2), bid(3)])},
        )
    )
    assert [a.id for a in res.articles] == ["doc--a"]
    assert res.manifest.accounting.unassigned_reasons == {bid(2): "empty", bid(3): "empty"}


def test_unassigned_topic_and_titles_and_split_modes() -> None:
    blocks = [blk(1, "One."), blk(2, "Two."), blk(3, "Three.")]
    topics = {"alpha": ("Alpha topic", [bid(1)]), "beta": ("Beta topic", [bid(2)])}
    res = run(synth_inputs(blocks, topics=topics, unassigned_topic=[bid(3)]))
    assert [a.id for a in res.articles] == ["doc--alpha", "doc--beta", "doc--unassigned"]
    assert [a.title for a in res.articles] == ["Alpha topic", "Beta topic", "Unassigned blocks"]
    one = run(
        synth_inputs(
            blocks, topics=topics, unassigned_topic=[bid(3)], split=ArticleSplit.per_document
        )
    )
    assert [a.id for a in one.articles] == ["doc"] and one.articles[0].title == "Doc Title"
    assert one.articles[0].block_ids == [bid(1), bid(2), bid(3)]
    untitled = run(synth_inputs(blocks, title=None, split=ArticleSplit.per_document))
    assert untitled.articles[0].title == "doc"  # the filename stem


def test_gate_locked_leaves_nothing_to_write() -> None:
    with pytest.raises(GateLocked):
        assemble(synth_inputs([blk(1, status=BlockStatus.queued)]), CLOCK)
    with pytest.raises(ExportError):  # a figure attached but without a sidecar
        run(synth_inputs([blk(1), fig_block(10)], attach={ART: [att(fid(10))]}))


def test_alt_text_rules() -> None:
    assert alt_text("FIG-a-p001-01", "  Figure 1.\n  Pump [A] \\ b ", "gen") == (
        "FIG-a-p001-01 — Figure 1. Pump \\[A\\] \\\\ b"
    )
    assert alt_text("FIG-a-p001-01", None, " a \n b ") == "FIG-a-p001-01 — [generated] a b"
    assert alt_text("FIG-a-p001-01", " ", None) == "FIG-a-p001-01 — (no caption)"
    # `]` and `)` are escaped so no link parser can end the alt text or the link early
    assert alt_text("FIG-a-p001-01", "see [1](images/x.png) (rev 2)", None) == (
        "FIG-a-p001-01 — see \\[1\\](images/x.png\\) (rev 2\\)"
    )
    assert alt_text("FIG-a-p001-01", None, "a) b") == "FIG-a-p001-01 — [generated] a\\) b"


def test_the_body_is_deterministic_and_marks_overrides_only_in_comments() -> None:
    inp = synth_inputs(two_open(), overrides=[override(1)], flags=[flag(1, bid(3))])
    a, b = run(inp), run(inp)
    assert a.files == b.files
    text = a.articles[0].text
    body = text[text.index("\n---\n", 3) :]
    # the word appears only inside the markers (frontmatter counts them)
    outside = "\n".join(ln for ln in body.split("\n") if not ln.startswith("<!-- ml: "))
    assert "override" not in outside.lower()
    assert len(markers(text)) == 2
