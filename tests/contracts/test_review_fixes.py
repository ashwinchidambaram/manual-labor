"""Tests added after the module 0 review: manifest accounting, figure files, article ids,
faithfulness readiness and previously untested validator branches."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from manuallabor import contracts as c
from tests.contracts.factories import (
    SLUG,
    TS,
    block_dict,
    document_dict,
    figure_dict,
    manifest_dict,
)

B1, B2, B3 = (f"b-{SLUG}-p001-0{i}" for i in (1, 2, 3))
FIG1 = f"FIG-{SLUG}-p001-01"
FIG2 = f"FIG-{SLUG}-p001-02"


def bad(model: type[BaseModel], data: dict[str, Any], match: str | None = None) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(data)


def mut(fn: Any) -> dict[str, Any]:
    d = manifest_dict()
    fn(d)
    return d


# -- manifest accounting (item 1) ------------------------------------------------------------
def test_m1_dropped_block_with_consistent_totals_fails() -> None:
    def drop(d: dict[str, Any]) -> None:
        d["accounting"]["assignments"].pop(B3)
        d["accounting"]["unassigned_reasons"].pop(B3)
        d["accounting"]["total_blocks"] = 2
        d["review_stats"]["total_blocks"] = 2
        d["review_stats"]["queued"] = 0

    bad(c.Manifest, mut(drop), "number of blocks in docs")


def test_m1_dropped_block_with_docs_also_edited_is_still_consistent() -> None:
    # Control: when parsing really produced only two blocks, the same manifest is valid.
    def two(d: dict[str, Any]) -> None:
        d["docs"][0]["block_ids"] = [B1, B2]
        d["accounting"]["assignments"].pop(B3)
        d["accounting"]["unassigned_reasons"].pop(B3)
        d["accounting"]["total_blocks"] = 2
        d["review_stats"]["total_blocks"] = 2
        d["review_stats"]["queued"] = 0

    c.Manifest.model_validate(mut(two))


def test_m2_block_assigned_twice_fails() -> None:
    def twice(d: dict[str, Any]) -> None:
        d["articles"].append(
            {**d["articles"][0], "id": f"{SLUG}--x", "path": f"articles/{SLUG}--x.md"}
        )

    bad(c.Manifest, mut(twice), "block_ids")

    def dup_in_article(d: dict[str, Any]) -> None:
        d["articles"][0]["block_ids"] = [B1, B1, B2]

    bad(c.Manifest, mut(dup_in_article), "duplicate block_ids|block_ids")


def test_m3_extra_block_not_in_docs_fails() -> None:
    ghost = f"b-{SLUG}-p001-04"

    def extra(d: dict[str, Any]) -> None:
        d["accounting"]["assignments"][ghost] = "unassigned"
        d["accounting"]["unassigned_reasons"][ghost] = "empty"
        d["accounting"]["total_blocks"] = 4
        d["review_stats"]["total_blocks"] = 4
        d["review_stats"]["queued"] = 2

    bad(c.Manifest, mut(extra), "number of blocks in docs")


def test_m3_same_count_but_different_block_fails() -> None:
    ghost = f"b-{SLUG}-p001-04"

    def swap(d: dict[str, Any]) -> None:
        d["accounting"]["assignments"].pop(B3)
        d["accounting"]["assignments"][ghost] = "unassigned"
        d["accounting"]["unassigned_reasons"].pop(B3)
        d["accounting"]["unassigned_reasons"][ghost] = "empty"

    bad(c.Manifest, mut(swap), "parsed blocks != assigned")


def test_m4_article_for_unknown_doc_fails() -> None:
    def unknown(d: dict[str, Any]) -> None:
        d["articles"][0]["source_doc"] = "ghost-doc"

    bad(c.Manifest, mut(unknown), "source_doc")


def test_m4_figure_for_unknown_doc_fails() -> None:
    def unknown(d: dict[str, Any]) -> None:
        d["figures"][0]["source_doc"] = "ghost-doc"
        d["figures"][0]["sidecar"] = f"images/ghost-doc/{FIG1}.json"

    bad(c.Manifest, mut(unknown), "source_doc")


def test_m5_status_counts_must_sum() -> None:
    bad(c.Manifest, mut(lambda d: d["review_stats"].update(queued=0)), "sum to total_blocks")


def test_m6_dangling_duplicate_of_fails() -> None:
    bad(
        c.Manifest,
        mut(lambda d: d["figures"][0].update(duplicate_of=FIG2)),
        "not a figure in the manifest",
    )


def test_m7_duplicate_file_path_cross_check() -> None:
    def with_dup(file: str, dup: bool = True) -> dict[str, Any]:
        d = manifest_dict()
        d["docs"].append(
            document_dict(slug="other-doc", block_ids=[], filename="o.pdf", page_count=2)
        )
        d["figures"].append(
            {
                "id": "FIG-other-doc-p001-01",
                "sidecar": "images/other-doc/FIG-other-doc-p001-01.json",
                "file": file,
                "source_doc": "other-doc",
                "duplicate_of": FIG1 if dup else None,
            }
        )
        return d

    c.Manifest.model_validate(with_dup(f"../{SLUG}/{FIG1}.png"))
    bad(c.Manifest, with_dup("FIG-other-doc-p001-01.png"), "disagrees with duplicate_of")
    bad(c.Manifest, with_dup(f"../{SLUG}/{FIG1}.png", dup=False), "disagrees with duplicate_of")
    bad(c.Manifest, with_dup(f"../elsewhere/{FIG1}.png"), "file must be")


def test_m8_docs_slugs_unique_and_unassigned_article_id_reserved() -> None:
    def dup_doc(d: dict[str, Any]) -> None:
        d["docs"].append(document_dict(block_ids=[]))

    bad(c.Manifest, mut(dup_doc), "slugs must be unique")

    def reserved(d: dict[str, Any]) -> None:
        d["articles"][0].update(id="unassigned", path="articles/unassigned.md")

    bad(c.Manifest, mut(reserved), "reserved")


# manifest.py residual validator branches --------------------------------------------------------
def test_m9_manifest_article_and_figure_paths() -> None:
    d = manifest_dict()
    bad(c.ManifestArticle, {**d["articles"][0], "path": "articles/other.md"}, "path must be")
    bad(c.ManifestFigure, {**d["figures"][0], "sidecar": "images/x/y.json"}, "sidecar must be")
    rs = d["review_stats"]
    m = c.ReviewStats.model_validate({**rs, "numbers_verified_blocks": [B2, B1]})
    assert m.numbers_verified_blocks == [B1, B2]


def test_m10_accounting_branches() -> None:
    bad(
        c.Manifest,
        mut(lambda d: d["accounting"].update(total_blocks=2)),
        "total_blocks must equal len",
    )
    bad(
        c.Manifest,
        mut(lambda d: d["articles"][0]["block_ids"].remove(B2)),
        "do not match accounting",
    )
    bad(
        c.Manifest,
        mut(lambda d: d["accounting"]["unassigned_reasons"].update({B1: "empty"})),
        "unassigned_reasons",
    )

    # figure chain: duplicate_of pointing at a figure that is itself a duplicate
    def chain(d: dict[str, Any]) -> None:
        f = d["figures"][0]
        mid = {**f, "id": FIG2, "sidecar": f"images/{SLUG}/{FIG2}.json", "duplicate_of": FIG1}
        mid["file"] = f"../{SLUG}/{FIG1}.png"
        top = {
            **f,
            "id": f"FIG-{SLUG}-p001-03",
            "sidecar": f"images/{SLUG}/FIG-{SLUG}-p001-03.json",
            "duplicate_of": FIG2,
        }
        d["figures"] += [mid, top]
        f["duplicate_of"] = None

    bad(c.Manifest, mut(chain), "root figure")
    # sorted on load
    d = manifest_dict()
    d["docs"].append(document_dict(slug="aaa-doc", block_ids=[], filename="a.pdf"))
    m = c.Manifest.model_validate(d)
    assert [x.slug for x in m.docs] == ["aaa-doc", SLUG]
    # unknown figure referenced from an article
    bad(
        c.Manifest,
        mut(lambda d: d["articles"][0]["figures"].append(FIG2)),
        "unknown figure",
    )


# -- slug / ids -------------------------------------------------------------------------------
def test_s1_selection_with_malformed_ids_falls_through_to_validation() -> None:
    bad(c.Selection, {"block_ids": ["not-an-id", B1]})
    s = c.Selection.model_validate({"block_ids": (B2, B1)})
    assert s.block_ids == [B1, B2]
    bad(c.Selection, {"block_ids": "b"})


# -- figure sidecar file (item 4) --------------------------------------------------------------
OWN = f"FIG-{SLUG}-p042-01"


@pytest.mark.parametrize(
    "file",
    [
        f"{OWN}.png",
        f"{OWN}.svg",
        "../other-doc/FIG-other-doc-p003-02.png",
        "../other-doc/FIG-other-doc-p003-02.svg",
        f"../{SLUG}/FIG-{SLUG}-p007-01.png",
    ],
)
def test_f1_file_accepted(file: str) -> None:
    c.FigureRecord.model_validate(figure_dict(file=file))


@pytest.mark.parametrize(
    "file",
    [
        "foo.png",
        f"{OWN}.jpg",
        f"{OWN}.gif",
        f"{OWN}.png/extra",
        f"x/{OWN}.png",
        f"../{OWN}.png",
        f"../other-doc/{OWN}.png",  # directory slug disagrees with the id's slug
        "../other-doc/FIG-another-p003-02.png",  # directory slug disagrees
        f"../{SLUG}/{OWN}.png",  # dedup path pointing at itself
        "../Bad/FIG-Bad-p003-02.png",
        "../other-doc/FIG-other-doc-p0003-02.png",
        "../other-doc/FIG-other-doc-p003-02",
        "../../other-doc/FIG-other-doc-p003-02.png",
    ],
)
def test_f1_file_rejected(file: str) -> None:
    bad(c.FigureRecord, figure_dict(file=file), "file must be")


def test_f2_svg_follows_same_rule() -> None:
    other = "FIG-other-doc-p003-02"
    c.FigureRecord.model_validate(
        figure_dict(extraction="vector", svg=f"{OWN}.svg", file=f"{OWN}.png")
    )
    c.FigureRecord.model_validate(
        figure_dict(
            extraction="vector", file=f"../other-doc/{other}.png", svg=f"../other-doc/{other}.svg"
        )
    )
    bad(
        c.FigureRecord,
        figure_dict(extraction="vector", file=f"{OWN}.png", svg=f"../other-doc/{other}.svg"),
        "same figure",
    )
    bad(
        c.FigureRecord,
        figure_dict(extraction="vector", file=f"../other-doc/{other}.png", svg=f"{OWN}.svg"),
        "same figure",
    )
    bad(
        c.FigureRecord,
        figure_dict(extraction="vector", file=f"{OWN}.png", svg=f"{OWN}.png"),
        "file must be",
    )
    bad(
        c.FigureRecord,
        figure_dict(
            extraction="vector",
            file="../other-doc/FIG-other-doc-p003-02.png",
            svg="../other-doc/FIG-other-doc-p004-02.svg",
        ),
        "same figure",
    )


# -- article validators (item 11) --------------------------------------------------------------
def _frontmatter(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": SLUG,
        "title": "T",
        "source_doc": SLUG,
        "source_file": "a.pdf",
        "product_model": None,
        "pages": [1],
        "sections": [],
        "figures": [],
        "blocks": 1,
        "review": {"approved": 1, "edited": 0, "overrides": 0},
        "generated_at": TS,
    }
    d.update(over)
    return d


def test_a1_article_id_must_derive_from_source_doc() -> None:
    c.ArticleFrontmatter.model_validate(_frontmatter())
    c.ArticleFrontmatter.model_validate(_frontmatter(id=f"{SLUG}--belt"))
    bad(c.ArticleFrontmatter, _frontmatter(id="other-doc"), "source_doc")
    bad(c.ArticleFrontmatter, _frontmatter(id=f"{SLUG}x"), "source_doc")
    bad(c.ArticleFrontmatter, _frontmatter(id=f"other--{SLUG}"), "source_doc")


def test_a2_figures_unique() -> None:
    c.ArticleFrontmatter.model_validate(_frontmatter(figures=[FIG1, FIG2]))
    bad(c.ArticleFrontmatter, _frontmatter(figures=[FIG1, FIG1]), "unique")


# -- faithfulness readiness (item 10) -----------------------------------------------------------
def _op(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "op": "replace",
        "raw": "5",
        "clean": "6",
        "raw_start": 10,
        "raw_end": 11,
        "clean_start": 10,
        "clean_end": 11,
        "allowed": False,
    }
    d.update(over)
    return d


def test_d1_diffop_spans_and_allowed() -> None:
    op = c.DiffOp.model_validate(_op())
    assert op.allowed is False
    bad(c.DiffOp, {k: v for k, v in _op().items() if k != "allowed"})
    bad(c.DiffOp, {k: v for k, v in _op().items() if k != "raw_start"})
    bad(c.DiffOp, _op(raw_start=-1))
    bad(c.DiffOp, _op(clean_end=-1))
    bad(c.DiffOp, _op(raw_start=5, raw_end=4), "span")
    bad(c.DiffOp, _op(clean_start=5, clean_end=4), "span")


def test_d2_numeric_variant_and_violation_kinds() -> None:
    assert {k.value for k in c.FaithViolationKind} == {
        "insertion",
        "deletion",
        "numeric_mismatch",
        "reorder",
    }
    nv = {"raw": "35 N·m", "chosen": "35 N·m", "source": "textlayer", "reason": "ocr misread"}
    ok = {
        "passed": True,
        "alignment_ratio": 1.0,
        "violations": [],
        "diff": [],
        "numeric_variants": [nv],
    }
    r = c.FaithfulnessResult.model_validate(ok)
    assert len(r.numeric_variants) == 1 and r.numeric_variants[0].source == "textlayer"
    empty = c.FaithfulnessResult.model_validate({**ok, "numeric_variants": []})
    assert empty.numeric_variants == []
    no_field = {k: v for k, v in ok.items() if k != "numeric_variants"}
    assert c.FaithfulnessResult.model_validate(no_field).numeric_variants == []
    bad(c.FaithfulnessResult, {**ok, "numeric_variants": [{**nv, "source": "guess"}]})
    bad(c.FaithfulnessResult, {**ok, "numeric_variant": nv})  # singular field is gone
    bad(c.FaithfulnessResult, {**ok, "numeric_variants": None})
    bad(c.FaithfulnessResult, {**ok, "numeric_variant_note": "x"})  # old field is gone
    bad(c.NumericVariant, {k: v for k, v in nv.items() if k != "reason"})
    assert [k.value for k in c.DiffOpKind] == ["equal", "insert", "delete", "replace", "reorder"]
    assert c.DiffOp.model_validate(_op(op="reorder")).op == c.DiffOpKind.reorder


# -- document / group branches ------------------------------------------------------------------
def test_doc1_document_branches() -> None:
    c.Document.model_validate(document_dict())
    bad(c.Document, document_dict(filename="a/b.pdf"), "basename")
    bad(c.Document, document_dict(filename="a\\b.pdf"), "basename")
    bad(c.Document, document_dict(stripped_headers=["b", "a"]), "sorted and unique")
    bad(c.Document, document_dict(stripped_footers=["a", "a"]), "sorted and unique")
    bad(c.Document, document_dict(pages_without_text_layer=[2, 2]), "sorted and unique")
    bad(c.Document, document_dict(pages_without_text_layer=[0]), "page_count|greater")
    bad(c.Document, document_dict(block_ids=[B1, B1]), "unique")
    bad(c.Document, document_dict(block_ids=["b-other-doc-p001-01"]), "belong")
    bad(c.Document, {k: v for k, v in document_dict().items() if k != "block_ids"})
    d = c.Document.model_validate(document_dict(block_ids=[B2, B1]))
    assert d.block_ids == [B2, B1]  # parse order is preserved, never sorted


def _group(**over: Any) -> dict[str, Any]:
    g: dict[str, Any] = {
        "id": f"g-{SLUG}-s001",
        "view": "structure",
        "doc_id": SLUG,
        "title": "T",
        "slug": "t",
        "block_ids": [B1],
        "page_ranges": [{"start": 1, "end": 2}],
        "block_count": 1,
        "figure_count": 0,
    }
    g.update(over)
    return g


def test_g1_group_branches() -> None:
    bad(c.Group, _group(id="g-other-doc-s001"), "slug does not match doc_id")
    bad(c.Group, _group(block_ids=[B1, B1], block_count=2), "unique")
    g = c.Group.model_validate(_group(section_ids=[f"g-{SLUG}-s003", f"g-{SLUG}-s002"]))
    assert g.section_ids == [f"g-{SLUG}-s002", f"g-{SLUG}-s003"]
    t = _group(id=f"g-{SLUG}-t001", view="topic", parent_id=f"g-{SLUG}-s001")
    bad(c.Group, t, "parent_id")
    bad(
        c.Group,
        _group(id=f"g-{SLUG}-t001", view="topic", slug="unassigned", is_unassigned=True),
        "is_unassigned",
    )


# -- block still validates with the new diff shape ------------------------------------------------
def test_b1_block_with_faithfulness_roundtrip() -> None:
    faith = {
        "passed": False,
        "alignment_ratio": 0.9,
        "violations": [
            {
                "kind": "reorder",
                "raw_start": 0,
                "raw_end": 3,
                "clean_start": 4,
                "clean_end": 7,
                "raw": "abc",
                "clean": "abc",
            }
        ],
        "diff": [_op()],
    }
    b = c.Block.model_validate(block_dict(faithfulness=faith))
    assert c.Block.model_validate(deepcopy(b.model_dump(mode="json"))) == b


# -- remaining passthrough / error branches ------------------------------------------------------
def test_x1_non_list_inputs_fall_through_to_type_errors() -> None:
    bad(c.FigureRecord, figure_dict(tags="belt"))
    bad(c.FigureRecord, figure_dict(articles="a"))
    bad(c.FigureRecord, figure_dict(tags=[1, 2]))
    bad(c.Group, _group(section_ids="x"))
    bad(c.Block, block_dict(signals="x"))
    bad(c.Proposal, {"id": "prop-000001", "rechecks": "x"})
    bad(c.Manifest, {**manifest_dict(), "docs": "x"})
    bad(c.ReviewStats, {**manifest_dict()["review_stats"], "numbers_verified_blocks": "x"})


def test_x2_datetime_branches() -> None:
    from datetime import datetime

    flag = {"id": "flag-000001", "target_id": B1, "category": "wrong_text"}
    bad(c.Flag, {**flag, "created_at": datetime(2026, 1, 1)}, "timezone-aware")
    bad(c.Flag, {**flag, "created_at": "not a date"})


def test_x3_id_helpers_errors() -> None:
    from manuallabor import ids

    for args in [("Bad", "topic", 1), ("a", "nope", 1), ("a", "topic", 1000), ("a", "topic", -1)]:
        with pytest.raises(ValueError):
            ids.group_id(*args)
    with pytest.raises(ValueError):
        ids.article_id("Bad", None)
    with pytest.raises(ValueError):
        ids.article_id("a", "Bad Topic")
    assert ids.block_sort_key(ids.figure_id("a", 1, 1)) == ("a", 1, 1)


def test_doc2_valid_stripped_lists() -> None:
    d = c.Document.model_validate(
        document_dict(stripped_headers=["a", "b"], stripped_footers=["z"])
    )
    assert d.stripped_headers == ["a", "b"]
