"""Builders for the export tests: a real processed project, a scripted reviewer and
independent (test-local) re-derivations of what an article must contain."""

from __future__ import annotations

import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from manuallabor.cleanup.attach import build_articles
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.export.pipeline import resolve_clock, run_export
from manuallabor.grouping.selection import default_selection
from manuallabor.ingest import ingest_files
from manuallabor.project import ProjectPaths
from manuallabor.state.data import ProjectData
from manuallabor.state.figures import FigureService
from manuallabor.state.models import ReviewActionIn, SelectionOp
from manuallabor.state.review import ReviewService, load_review_blocks
from manuallabor.state.scope import ScopeService
from manuallabor.state.store import Store
from tests.conftest import FIXTURES
from tests.subproc import run_bounded

CLOCK = "2026-10-29T12:00:00Z"
CLOCK2 = "2026-10-30T08:30:00Z"


def labor_run(root: Path, *args: str) -> None:
    """`labor run --mock` in a child process: Docling stays out of the pytest process (the API
    tests assert that importing the app never loads it). Bounded: a hang fails the test."""
    r = run_bounded([sys.executable, "-m", "manuallabor", "run", str(root), "--mock", *args])
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]


def build_scored(root: Path, files: list[Path]) -> ProjectPaths:
    """Ingest, parse, group, select everything, clean and score (mock models)."""
    root.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "project-a" / "project.json", root / "project.json")
    paths = ProjectPaths(root)
    ingest_files(paths, files, emit=lambda _o: None)
    labor_run(root, "--to", "group")
    store = Store.open(paths)
    try:
        data = ProjectData(paths, store)
        sel = default_selection(paths, data.all_groups())
        ScopeService(paths, store, data).apply(
            SelectionOp(op="select", block_ids=list(sel.block_ids), request_id="t-select")
        )
    finally:
        store.close()
    labor_run(root, "--to", "score2")
    return paths


def reviewer(paths: ProjectPaths, store: Store) -> ReviewService:
    data = ProjectData(paths, store)
    return ReviewService(paths, store, data, FigureService(paths, store, data))


def approve_queued(paths: ProjectPaths, store: Store) -> int:
    """Approve every queued in-scope block (a scripted reviewer)."""
    review = reviewer(paths, store)
    data = ProjectData(paths, store)
    selected = set(data.selection().block_ids)
    n = 0
    for slug in paths.list_slugs():
        scope = data.scope_ids(slug, selected)
        for b in load_review_blocks(paths, store, slug):
            if b.id in scope and b.status == BlockStatus.queued:
                review.act(
                    ReviewActionIn(kind="approve", block_id=b.id, request_id=f"t-approve-{b.id}")
                )
                n += 1
    return n


@dataclass
class Exported:
    paths: ProjectPaths
    zip: Path
    sha: str
    clock: str = CLOCK

    @property
    def staging(self) -> Path:
        return self.paths.assembled

    def names(self) -> list[str]:
        with zipfile.ZipFile(self.zip) as zf:
            return zf.namelist()

    def read(self, name: str) -> bytes:
        with zipfile.ZipFile(self.zip) as zf:
            return zf.read(name)

    def text(self, name: str) -> str:
        return self.read(name).decode("utf-8")


def export_project(scored: ProjectPaths, dst: Path, clock: str = CLOCK) -> Exported:
    """Copy a scored project (with its database), approve everything, export."""
    from tests.conftest import labor_copy

    labor_copy(scored.root, dst, db=True)
    paths = ProjectPaths(dst)
    store = Store.open(paths)
    try:
        approve_queued(paths, store)
        rec = run_export(paths, store, clock=resolve_clock(clock), emit=lambda _o: None)
    finally:
        store.close()
    return Exported(paths, Path(rec.zip_path), rec.summary.zip_sha256, clock)


# -- independent re-derivation of an article ------------------------------------------------------

_ENUM = re.compile(r"^(?:\(?\d{1,2}[.)]|[a-z][.)])\s")


def t_of(b: Block) -> str:
    return b.clean_text if b.clean_text is not None else b.raw_text


def list_lines(t: str) -> list[str]:
    out = []
    for line in t.split("\n"):
        if line.startswith("• "):
            out.append("* " + line[2:])
        elif line == "" or line.startswith("* ") or _ENUM.match(line):
            out.append(line)
        else:
            out.append("* " + line)
    return out


def alt_of(fid: str, caption: str | None, generated: str | None) -> str:
    def esc(x: str) -> str:
        x = x.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        return x.replace(")", "\\)").replace("<", "\\<")

    cap = " ".join((caption or "").split())
    if cap:
        return f"{fid} \u2014 {esc(cap)}"
    gen = " ".join((generated or "").split())
    return f"{fid} \u2014 [generated] {esc(gen)}" if gen else f"{fid} \u2014 (no caption)"


def expected_body(
    paths: ProjectPaths, store: Store, article_id: str, *, with_markers: bool = True
) -> tuple[str, list[str]]:
    """(the article text after the frontmatter block's closing line, figure ids in order),
    derived only from the review blocks, groups.json, attach.json and the sidecars. With
    `with_markers`, each auto-approved text block is followed by its review marker (design 11
    section 20; the projects these tests export carry no override); without, the body is the
    one the section 3.2 grammar produced before section 20."""
    from manuallabor import ids
    from manuallabor.cleanup.types import AttachFile
    from manuallabor.contracts.figure import FigureRecord, parse_figure_file
    from manuallabor.contracts.group import GroupsFile
    from manuallabor.contracts.io import read_json
    from manuallabor.figures.types import FigureReport

    slug = ids.parse_article_id(article_id)[0]
    dp = paths.doc(slug)
    blocks = {b.id: b for b in load_review_blocks(paths, store, slug)}
    gf = read_json(dp.groups, GroupsFile)
    af = read_json(dp.attach, AttachFile)
    sel = ProjectData(paths, store).selection()
    order = {b.id: b.reading_order for b in blocks.values()}
    selected = {
        b
        for b in sel.block_ids
        if b in blocks and blocks[b].type not in (BlockType.header, BlockType.footer)
    }
    members = build_articles(slug, gf, selected, sel.article_split, order)[article_id]
    kept = [
        blocks[b]
        for b in members
        if blocks[b].status != BlockStatus.rejected
        and (blocks[b].type == BlockType.figure or " ".join(blocks[b].raw_text.split()))
    ]
    level_of: dict[str, int] = {}
    for g in gf.structure:
        if gf.title_sources.get(g.id) == "heading":
            level_of[min(g.block_ids, key=lambda b: order[b])] = g.level
    items: list[tuple[tuple[int, int, int], str, str | None]] = []
    for b in kept:
        if b.type == BlockType.figure:
            continue
        t = t_of(b)
        if b.type == BlockType.heading and b.id in level_of:
            t = "#" * min(6, 1 + level_of[b.id]) + " " + t
        elif b.type == BlockType.list:
            t = "\n".join(list_lines(t))
        items.append(((b.reading_order, 0, 0), t, None))
        if with_markers and b.status == BlockStatus.auto_approved:
            items.append(
                ((b.reading_order, 0, 1), f"<!-- ml: auto-approved; block: {b.id} -->", None)
            )
    have = {b.id for b in kept if b.type != BlockType.figure}
    kept_order = {b.id: b.reading_order for b in kept}
    cap_block = {
        f.figure_id: f.caption_block_id for f in read_json(dp.figure_report, FigureReport).figures
    }
    own = {str(b.figure_id): b.id for b in blocks.values() if b.figure_id}
    for art in af.articles:
        if art.article_id != article_id:
            continue
        for i, a in enumerate(art.figures):
            rec = read_json(paths.figure_file(slug, a.figure_id, "json"), FigureRecord)
            rule = a.rule.value
            if rule in ("caption_ref", "caption_match", "human") and a.anchor_block_id in have:
                key = (kept_order[str(a.anchor_block_id)], 1, i)
            elif rule in ("caption_ref", "caption_match") or (
                rule == "human" and a.anchor_block_id is not None
            ):
                key = (10**9, 0, i)
            elif cap_block.get(a.figure_id) in have:
                key = (kept_order[str(cap_block[a.figure_id])], 1, i)
            elif own.get(a.figure_id) in kept_order:
                key = (kept_order[own[a.figure_id]], -1, i)
            else:
                key = (10**9, 0, i)
            tgt = parse_figure_file(rec.id, rec.file, ("png", "svg"))
            canon = rec.id if tgt is None else tgt[1]
            path = f"images/{ids.parse_figure_id(canon)[0]}/{canon}.png"
            alt = alt_of(rec.id, rec.caption_original, rec.description_generated)
            items.append((key, f"![{alt}]({path})", a.figure_id))
    items.sort(key=lambda x: x[0])
    return "\n\n".join(t for _, t, _ in items), [f for _, _, f in items if f is not None]
