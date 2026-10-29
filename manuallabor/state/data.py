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
from manuallabor.grouping.selection import default_selection, normalize_to, selectable_ids
from manuallabor.parse.types import PageLayout
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import block_contexts, load_scored_blocks
from manuallabor.scoring.types import BlockContext, ScoreFile
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
        """The DB selection (normalized to selectable blocks), or the default when none."""
        groups = self.all_groups()
        body = self.store.get_selection_json()
        if body is None:
            return default_selection(self.paths, groups)
        sel, _ = normalize_to(Selection.model_validate_json(body), selectable_ids(groups))
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
        """ready = score2 output exists (scores.json after clean.json), fresh or stale."""
        from manuallabor.jobs import graph

        dp = self.paths.doc(slug)
        cfg = self.paths.load_config()
        states = graph.doc_node_states(self.paths, slug, cfg)
        by = {s.node: s for s in states}
        ready = dp.scores.is_file() and dp.clean.is_file()
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
