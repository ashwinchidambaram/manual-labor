"""E1-E3, E8, E10-E13, E15-E16, E24: the exported zip of real, parsed projects."""

from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from manuallabor import ids
from manuallabor.contracts.article import ArticleFrontmatter
from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.manifest import Manifest
from manuallabor.export.pipeline import read_state
from manuallabor.export.render import FIGURE_LINE_RE
from manuallabor.export.types import ExportError
from manuallabor.export.validate import split_article, validate_zip
from manuallabor.export.zip import ZIP_DATE
from manuallabor.project import ProjectPaths
from manuallabor.scoring.numeric import FAITH_NUM_RE
from manuallabor.state.review import load_review_blocks
from manuallabor.state.store import Store
from tests.export.helpers import Exported, expected_body, t_of


def manifest_of(e: Exported) -> Manifest:
    return Manifest.model_validate_json(e.read("manifest.json"))


@pytest.fixture
def ro_store(exported_a: Exported) -> Store:
    s = Store.open(exported_a.paths, readonly=True)
    yield s  # type: ignore[misc]
    s.close()


def frontmatter_end(text: str) -> int:
    return text.index("\n---\n", 3) + 5


def test_e1_body_is_derived_from_the_blocks_byte_for_byte(
    exported_a: Exported, ro_store: Store
) -> None:
    m = manifest_of(exported_a)
    assert m.articles
    n_figs = 0
    for a in m.articles:
        text = exported_a.text(a.path)
        body, figs = expected_body(exported_a.paths, ro_store, a.id)
        want = "\n# " + a.title + "\n" + ("\n" + body + "\n" if body else "")
        assert text[frontmatter_end(text) :] == want, a.id
        assert figs == a.figures
        n_figs += len(figs)
        # section 20.6: deleting the markers gives the pre-marker body byte for byte
        old, _ = expected_body(exported_a.paths, ro_store, a.id, with_markers=False)
        stripped = re.sub(r"\n\n<!-- ml: [^\n]* -->(?=\n)", "", text)
        assert stripped[frontmatter_end(stripped) :] == "\n# " + a.title + "\n" + (
            "\n" + old + "\n" if old else ""
        ), a.id
    assert n_figs >= 10  # figures.pdf is figure-heavy


def test_e2_numeric_multiset_is_unchanged(exported_a: Exported, ro_store: Store) -> None:
    m = manifest_of(exported_a)
    checked = 0
    for a in m.articles:
        text = exported_a.text(a.path)
        body = text[frontmatter_end(text) :]
        lines = body.split("\n")[2:]  # the blank line and `# title`
        kept = []
        for ln in lines:
            if ln.startswith(("![FIG-", "<!-- ml: ")):
                continue  # alt text and review markers are metadata, not article text
            ln = ln.removeprefix("* ") if ln.startswith("* ") else ln
            while ln.startswith("#"):
                ln = ln.lstrip("#").lstrip(" ")
                break
            kept.append(ln)
        got = Counter(FAITH_NUM_RE.findall("\n".join(kept)))
        slug = a.source_doc
        by_id = {b.id: b for b in load_review_blocks(exported_a.paths, ro_store, slug)}
        want: Counter[str] = Counter()
        for bid in a.block_ids:
            b = by_id[bid]
            if b.type != BlockType.figure:
                want.update(FAITH_NUM_RE.findall(t_of(b).replace("• ", "")))
        assert got == want, a.id
        checked += sum(got.values())
    assert checked > 50


def test_e3_every_body_line_is_explained(exported_a: Exported, ro_store: Store) -> None:
    m = manifest_of(exported_a)
    for a in m.articles:
        by_id = {b.id: b for b in load_review_blocks(exported_a.paths, ro_store, a.source_doc)}
        allowed: set[str] = set()
        for bid in a.block_ids:
            b = by_id[bid]
            if b.type == BlockType.figure:
                continue
            for ln in t_of(b).split("\n"):
                allowed.add(ln)
                allowed.add("* " + ln)
                if ln.startswith("• "):
                    allowed.add("* " + ln[2:])
                for k in range(2, 7):
                    allowed.add("#" * k + " " + ln)
        text = exported_a.text(a.path)
        for ln in text[frontmatter_end(text) :].split("\n"):
            if ln == "" or ln == f"# {a.title}" or FIGURE_LINE_RE.match(ln):
                continue
            if ln.startswith("<!-- ml: auto-approved; block: ") and ln.endswith(" -->"):
                bid = ln.split("block: ", 1)[1][: -len(" -->")]
                assert bid in a.block_ids and by_id[bid].status == BlockStatus.auto_approved
                continue
            assert ln in allowed, f"{a.id}: unexplained line {ln[:80]!r}"


def test_e8_figure_lines(exported_a: Exported) -> None:
    m = manifest_of(exported_a)
    n = 0
    with_caption = 0
    for a in m.articles:
        text = exported_a.text(a.path)
        for ln in text.split("\n"):
            if not ln.startswith("!["):
                continue
            mt = FIGURE_LINE_RE.match(ln)
            assert mt, ln
            n += 1
            assert mt.group("alt") != ""
            fid = mt.group("fid")
            slug = ids.parse_figure_id(fid)[0]
            rec = FigureRecord.model_validate_json(exported_a.read(f"images/{slug}/{fid}.json"))
            if rec.caption_original:
                with_caption += 1
                cap = " ".join(rec.caption_original.split())
                assert mt.group("alt") == cap.replace("[", "\\[").replace("]", "\\]")
            elif rec.description_generated:
                assert mt.group("alt").startswith("[generated] ")
    assert n >= 10 and with_caption >= 5


def test_e10_duplicates_share_one_file(exported_dup: Exported) -> None:
    m = manifest_of(exported_dup)
    dups = {f.id: f for f in m.figures if f.duplicate_of is not None}
    copy_dups = [f for f in dups.values() if f.source_doc == "figures-copy"]
    assert len(copy_dups) == 14, "every figure of the byte copy duplicates one of the original"
    assert any(f.source_doc == "figures" for f in dups.values()), "and the fixture has its own"
    names = set(exported_dup.names())
    for d in dups.values():
        assert d.duplicate_of is not None
        canon = d.duplicate_of
        cdoc = ids.parse_figure_id(canon)[0]
        assert canon not in dups  # duplicates point at a root
        assert f"images/{cdoc}/{canon}.png" in names
        assert f"images/{d.source_doc}/{d.id}.png" not in names  # no own file
        assert f"images/{d.source_doc}/{d.id}.json" in names  # but its own sidecar
        rec = FigureRecord.model_validate_json(exported_dup.read(d.sidecar))
        assert rec.file == f"../{cdoc}/{canon}.png" == d.file
    refs = 0
    for a in m.articles:
        for ln in exported_dup.text(a.path).split("\n"):
            mt = FIGURE_LINE_RE.match(ln)
            if mt and mt.group("fid") in dups:
                refs += 1
                canon = dups[mt.group("fid")].duplicate_of
                assert (
                    mt.group("path") == f"images/{ids.parse_figure_id(str(canon))[0]}/{canon}.png"
                )
                assert mt.group("fid").startswith(f"FIG-{a.source_doc}-")  # alt keeps its own id
    assert refs >= 10
    own_files = {n for n in names if n.endswith(".png")}
    assert not [n for n in own_files if "/figures-copy/" in n]
    assert len(own_files) == len(m.figures) - len(dups)


def test_e11_vector_figures_ship_png_and_svg(exported_a: Exported) -> None:
    m = manifest_of(exported_a)
    names = set(exported_a.names())
    vec = []
    for f in m.figures:
        rec = FigureRecord.model_validate_json(exported_a.read(f.sidecar))
        if rec.svg is not None:
            vec.append(f.id)
            assert f"images/{f.source_doc}/{f.id}.svg" in names
            assert f"images/{f.source_doc}/{f.id}.png" in names
    assert vec, "figures.pdf has vector figures"
    for a in m.articles:
        assert ".svg)" not in exported_a.text(a.path)


def test_e12_every_block_is_accounted_for(exported_a: Exported, ro_store: Store) -> None:
    m = manifest_of(exported_a)
    acc = m.accounting
    parsed = {}
    for slug in exported_a.paths.list_slugs():
        for b in load_review_blocks(exported_a.paths, ro_store, slug):
            parsed[b.id] = b
    assert set(acc.assignments) == set(parsed) and acc.total_blocks == len(parsed)
    in_art = Counter(b for a in m.articles for b in a.block_ids)
    assert all(c == 1 for c in in_art.values())
    for bid, where in acc.assignments.items():
        if where == ids.UNASSIGNED:
            assert bid not in in_art
            reason = acc.unassigned_reasons[bid]
            if parsed[bid].type in (BlockType.header, BlockType.footer):
                assert reason == "header_footer"
        else:
            assert bid in in_art and bid not in acc.unassigned_reasons
    assert any(r == "header_footer" for r in acc.unassigned_reasons.values())
    from manuallabor.state.data import ProjectData

    selected = set(ProjectData(exported_a.paths, ro_store).selection().block_ids)
    not_sel = [b for b, r in acc.unassigned_reasons.items() if r == "not_selected"]
    assert all(b not in selected for b in not_sel)  # `not_selected` means just that
    for bid, where in acc.assignments.items():
        if bid in selected and parsed[bid].type not in (BlockType.header, BlockType.footer):
            assert where != ids.UNASSIGNED or acc.unassigned_reasons[bid] in ("empty", "rejected")
    assert {a.id: a.block_ids for a in m.articles}
    Manifest.model_validate(json.loads(exported_a.read("manifest.json")))
    for a in m.articles:
        fm, _ = split_article(exported_a.text(a.path))
        assert fm["blocks"] == len(a.block_ids)
    assert m.review_stats.overrides == 0 and m.overrides == []
    assert m.review_stats.total_blocks == len(parsed)
    assert Counter(b.status.value for b in parsed.values())["queued"] == 0


def test_e13_split_modes(scored_a: ProjectPaths, tmp_path: Path) -> None:
    from manuallabor.contracts.enums import ArticleSplit
    from manuallabor.export.pipeline import resolve_clock, run_export
    from manuallabor.jobs.inline import run_inline
    from manuallabor.state.data import ProjectData
    from manuallabor.state.models import RunPlanIn, SelectionOp
    from manuallabor.state.scope import ScopeService
    from tests.conftest import labor_copy
    from tests.export.helpers import approve_queued

    paths = ProjectPaths(labor_copy(scored_a.root, tmp_path / "proj", db=True))
    store = Store.open(paths)
    clock = resolve_clock("2026-10-29T12:00:00Z")
    try:
        approve_queued(paths, store)
        topic = run_export(paths, store, clock=clock)
        mt = Manifest.model_validate_json(zipfile.ZipFile(topic.zip_path).read("manifest.json"))
        ScopeService(paths, store, ProjectData(paths, store)).apply(
            SelectionOp(op="set_split", split="per_document", request_id="t-split")
        )
        with pytest.raises(ExportError, match="stale"):
            run_export(paths, store, clock=clock)  # attach.json depends on the split
        res = run_inline(
            paths, RunPlanIn(to="score2"), mode="mock", emit=lambda _o: None, store=store
        )
        assert res.ok
        approve_queued(paths, store)
        doc = run_export(paths, store, clock=clock)
        md = Manifest.model_validate_json(zipfile.ZipFile(doc.zip_path).read("manifest.json"))
    finally:
        store.close()
    assert (
        mt.article_split == ArticleSplit.per_topic and md.article_split == ArticleSplit.per_document
    )
    assert any(a.id.endswith("--unassigned") for a in mt.articles)
    assert {a.id for a in md.articles} == {"clean", "figures"}
    assert {a.id for a in mt.articles if a.source_doc == "clean"} != {"clean"}
    flat = lambda m: sorted(b for a in m.articles for b in a.block_ids)  # noqa: E731
    assert flat(mt) == flat(md)
    assert validate_zip(Path(doc.zip_path)) == []


def test_e15_zip_structure(exported_a: Exported) -> None:
    with zipfile.ZipFile(exported_a.zip) as zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        assert names == sorted(names, key=lambda n: n.encode())
        assert names[0] == "README.md" and names[-1] == "manifest.json"
        assert not [n for n in names if n.endswith("/")]
        for i in infos:
            assert i.date_time == ZIP_DATE and i.create_system == 3
            assert i.external_attr == 0o644 << 16 and i.extra == b"" and i.comment == b""
            want = zipfile.ZIP_STORED if i.filename.endswith(".png") else zipfile.ZIP_DEFLATED
            assert i.compress_type == want, i.filename
        assert zf.testzip() is None and zf.comment == b""


def test_e16_validate_positive(exported_a: Exported, exported_dup: Exported) -> None:
    assert validate_zip(exported_a.zip) == []
    assert validate_zip(exported_dup.zip) == []


def test_e24_summary_matches_a_recount(exported_a: Exported) -> None:
    st = read_state(exported_a.paths)
    assert st.export is not None
    s = st.export.summary
    m = manifest_of(exported_a)
    assert (
        s.articles
        == len(m.articles)
        == len([n for n in exported_a.names() if n.startswith("articles/") and n.endswith(".md")])
    )
    assert (
        s.figures
        == len(m.figures)
        == len([n for n in exported_a.names() if n.endswith(".json") and n.startswith("images/")])
    )
    pages = set()
    for a in m.articles:
        fm = ArticleFrontmatter.model_validate(split_article(exported_a.text(a.path))[0])
        pages |= {(fm.source_doc, p) for p in fm.pages}
    assert s.pages_covered == len(pages)
    rs = m.review_stats
    # design 11 section 14: the summary counts the exported blocks, one bucket each (a page
    # header is auto-approved in review_stats but never exported)
    exported = [b for b, a in m.accounting.assignments.items() if a != "unassigned"]
    r = s.review
    assert r.blocks == len(exported) == r.auto_approved + r.approved + r.edited + r.overrides
    assert r.total_blocks == rs.total_blocks == r.blocks + sum(r.left_out.values())
    assert r.approved <= rs.approved and r.auto_approved <= rs.auto_approved
    assert s.review.numbers_verified == len(rs.numbers_verified_blocks) > 0
    assert s.zip_bytes == exported_a.zip.stat().st_size and s.docs == 2
    assert s.zip_sha256 == exported_a.sha and BlockStatus.approved.value
