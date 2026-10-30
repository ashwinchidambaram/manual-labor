"""Read-side view of a project for the review/scope/figure services: cached file loads,
selection, review scope and per-document readiness."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from manuallabor import ids
from manuallabor.cleanup.attach import build_articles
from manuallabor.cleanup.types import AttachFile, CleanFile
from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.group import GroupsFile
from manuallabor.contracts.io import read_json, read_json_list
from manuallabor.contracts.selection import Selection
from manuallabor.figures.types import FigureReport
from manuallabor.grouping.selection import (
    default_selection,
    normalize_to,
    selectable_ids,
    with_new_docs,
)
from manuallabor.parse.types import PageLayout
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import block_contexts, load_scored_blocks, scores_current
from manuallabor.scoring.types import BlockContext, ScoreFile, ScoringError
from manuallabor.state.models import DocReadiness
from manuallabor.state.store import Store

__all__ = ["ProjectData", "sig"]


def sig(*paths: Path) -> tuple[Any, ...]:
    out: list[Any] = []
    for p in paths:
        try:
            st = p.stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


class ProjectData:
    def __init__(self, paths: ProjectPaths, store: Store) -> None:
        self.paths = paths
        self.store = store
        self._lock = threading.RLock()
        self._cache: dict[tuple[str, str], tuple[Any, Any]] = {}

    def _cached(self, kind: str, slug: str, signature: tuple[Any, ...], make: Any) -> Any:
        key = (kind, slug)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] == signature:
                return hit[1]
        value = make()
        with self._lock:
            self._cache[key] = (signature, value)
        return value

    def memo(self, kind: str, key: str, signature: tuple[Any, ...], make: Any) -> Any:
        """A value derived from project files and the DB, recomputed when `signature` changes.
        Callers whose value reads decisions, flags, selection or overrides put
        `store.max_action_id()` in the signature (every such write appends an action) and use
        `db_signature`, which refuses to cache inside an open transaction."""
        return self._cached(kind, key, signature, make)

    def db_signature(self, *paths: Path) -> tuple[Any, ...] | None:
        """File stats plus the last action id, or None (do not cache) while a transaction is
        open: its own thread sees rows written before their action row."""
        if self.store.in_tx:
            return None
        return (*sig(*paths), self.store.max_action_id())

    # -- per document files -----------------------------------------------------------------

    def document(self, slug: str) -> Document:
        dp = self.paths.doc(slug)
        doc: Document = self._cached(
            "document", slug, sig(dp.document), lambda: self.paths.load_document(slug)
        )
        return doc

    def machine_blocks(self, slug: str) -> list[Block]:
        """blocks.json + scores.json + clean.json (the machine view; no human overlay)."""
        dp = self.paths.doc(slug)
        return self._cached(  # type: ignore[no-any-return]
            "machine",
            slug,
            sig(dp.blocks, dp.scores, dp.clean),
            lambda: load_scored_blocks(self.paths, slug),
        )

    def scored(self, slug: str) -> bool:
        """Whether the machine view loads: clean.json and a scores.json of this
        `SCORING_ALGO_VERSION` that match blocks.json. False is "not scored yet" for every read
        path (design 03 section 2.10a): a score file from before an upgrade, or one a re-parse
        has outrun, never turns into a 500. Cached on the same stats as `machine_blocks`."""
        return self.paths.doc(slug).clean.is_file() and self.has_scores(slug)

    def has_scores(self, slug: str) -> bool:
        """Whether `machine_blocks` loads: a scores.json of this `SCORING_ALGO_VERSION` that
        matches blocks.json, with or without clean.json. The first scoring pass (before the
        scope is confirmed) is enough for the Scope screen's pre-cleanup estimate (the summary
        and `/api/scope/blocks`); Verify, figures and export need `scored`."""
        dp = self.paths.doc(slug)
        if not scores_current(self.paths, slug):
            return False

        def check() -> bool:
            try:
                self.machine_blocks(slug)
            except ScoringError:
                return False
            return True

        return self._cached("has_scores", slug, sig(dp.blocks, dp.scores, dp.clean), check)  # type: ignore[no-any-return]

    def raw_blocks(self, slug: str) -> list[Block]:
        dp = self.paths.doc(slug)
        return self._cached(  # type: ignore[no-any-return]
            "raw", slug, sig(dp.blocks), lambda: read_json_list(dp.blocks, Block)
        )

    def score_file(self, slug: str) -> ScoreFile | None:
        dp = self.paths.doc(slug)
        if not dp.scores.is_file():
            return None
        return self._cached(  # type: ignore[no-any-return]
            "scores", slug, sig(dp.scores), lambda: read_json(dp.scores, ScoreFile)
        )

    def clean_file(self, slug: str) -> CleanFile | None:
        dp = self.paths.doc(slug)
        if not dp.clean.is_file():
            return None
        return self._cached(  # type: ignore[no-any-return]
            "clean", slug, sig(dp.clean), lambda: read_json(dp.clean, CleanFile)
        )

    def groups(self, slug: str) -> GroupsFile | None:
        dp = self.paths.doc(slug)
        if not dp.groups.is_file():
            return None
        return self._cached(  # type: ignore[no-any-return]
            "groups", slug, sig(dp.groups), lambda: read_json(dp.groups, GroupsFile)
        )

    def attach(self, slug: str) -> AttachFile | None:
        dp = self.paths.doc(slug)
        if not dp.attach.is_file():
            return None
        return self._cached(  # type: ignore[no-any-return]
            "attach", slug, sig(dp.attach), lambda: read_json(dp.attach, AttachFile)
        )

    def figure_captions(self, slug: str) -> dict[str, str]:
        """figure id -> caption_original from figures_report.json (non-empty captions only)."""
        dp = self.paths.doc(slug)

        def make() -> dict[str, str]:
            if not dp.figure_report.is_file():
                return {}
            report = read_json(dp.figure_report, FigureReport)
            return {
                str(f.figure_id): f.caption_original
                for f in report.figures
                if f.caption_original and f.caption_original.strip()
            }

        return self._cached("captions", slug, sig(dp.figure_report), make)  # type: ignore[no-any-return]

    def contexts(self, slug: str) -> dict[str, BlockContext]:
        dp = self.paths.doc(slug)

        def make() -> dict[str, BlockContext]:
            layouts = read_json_list(dp.layout, PageLayout) if dp.layout.is_file() else []
            return block_contexts(self.document(slug), self.raw_blocks(slug), layouts)

        return self._cached("ctx", slug, sig(dp.blocks, dp.layout, dp.document), make)  # type: ignore[no-any-return]

    def all_groups(self) -> dict[str, GroupsFile]:
        out: dict[str, GroupsFile] = {}
        for slug in self.paths.list_slugs():
            gf = self.groups(slug)
            if gf is not None:
                out[slug] = gf
        return out

    # -- selection ----------------------------------------------------------------------------

    def selection(self) -> Selection:
        """The DB selection (normalized to selectable blocks, documents grouped since it was
        written fully selected), or the default when none."""
        groups = self.all_groups()
        body = self.store.get_selection_json()
        if body is None:
            return default_selection(self.paths, groups)
        sel = with_new_docs(Selection.model_validate_json(body), groups)
        sel, _ = normalize_to(sel, selectable_ids(groups))
        return sel

    def raw_selection(self) -> Selection | None:
        body = self.store.get_selection_json()
        return None if body is None else Selection.model_validate_json(body)

    # -- scope --------------------------------------------------------------------------------

    def scope_ids(self, slug: str, selected: set[str] | None = None) -> set[str]:
        """Selected blocks of the document + figure blocks attached to any article."""
        if selected is None:
            selected = set(self.selection().block_ids)
        mine = {b for b in selected if ids.parse_block_id(b)[0] == slug}
        af = self.attach(slug)
        if af is not None:
            fig_block = {
                str(b.figure_id): b.id
                for b in self.raw_blocks(slug)
                if b.type == BlockType.figure and b.figure_id is not None
            }
            for art in af.articles:
                for a in art.figures:
                    bid = fig_block.get(a.figure_id)
                    if bid is not None:
                        mine.add(bid)
        return mine

    def articles_of(self, slug: str, block_id: str) -> list[str]:
        """Article ids the block belongs to (text blocks) or is attached to (figures)."""
        af = self.attach(slug)
        blocks = {b.id: b for b in self.raw_blocks(slug)}
        b = blocks.get(block_id)
        if b is None:
            return []
        if b.type == BlockType.figure and af is not None:
            return sorted(
                art.article_id
                for art in af.articles
                if any(a.figure_id == b.figure_id for a in art.figures)
            )
        gf = self.groups(slug)
        if gf is None:
            return []
        sel = self.selection()
        selected = {x for x in sel.block_ids if ids.parse_block_id(x)[0] == slug}
        order = {x.id: x.reading_order for x in blocks.values()}
        arts = build_articles(slug, gf, selected, sel.article_split, order)
        return sorted(a for a, members in arts.items() if block_id in members)

    # -- readiness ------------------------------------------------------------------------------

    def readiness(self, slug: str) -> DocReadiness:
        """ready = score2 output exists and loads (`scored`: clean.json and a scores.json of
        this algo version), fresh or stale. A score file of another algo version is pending,
        waiting for the first stage that is not fresh."""
        from manuallabor.jobs import graph

        cfg = self.paths.load_config()
        states = graph.doc_node_states(self.paths, slug, cfg)
        by = {s.node: s for s in states}
        ready = self.scored(slug)
        stale = ready and by["score2"].state != "fresh"
        waiting = None
        if not ready:
            for s in states:
                if s.state != "fresh":
                    waiting = s.node
                    break
        return DocReadiness(
            doc_id=slug, state="ready" if ready else "pending", stale=stale, waiting_for=waiting
        )
