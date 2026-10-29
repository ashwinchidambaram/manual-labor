"""Figure service (design 07 section 5.3): rail, attach/detach overrides, crop bbox."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manuallabor import ids
from manuallabor.cleanup.types import AttachOverride
from manuallabor.contracts._base import check_bbox
from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import read_json
from manuallabor.project import ProjectPaths
from manuallabor.state import projections
from manuallabor.state.data import ProjectData
from manuallabor.state.errors import InvalidOp, NotFound
from manuallabor.state.models import ActionKind, FigureAttachment, FigureRailItem
from manuallabor.state.review import derive
from manuallabor.state.store import Store

__all__ = ["FigureService"]


class FigureService:
    def __init__(self, paths: ProjectPaths, store: Store, data: ProjectData) -> None:
        self.paths = paths
        self.store = store
        self.data = data

    # -- lookups --------------------------------------------------------------------------------

    def _slug(self, figure_id: str) -> str:
        try:
            return ids.parse_figure_id(figure_id)[0]
        except ValueError as exc:
            raise NotFound(figure_id) from exc

    def _record(self, figure_id: str) -> FigureRecord:
        slug = self._slug(figure_id)
        p = self.paths.figure_file(slug, figure_id, "json")
        if not p.is_file():
            raise NotFound(figure_id)
        return read_json(p, FigureRecord)

    def _block_of(self, figure_id: str) -> str:
        slug = self._slug(figure_id)
        for b in self.data.raw_blocks(slug):
            if b.type == BlockType.figure and b.figure_id == figure_id:
                return b.id
        raise NotFound(figure_id)

    def _status(self, slug: str, block_id: str) -> BlockStatus:
        decs = [d for d in self.store.decisions(block_id=block_id)]
        flags = {f.id: f for f in self.store.flags()}
        for b in self.data.machine_blocks(slug):
            if b.id == block_id:
                return derive(b, decs, flags).status
        return BlockStatus.queued

    # -- read -----------------------------------------------------------------------------------

    def rail(self, article_id: str) -> list[FigureRailItem]:
        try:
            slug, _topic = ids.parse_article_id(article_id)
        except ValueError as exc:
            raise NotFound(article_id) from exc
        af = self.data.attach(slug)
        if af is None:
            return []
        out: list[FigureRailItem] = []
        for art in af.articles:
            if art.article_id != article_id:
                continue
            for a in art.figures:
                p = self.paths.figure_file(slug, a.figure_id, "json")
                if not p.is_file():
                    continue
                rec = read_json(p, FigureRecord)
                bid = self._block_of(a.figure_id)
                out.append(
                    FigureRailItem(
                        figure_id=a.figure_id,
                        block_id=bid,
                        record=rec,
                        image_url=f"/api/figures/{a.figure_id}/image",
                        attachment=FigureAttachment(
                            article_id=article_id,
                            rule=a.rule.value,
                            confidence=a.confidence,
                            anchor_block_id=a.anchor_block_id,
                        ),
                        status=self._status(slug, bid),
                    )
                )
        return out

    def image_path(self, figure_id: str) -> Path:
        slug = self._slug(figure_id)
        rec = self._record(figure_id)
        p = (self.paths.figure_dir(slug) / (rec.svg or rec.file)).resolve()
        if not p.is_file():
            p = (self.paths.figure_dir(slug) / rec.file).resolve()
        if not p.is_file():
            raise NotFound(figure_id)
        return p

    # -- write ----------------------------------------------------------------------------------

    def _override(
        self,
        op: str,
        figure_id: str,
        article_id: str,
        anchor: str | None,
        request_id: str,
        screen: str = "verify",
        meta: dict[str, Any] | None = None,
    ) -> AttachOverride:
        prev = self.store.action_by_request(request_id, (ActionKind.attach, ActionKind.detach))
        if prev is not None:
            return AttachOverride.model_validate(prev.payload["_outcome"])
        slug = self._slug(figure_id)
        rec = self._record(figure_id)
        try:
            aslug, _ = ids.parse_article_id(article_id)
        except ValueError as exc:
            raise InvalidOp(f"not an article id: {article_id}") from exc
        if aslug != slug:
            raise InvalidOp("a figure can only be attached to an article of its own document")
        seq = self.store.next_override_seq("attach_overrides")
        ov = AttachOverride(
            seq=seq,
            op=op,  # type: ignore[arg-type]
            figure_id=figure_id,
            article_id=article_id,
            anchor_block_id=anchor if op == "attach" else None,
        )
        example: dict[str, Any] = {
            "doc_id": slug,
            "figure": {
                "figure_id": figure_id,
                "from_articles": list(rec.articles),
                "to_article": article_id if op == "attach" else None,
                "rule_before": rec.attach_rule.value,
            },
        }
        if meta is not None:
            example["proposal"] = meta.get("proposal")
        with self.store.tx():
            aid = self.store.next_action_id()
            self.store.add_override(
                "attach_overrides",
                seq,
                slug,
                json.dumps(ov.model_dump(mode="json"), sort_keys=True),
                aid,
            )
            self.store.append_action(
                ActionKind.attach if op == "attach" else ActionKind.detach,
                screen,
                target_id=figure_id,
                doc_id=slug,
                payload={
                    "override": ov.model_dump(mode="json"),
                    **{k: v for k, v in (meta or {}).items() if k != "proposal"},
                    "_outcome": ov.model_dump(mode="json"),
                },
                example=example,
                request_id=request_id,
                action_id=aid,
            )
            self.store.after_commit(lambda: projections.project_overrides(self.store, self.paths))
        return ov

    def attach(
        self,
        figure_id: str,
        article_id: str,
        anchor: str | None,
        request_id: str,
        *,
        screen: str = "verify",
        meta: dict[str, Any] | None = None,
    ) -> AttachOverride:
        return self._override(
            "attach", figure_id, article_id, anchor, request_id, screen=screen, meta=meta
        )

    def detach(self, figure_id: str, article_id: str, request_id: str) -> AttachOverride:
        return self._override("detach", figure_id, article_id, None, request_id)

    def set_bbox(
        self,
        figure_id: str,
        bbox: list[float],
        request_id: str,
        *,
        screen: str = "verify",
        meta: dict[str, Any] | None = None,
    ) -> None:
        if self.store.action_by_request(request_id, (ActionKind.crop_bbox,)) is not None:
            return
        slug = self._slug(figure_id)
        bid = self._block_of(figure_id)
        blk = next(b for b in self.data.raw_blocks(slug) if b.id == bid)
        if blk.bbox is None:
            raise InvalidOp("only PDF figures have a crop box")
        try:
            check_bbox([float(v) for v in bbox])
        except (ValueError, TypeError) as exc:
            raise InvalidOp(str(exc)) from exc
        seq = self.store.next_figure_override_seq()
        with self.store.tx():
            aid = self.store.next_action_id()
            self.store.add_figure_override(seq, slug, figure_id, [float(v) for v in bbox], aid)
            self.store.append_action(
                ActionKind.crop_bbox,
                screen,
                target_id=figure_id,
                doc_id=slug,
                payload={
                    "bbox": bbox,
                    "before": blk.bbox,
                    **{k: v for k, v in (meta or {}).items() if k != "proposal"},
                    "_outcome": None,
                },
                example={
                    "doc_id": slug,
                    "figure": {
                        "figure_id": figure_id,
                        "from_articles": [],
                        "to_article": None,
                        "rule_before": None,
                    },
                    **({"proposal": meta.get("proposal")} if meta is not None else {}),
                },
                request_id=request_id,
                action_id=aid,
            )
            self.store.after_commit(
                lambda: projections.project_figure_overrides(self.store, self.paths)
            )
