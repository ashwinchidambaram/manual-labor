"""Review service (design 07 section 2.3 and 5.3): status derivation, queue, cursor, actions.

Block status is *derived* from the append-only decisions; nothing here writes a status."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manuallabor import ids
from manuallabor.contracts.block import Block, DiffOp, FaithfulnessResult, Signal
from manuallabor.contracts.decision import Decision
from manuallabor.contracts.enums import (
    BlockStatus,
    BlockType,
    DecisionAction,
    DocKind,
    FaithViolationKind,
    FlagStatus,
    ProposalStatus,
)
from manuallabor.contracts.flag import Flag
from manuallabor.contracts.proposal import Proposal
from manuallabor.project import ProjectPaths
from manuallabor.scoring.faithfulness import check_faithfulness_ex
from manuallabor.scoring.pipeline import faith_kwargs
from manuallabor.state.card import card_excerpt, section_titles, weakest_word
from manuallabor.state.data import ProjectData
from manuallabor.state.errors import (
    EditConflictError,
    InvalidOp,
    NoPageRender,
    NotFound,
    OutOfScope,
)
from manuallabor.state.interfaces import FigureServiceP
from manuallabor.state.models import (
    ActionKind,
    BlockDetail,
    Cursor,
    DecisionRecord,
    DocReadiness,
    EditConflict,
    LearningUse,
    PageRef,
    QueueItem,
    QueuePage,
    QueueSort,
    ReviewActionIn,
    ReviewActionOut,
    ReviewCounts,
    WhyItem,
)
from manuallabor.state.store import Store, sha_text

__all__ = [
    "Derived",
    "HumanEditCheck",
    "ReviewService",
    "check_human_edit",
    "derive",
    "derive_status",
    "display_text",
    "load_review_blocks",
    "numeric_changes",
    "overlay_block",
    "why_items",
]

TRAIL_MAX = 50
_ACT_KINDS = (
    ActionKind.approve,
    ActionKind.edit,
    ActionKind.flag,
    ActionKind.skip,
    ActionKind.back,
)


def display_text(block: Block) -> str:
    return block.clean_text if block.clean_text is not None else block.raw_text


@dataclass(frozen=True)
class Derived:
    status: BlockStatus
    stale_reason: str | None
    decision: DecisionRecord | None  # the effective decision (approve / edit / flag)
    latest: DecisionRecord | None  # the latest current decision of any kind (incl. skip)
    orphaned: int  # decisions made on other raw text
    skipped: bool
    # the latest current human/agent edit: the text source while the block is `edited` (an
    # approve after it applies to the edited text and keeps status `edited`)
    edit: DecisionRecord | None = None


def derive(block: Block, decisions: Sequence[DecisionRecord], flags: Mapping[str, Flag]) -> Derived:
    """The status table of design 07 section 2.3 (first matching row)."""
    raw_sha = sha_text(block.raw_text)
    current = [d for d in decisions if d.raw_sha256 == raw_sha]
    orphaned = len(decisions) - len(current)
    latest = current[-1] if current else None
    effective = [d for d in current if d.decision.action != DecisionAction.skip]
    d = effective[-1] if effective else None
    skipped = latest is not None and latest.decision.action == DecisionAction.skip
    edits = [x for x in effective if x.decision.action == DecisionAction.edit]
    edit = edits[-1] if edits else None
    machine = block.status
    if d is None:
        return Derived(machine, None, None, latest, orphaned, skipped)
    act = d.decision.action
    if act == DecisionAction.approve:
        if edit is not None:
            # approve after an edit approves the edited text; a human edit is never discarded
            # (an approval recorded against other text leaves the edit unapproved)
            return Derived(BlockStatus.edited, None, d, latest, orphaned, skipped, edit)
        if d.shown_text_sha256 == sha_text(display_text(block)):
            return Derived(BlockStatus.approved, None, d, latest, orphaned, skipped)
        return Derived(machine, "changed since approval", d, latest, orphaned, skipped)
    if act == DecisionAction.edit:
        return Derived(BlockStatus.edited, None, d, latest, orphaned, skipped, d)
    # flag
    fid = d.decision.flag_id
    flag = flags.get(fid) if fid is not None else None
    if flag is not None and flag.status == FlagStatus.open:
        return Derived(BlockStatus.flagged, None, d, latest, orphaned, skipped)
    return Derived(machine, None, d, latest, orphaned, skipped)


def derive_status(
    block: Block, decisions: Sequence[DecisionRecord], flags: Mapping[str, Flag]
) -> tuple[BlockStatus, str | None]:
    r = derive(block, decisions, flags)
    return r.status, r.stale_reason


def overlay_block(block: Block, r: Derived) -> Block:
    """The machine block with the human state applied (validated)."""
    if r.status == block.status and r.stale_reason is None and r.decision is None:
        return block
    fields: dict[str, Any] = {"status": r.status.value}
    if r.status == BlockStatus.approved:
        fields["numbers_verified"] = block.has_numeric_spec
    elif r.status == BlockStatus.edited and r.edit is not None and r.decision is not None:
        fields["clean_text"] = r.edit.decision.edited_text
        # verified only by an approval of the edited text (or an accepted proposal), never by
        # the edit itself
        if r.decision.decision.action == DecisionAction.approve:
            verified = r.decision.shown_text_sha256 == sha_text(r.edit.decision.edited_text or "")
        else:
            verified = r.decision.numbers_verified
        fields["numbers_verified"] = block.has_numeric_spec and verified
        fields["faithfulness"] = None
    else:
        fields["numbers_verified"] = False
    return Block.model_validate({**block.model_dump(mode="json"), **fields})


def load_review_blocks(paths: ProjectPaths, store: Store, slug: str) -> list[Block]:
    """scoring.load_scored_blocks + the decision overlay. The API and module 11 read blocks
    only through this (or ReviewService); it never feeds back into scoring."""
    from manuallabor.scoring.pipeline import load_scored_blocks

    machine = load_scored_blocks(paths, slug)
    decisions: dict[str, list[DecisionRecord]] = {}
    for d in store.decisions(doc_id=slug):
        decisions.setdefault(d.decision.block_id, []).append(d)
    flags = {f.id: f for f in store.flags()}
    return [overlay_block(b, derive(b, decisions.get(b.id, ()), flags)) for b in machine]


def _title_rows(slug: str, overlays: Sequence[Block]) -> dict[str, dict[str, Any]]:
    titles = section_titles(overlays)
    return {
        b.id: {
            "block_id": b.id,
            "doc_id": slug,
            "page": b.page,
            "type": b.type.value,
            "section_title": titles.get(b.id),
        }
        for b in overlays
    }


# -- why list ----------------------------------------------------------------------------------


def why_items(block: Block, stale_reason: str | None, learning: LearningUse) -> list[WhyItem]:
    items = [
        WhyItem(
            kind="signal", name=s.name.value, value=s.value, critical=s.critical, detail=s.detail
        )
        for s in block.signals
    ]
    items.sort(key=lambda w: (not w.critical, w.value if w.value is not None else 2.0, w.name))
    if stale_reason is not None:
        items.insert(0, WhyItem(kind="stale", name=stale_reason, critical=True))
    for rule in learning.learned_rules:
        items.append(WhyItem(kind="rule", name=rule, critical=False))
    for ex in learning.few_shot:
        items.append(WhyItem(kind="learning", name=ex, critical=False))
    return items


def _reasons(items: Sequence[WhyItem]) -> list[str]:
    out: list[str] = []
    for w in items:
        if w.kind == "stale" or (w.kind == "signal" and w.value is not None and w.value < 1.0):
            out.append(w.name)
        if len(out) == 3:
            break
    return out


# -- human edit faithfulness -------------------------------------------------------------------


@dataclass(frozen=True)
class HumanEditCheck:
    result: FaithfulnessResult
    numeric_changes: list[str]

    @property
    def passed(self) -> bool:
        return self.result.passed


def numeric_changes(result: FaithfulnessResult) -> list[str]:
    removed = [
        v.raw for v in result.violations if v.kind == FaithViolationKind.numeric_mismatch and v.raw
    ]
    added = [
        v.clean
        for v in result.violations
        if v.kind == FaithViolationKind.numeric_mismatch and v.clean
    ]
    out: list[str] = []
    for i in range(max(len(removed), len(added))):
        a = removed[i] if i < len(removed) else "(none)"
        b = added[i] if i < len(added) else "(none)"
        out.append(f"{a} → {b}")
    return out


def check_human_edit(data: ProjectData, block: Block, text: str) -> HumanEditCheck:
    """The real faithfulness check of the human's text against the block's raw text."""
    raw_block = block.model_copy(update={"clean_text": None})
    ctx = data.contexts(block.doc_id)[block.id]
    sf = data.score_file(block.doc_id)
    variants = []
    if sf is not None:
        for s in sf.blocks:
            if s.block_id == block.id and s.faithfulness is not None:
                variants = list(s.faithfulness.numeric_variants)
    out = check_faithfulness_ex(raw_block.raw_text, text, **faith_kwargs(raw_block, ctx, variants))
    return HumanEditCheck(out.result, numeric_changes(out.result))


# -- the service -------------------------------------------------------------------------------


@dataclass
class _Entry:
    key: tuple[Any, ...]
    item: QueueItem


@dataclass(frozen=True)
class _CardContext:
    """Per-document inputs of the queue card fields."""

    titles: Mapping[str, str | None]
    captions: Mapping[str, str]


@dataclass
class _Scan:
    pending: list[_Entry]
    counts: ReviewCounts


class ReviewService:
    def __init__(
        self,
        paths: ProjectPaths,
        store: Store,
        data: ProjectData,
        figures: FigureServiceP | None = None,
    ) -> None:
        self.paths = paths
        self.store = store
        self.data = data
        self.figures = figures

    # -- helpers --------------------------------------------------------------------------

    def _provenance(self, slug: str) -> str:
        cf = self.data.clean_file(slug)
        return cf.learning_snapshot if cf is not None else "baseline"

    def _ready_docs(self, doc_filter: str | None = None) -> list[str]:
        out = []
        for slug in self.paths.list_slugs():
            if doc_filter is not None and slug != doc_filter:
                continue
            if self.data.scored(slug):  # a score file of another algo version is not ready
                out.append(slug)
        return out

    def _decisions_by_block(self, slug: str) -> dict[str, list[DecisionRecord]]:
        out: dict[str, list[DecisionRecord]] = {}
        for d in self.store.decisions(doc_id=slug):
            out.setdefault(d.decision.block_id, []).append(d)
        return out

    def _flags(self) -> dict[str, Flag]:
        return {f.id: f for f in self.store.flags()}

    def _doc_signature(self, slug: str) -> tuple[Any, ...] | None:
        """What a document's human overlay depends on: the machine view's files and the action
        log (every decision, flag and resolution is written with an action). None inside a
        transaction (never cached there)."""
        dp = self.paths.doc(slug)
        return self.data.db_signature(dp.blocks, dp.scores, dp.clean)

    def _derive_doc(self, slug: str) -> list[tuple[Block, Block, Derived]]:
        """(machine, overlay, derived) per block of the document; cached until a file or the
        action log changes (review F4/F5: every read path shares one derivation)."""
        sg = self._doc_signature(slug)
        if sg is None:
            return self._derive_doc_uncached(slug)
        out: list[tuple[Block, Block, Derived]] = self.data.memo(
            "derived", slug, sg, lambda: self._derive_doc_uncached(slug)
        )
        return out

    def _derive_doc_uncached(self, slug: str) -> list[tuple[Block, Block, Derived]]:
        decs = self._decisions_by_block(slug)
        flags = self._flags()
        out = []
        for b in self.data.machine_blocks(slug):
            r = derive(b, decs.get(b.id, ()), flags)
            out.append((b, overlay_block(b, r), r))
        return out

    def _derived_view(self, kind: str, slug: str, make: Any) -> Any:
        """A projection of `_derive_doc(slug)` cached on the same signature."""
        sg = self._doc_signature(slug)
        if sg is None:
            return make(self._derive_doc_uncached(slug))
        return self.data.memo(kind, slug, sg, lambda: make(self._derive_doc(slug)))

    def review_blocks(self, slug: str) -> list[Block]:
        """The document's blocks with the human overlay (`load_review_blocks`, cached)."""
        out: list[Block] = self._derived_view("overlays", slug, lambda d: [ov for _m, ov, _r in d])
        return out

    def block_statuses(self, slug: str) -> dict[str, BlockStatus]:
        """Block id -> overlay status for one document (cached)."""
        if slug not in self.paths.list_slugs():
            raise NotFound(slug)
        if not self.data.scored(slug):
            return {}  # not scored yet (or by another algo version): nothing to derive
        out: dict[str, BlockStatus] = self._derived_view(
            "statuses", slug, lambda d: {ov.id: ov.status for _m, ov, _r in d}
        )
        return out

    def _learning_use(self, slug: str, block_id: str) -> LearningUse:
        cf = self.data.clean_file(slug)
        prov = cf.learning_snapshot if cf is not None else "baseline"
        if cf is None:
            return LearningUse(provenance=prov)
        for e in cf.blocks:
            if e.block_id == block_id:
                return LearningUse(
                    provenance=prov, learned_rules=list(e.learned_rules), few_shot=list(e.few_shot)
                )
        return LearningUse(provenance=prov)

    def _card_context(
        self, slug: str, derived: Sequence[tuple[Block, Block, Derived]]
    ) -> _CardContext:
        return _CardContext(
            titles=section_titles(ov for _m, ov, _r in derived),
            captions=self.data.figure_captions(slug),
        )

    def _item(self, ov: Block, r: Derived, card: _CardContext) -> QueueItem:
        why = why_items(ov, r.stale_reason, LearningUse())
        caption = card.captions.get(ov.figure_id) if ov.figure_id is not None else None
        return QueueItem(
            block_id=ov.id,
            doc_id=ov.doc_id,
            page=ov.page,
            type=ov.type,
            confidence=ov.confidence,
            status=ov.status,
            has_numeric_spec=ov.has_numeric_spec,
            reasons=_reasons(why),
            stale_doc=False,
            section_title=card.titles.get(ov.id),
            excerpt=card_excerpt(ov, caption),
            weakest_word=weakest_word(ov),
        )

    @staticmethod
    def _key(sort: QueueSort, b: Block) -> tuple[Any, ...]:
        if sort == QueueSort.by_page:
            return (ids.block_sort_key(b.id),)
        return (-1.0 if b.confidence is None else b.confidence, ids.block_sort_key(b.id))

    def _scan(
        self,
        cur: Cursor,
        *,
        sort: QueueSort | None = None,
        view: float | None = None,
        doc: str | None = None,
    ) -> _Scan:
        sort = sort if sort is not None else cur.sort
        view = view if view is not None else cur.view_threshold
        doc = doc if doc is not None else cur.doc_filter
        selected = set(self.data.selection().block_ids)
        counts = ReviewCounts()
        entries: list[_Entry] = []
        for slug in self._ready_docs(doc):
            scope = self.data.scope_ids(slug, selected)
            derived = self._derive_doc(slug)
            card = self._card_context(slug, derived)
            for _machine, ov, r in derived:
                if ov.id not in scope or ov.type in (BlockType.header, BlockType.footer):
                    continue
                counts.in_scope += 1
                st = ov.status
                if st == BlockStatus.approved:
                    counts.approved += 1
                elif st == BlockStatus.edited:
                    counts.edited += 1
                elif st == BlockStatus.flagged:
                    counts.flagged_open += 1
                elif st == BlockStatus.auto_approved:
                    counts.auto_approved += 1
                elif st == BlockStatus.queued:
                    counts.queued += 1
                elif st == BlockStatus.rejected:
                    counts.rejected += 1
                if r.skipped and st in (BlockStatus.queued, BlockStatus.auto_approved):
                    counts.skipped += 1
                shown = st == BlockStatus.queued or (
                    st == BlockStatus.auto_approved
                    and view is not None
                    and ov.confidence is not None
                    and ov.confidence < view
                )
                if not shown:
                    continue
                if sort == QueueSort.figures_only and ov.type != BlockType.figure:
                    continue
                item = self._item(ov, r, card)
                entries.append(
                    _Entry(
                        self._key(
                            QueueSort.worst_first if sort == QueueSort.figures_only else sort, ov
                        ),
                        item,
                    )
                )
        entries.sort(key=lambda e: e.key)
        counts.pending = len(entries)
        return _Scan(entries, counts)

    def _readiness(self) -> list[DocReadiness]:
        return [self.data.readiness(s) for s in self.paths.list_slugs()]

    def _stale_docs(self) -> set[str]:
        return {d.doc_id for d in self._readiness() if d.state == "ready" and d.stale}

    # -- queue / cursor ---------------------------------------------------------------------

    def queue(
        self,
        sort: QueueSort | None,
        view_threshold: float | None,
        doc: str | None,
        limit: int,
        offset: int,
    ) -> QueuePage:
        cur = self.cursor()
        scan = self._scan(cur, sort=sort, view=view_threshold, doc=doc)
        stale = self._stale_docs()
        for e in scan.pending:
            e.item.stale_doc = e.item.doc_id in stale
        page = scan.pending[offset : offset + limit]
        return QueuePage(
            items=[e.item for e in page],
            total=len(scan.pending),
            counts=scan.counts,
            docs=self._readiness(),
            cursor=cur,
        )

    def cursor(self) -> Cursor:
        return self.store.get_cursor() or Cursor()

    def set_cursor(self, c: Cursor, request_id: str) -> Cursor:
        prev = self.store.action_by_request(
            request_id, (ActionKind.cursor, ActionKind.threshold_view)
        )
        if prev is not None:
            return Cursor.model_validate(prev.payload["_outcome"])
        old = self.cursor()
        new = c.model_copy(update={"trail": c.trail[-TRAIL_MAX:]})
        view_changed = new.view_threshold != old.view_threshold
        with self.store.tx():
            aid = self.store.next_action_id()
            self.store.append_action(
                ActionKind.threshold_view if view_changed else ActionKind.cursor,
                "verify",
                payload={
                    "cursor": new.model_dump(mode="json"),
                    "_outcome": new.model_dump(mode="json"),
                },
                request_id=request_id,
                action_id=aid,
            )
            if view_changed and new.view_threshold is not None:
                self.store.add_threshold_history(
                    "view", old.view_threshold, new.view_threshold, "slider", aid
                )
            self.store.set_cursor(new, aid)
        return new

    # -- detail -----------------------------------------------------------------------------

    def _find(self, block_id: str) -> tuple[str, Block, Block, Derived]:
        try:
            slug, _page, _n = ids.parse_block_id(block_id)
        except ValueError as exc:
            raise NotFound(block_id) from exc
        if slug not in self.paths.list_slugs() or not self.data.scored(slug):
            raise NotFound(block_id)
        for machine, ov, r in self._derive_doc(slug):
            if machine.id == block_id:
                return slug, machine, ov, r
        raise NotFound(block_id)

    def _in_scope(self, slug: str, block_id: str) -> bool:
        return block_id in self.data.scope_ids(slug)

    def _page_ref(self, slug: str, page: int) -> PageRef:
        doc = self.data.document(slug)
        if doc.kind == DocKind.docx:
            return PageRef(
                doc_id=slug,
                page=page,
                width=0.0,
                height=0.0,
                render_url=None,
                source_url=f"/api/docs/{slug}/source",
            )
        w = h = 0.0
        try:
            from manuallabor.parse.pdf_pymupdf import open_pdf

            with open_pdf(self.paths.source(doc.filename)) as d:
                r = d[page - 1].rect
                w, h = float(r.width), float(r.height)
        except Exception as exc:  # the card still renders; a zero size is visible, not silent
            logging.getLogger(__name__).warning(
                "page size unavailable for %s page %d: %s", slug, page, exc
            )
        return PageRef(
            doc_id=slug,
            page=page,
            width=w,
            height=h,
            render_url=f"/api/docs/{slug}/pages/{page}.png",
            source_url=f"/api/docs/{slug}/source",
        )

    def detail(self, block_id: str) -> BlockDetail:
        slug, machine, ov, r = self._find(block_id)
        if not self._in_scope(slug, block_id):
            raise OutOfScope(block_id)
        learning = self._learning_use(slug, block_id)
        arts = self.data.articles_of(slug, block_id)
        figs = []
        if self.figures is not None:
            seen: set[str] = set()
            for a in arts:
                for item in self.figures.rail(a):
                    if item.figure_id not in seen:
                        seen.add(item.figure_id)
                        figs.append(item)
        targets = {block_id} | ({ov.figure_id} if ov.figure_id else set())
        flags = [f for f in self.store.flags() if f.target_id in targets]
        return BlockDetail(
            block=ov,
            article_ids=arts,
            page=self._page_ref(slug, ov.page),
            why=why_items(ov, r.stale_reason, learning),
            parser_texts=dict(sorted(ov.raw_text_by_parser.items())),
            learning=learning,
            history=self.store.decisions(block_id=block_id),
            figures=figs,
            flags=flags,
        )

    # -- actions ----------------------------------------------------------------------------

    def act(self, a: ReviewActionIn) -> ReviewActionOut:
        prev = self.store.action_by_request(a.request_id, _ACT_KINDS)
        if prev is not None:
            return ReviewActionOut.model_validate(prev.payload["_outcome"])
        if a.kind == "back":
            return self._back(a)
        if a.block_id is None:
            raise InvalidOp("block_id is required")
        slug, machine, ov, r = self._find(a.block_id)
        if not self._in_scope(slug, a.block_id):
            raise OutOfScope(a.block_id)
        if a.kind == "edit":
            return self._edit(a, slug, machine, ov, r)
        return self._simple(a, slug, machine, ov, r)

    def _decision_fields(self, machine: Block, slug: str) -> dict[str, Any]:
        cfg = self.paths.load_config()
        return {
            "score": machine.confidence,
            "threshold": cfg.threshold_for(slug),
            "signals": list(machine.signals),
            "raw_sha256": sha_text(machine.raw_text),
            "shown_text_sha256": sha_text(display_text(machine)),
            "provenance": self._provenance(slug),
        }

    def _example(
        self,
        machine: Block,
        slug: str,
        action: str,
        *,
        clean_after: str | None,
        faith_passed: bool | None,
        diff: list[DiffOp] | None,
        flag_category: str | None = None,
        flag_note: str | None = None,
        human_edit: bool = False,
    ) -> dict[str, Any]:
        cf = self.data.clean_file(slug)
        entry = None
        if cf is not None:
            for e in cf.blocks:
                if e.block_id == machine.id:
                    entry = {
                        "passes": list(e.passes),
                        "residual": list(e.residual),
                        "learned_rules": list(e.learned_rules),
                        "few_shot": list(e.few_shot),
                    }
        cfg = self.paths.load_config()
        return {
            "block_id": machine.id,
            "doc_id": slug,
            "block_type": machine.type.value,
            "raw_text": machine.raw_text,
            "raw_source": machine.raw_source,
            "raw_text_by_parser": dict(sorted(machine.raw_text_by_parser.items())),
            "clean_before": machine.clean_text,
            "clean_after": clean_after,
            "signals": [s.model_dump(mode="json") for s in machine.signals],
            "score": machine.confidence,
            "threshold": cfg.threshold,
            "has_numeric_spec": machine.has_numeric_spec,
            "action": action,
            "flag_category": flag_category,
            "flag_note": flag_note,
            "faith_passed": faith_passed,
            "diff": None if diff is None else [d.model_dump(mode="json") for d in diff],
            "learning_provenance": self._provenance(slug),
            "cleanup_entry": entry,
            "figure": None,
            "regroup": None,
            "proposal": None,
            "human_edit": human_edit,
        }

    def _edit(
        self, a: ReviewActionIn, slug: str, machine: Block, ov: Block, r: Derived
    ) -> ReviewActionOut:
        if machine.type == BlockType.figure:
            raise InvalidOp("figure blocks cannot be edited")
        text = a.text
        if text is None or text.strip() == "":
            raise InvalidOp("edit text must not be empty")
        chk = check_human_edit(self.data, machine, text)
        if not chk.passed and not a.confirm_content_change:
            raise EditConflictError(
                EditConflict(
                    violations=chk.result.violations,
                    numeric_changes=chk.numeric_changes,
                    diff=chk.result.diff,
                )
            )
        return self._write(
            a,
            slug,
            machine,
            DecisionAction.edit,
            edited_text=text,
            faith_passed=chk.passed,
            diff=chk.result.diff,
            human_edit=not chk.passed,
        )

    def _simple(
        self, a: ReviewActionIn, slug: str, machine: Block, ov: Block, r: Derived
    ) -> ReviewActionOut:
        action = DecisionAction(a.kind)
        if action == DecisionAction.flag:
            if a.flag is None:
                raise InvalidOp("flag details are required")
            target = a.flag.target_id or machine.id
            if target not in (machine.id, machine.figure_id):
                raise InvalidOp("flag target does not belong to the block")
            return self._write(a, slug, machine, action, flag=a.flag, target=target)
        if action == DecisionAction.approve and r.edit is not None:
            # K then A: the approval applies to the human edit, which stays the text source
            return self._write(a, slug, machine, action, shown_text=r.edit.decision.edited_text)
        return self._write(a, slug, machine, action)

    def _write(
        self,
        a: ReviewActionIn,
        slug: str,
        machine: Block,
        action: DecisionAction,
        *,
        edited_text: str | None = None,
        faith_passed: bool | None = None,
        diff: list[DiffOp] | None = None,
        flag: Any = None,
        target: str | None = None,
        human_edit: bool = False,
        kind: ActionKind | None = None,
        screen: str = "verify",
        source: str = "human",
        proposal: dict[str, Any] | None = None,
        resolution: str | None = None,
        keep_proposal: str | None = None,
        payload_extra: dict[str, Any] | None = None,
        shown_text: str | None = None,
    ) -> ReviewActionOut:
        base = self._decision_fields(machine, slug)
        if shown_text is not None:  # the text the reviewer approved (an earlier edit)
            base["shown_text_sha256"] = sha_text(shown_text)
        # numbers are verified by an approval (or an accepted proposal), never by an edit
        numeric_ok = machine.has_numeric_spec and (
            action == DecisionAction.approve or kind == ActionKind.proposal_accept
        )
        kind = kind if kind is not None else ActionKind(action.value)
        with self.store.tx():
            aid = self.store.next_action_id()
            seq = self.store.next_decision_seq()
            resolved_ids: list[str] = []
            if action in (DecisionAction.approve, DecisionAction.edit):
                for t in {machine.id, machine.figure_id or machine.id}:
                    resolved_ids.extend(f.id for f in self.store.open_flags_for(t))
            example = self._example(
                machine,
                slug,
                action.value,
                clean_after=edited_text
                if action == DecisionAction.edit
                else (shown_text if shown_text is not None else display_text(machine)),
                faith_passed=faith_passed,
                diff=diff,
                flag_category=None if flag is None else flag.category.value,
                flag_note=None if flag is None else flag.note,
                human_edit=human_edit,
            )
            example["proposal"] = proposal
            # rows that reference the action id first (the FKs are deferred), the action row
            # last: its payload stores the outcome, which needs the post-write state
            new_flag: Flag | None = None
            flag_id: str | None = None
            if flag is not None:
                new_flag = self.store.add_flag(
                    target_id=target or machine.id,
                    category=flag.category,
                    note=flag.note,
                    action_id=aid,
                )
                flag_id = new_flag.id
            for fid in resolved_ids:
                self.store.resolve_flag(fid, resolution or f"superseded by action {aid}", aid)
            self.store.add_decision(
                seq=seq,
                action_id=aid,
                block_id=machine.id,
                doc_id=slug,
                action=action,
                score=base["score"],
                threshold=base["threshold"],
                signals=base["signals"],
                edited_text=edited_text,
                flag_id=flag_id,
                raw_sha256=base["raw_sha256"],
                shown_text_sha256=base["shown_text_sha256"],
                faith_passed=faith_passed,
                human_edit_diff=diff if action == DecisionAction.edit else None,
                numbers_verified=numeric_ok,
                provenance=base["provenance"],
                source=source,
            )
            out = self._outcome(a, aid, slug, machine, new_flag)
            self.store.append_action(
                kind,
                screen,
                target_id=machine.id,
                doc_id=slug,
                payload={
                    "text": edited_text,
                    "flag_id": flag_id,
                    "resolved_flags": resolved_ids,
                    **(payload_extra or {}),
                    "_outcome": out.model_dump(mode="json"),
                },
                example=example,
                before=display_text(machine),
                after=edited_text if action == DecisionAction.edit else None,
                provenance=base["provenance"],
                request_id=a.request_id,
                action_id=aid,
            )
            if action in (DecisionAction.approve, DecisionAction.edit):
                self._supersede_pending(
                    {machine.id, machine.figure_id or machine.id}, aid, keep_proposal
                )
            if screen == "verify":  # the Agent screen never moves the Verify cursor
                self.store.set_cursor(out.cursor, aid)
        return out

    def _supersede_pending(self, targets: set[str], action_id: int, keep: str | None) -> None:
        """A reviewer decision on the target settles its pending proposals (module 10)."""
        for p in self.store.proposals(status=ProposalStatus.pending, target_ids=targets):
            if p.id != keep:
                self.store.set_proposal(
                    p.model_copy(update={"status": ProposalStatus.superseded}), action_id
                )

    def apply_agent_edit(
        self,
        block_id: str,
        text: str,
        proposal: Proposal,
        request_id: str,
        *,
        bulk: bool = False,
    ) -> ReviewActionOut:
        """Record an accepted agent proposal as an `edit` decision with source `agent`
        (design 10 section 3.9). The faithfulness verdict stored is the strict check against raw
        text; a content change that the independent readers attest is recorded exactly like a
        confirmed human edit (`faith_passed` False, diff stored)."""
        prev = self.store.action_by_request(request_id)
        if prev is not None:
            return ReviewActionOut.model_validate(prev.payload["_outcome"])
        slug, machine, _ov, _r = self._find(block_id)
        if not self._in_scope(slug, block_id):
            raise OutOfScope(block_id)
        if machine.type == BlockType.figure:
            raise InvalidOp("figure blocks cannot be edited")
        chk = check_human_edit(self.data, machine, text)
        a = ReviewActionIn(kind="edit", block_id=block_id, text=text, request_id=request_id)
        return self._write(
            a,
            slug,
            machine,
            DecisionAction.edit,
            edited_text=text,
            faith_passed=chk.passed,
            diff=chk.result.diff,
            human_edit=not chk.passed,
            kind=ActionKind.proposal_accept,
            screen="agent",
            source="agent",
            proposal=proposal.model_dump(mode="json"),
            resolution=f"proposal {proposal.id} accepted",
            keep_proposal=proposal.id,
            payload_extra={"proposal_id": proposal.id, "bulk": bulk},
        )

    def apply_proposal_edit(
        self,
        block_id: str,
        text: str,
        proposal: Proposal,
        confirm_content_change: bool,
        request_id: str,
    ) -> ReviewActionOut:
        """The reviewer's own text in place of an agent proposal: the human edit path (the
        faithfulness check, `EditConflictError` unless confirmed), recorded as `proposal_edit`
        on the agent screen with source `human`."""
        prev = self.store.action_by_request(request_id)
        if prev is not None:
            return ReviewActionOut.model_validate(prev.payload["_outcome"])
        slug, machine, _ov, _r = self._find(block_id)
        if not self._in_scope(slug, block_id):
            raise OutOfScope(block_id)
        if machine.type == BlockType.figure:
            raise InvalidOp("figure blocks cannot be edited")
        if text.strip() == "":
            raise InvalidOp("edit text must not be empty")
        chk = check_human_edit(self.data, machine, text)
        if not chk.passed and not confirm_content_change:
            raise EditConflictError(
                EditConflict(
                    violations=chk.result.violations,
                    numeric_changes=chk.numeric_changes,
                    diff=chk.result.diff,
                )
            )
        a = ReviewActionIn(
            kind="edit",
            block_id=block_id,
            text=text,
            confirm_content_change=confirm_content_change,
            request_id=request_id,
        )
        return self._write(
            a,
            slug,
            machine,
            DecisionAction.edit,
            edited_text=text,
            faith_passed=chk.passed,
            diff=chk.result.diff,
            human_edit=not chk.passed,
            kind=ActionKind.proposal_edit,
            screen="agent",
            source="human",
            proposal=proposal.model_dump(mode="json"),
            resolution=f"proposal {proposal.id} edited",
            keep_proposal=proposal.id,
            payload_extra={"proposal_id": proposal.id},
        )

    def _outcome(
        self, a: ReviewActionIn, aid: int, slug: str, machine: Block, new_flag: Flag | None
    ) -> ReviewActionOut:
        """The result of an action as it will be after commit (called inside the tx)."""
        cur = self.cursor()
        decs = self._decisions_by_block(slug).get(machine.id, [])
        flags = self._flags()
        r = derive(machine, decs, flags)
        ov = overlay_block(machine, r)
        scan = self._scan(cur)
        key = self._key(
            QueueSort.worst_first if cur.sort == QueueSort.figures_only else cur.sort, ov
        )
        nxt: _Entry | None = None
        for e in scan.pending:
            if e.key > key:
                nxt = e
                break
        if nxt is None and scan.pending:
            nxt = scan.pending[0]
        trail = [*cur.trail, machine.id][-TRAIL_MAX:]
        new_cur = cur.model_copy(
            update={"current_block_id": nxt.item.block_id if nxt else None, "trail": trail}
        )
        last = self.store.decisions(block_id=machine.id)
        return ReviewActionOut(
            action_id=aid,
            decision=last[-1] if last else None,
            flag=new_flag,
            block_status=ov.status,
            next=nxt.item if nxt else None,
            cursor=new_cur,
            counts=scan.counts,
        )

    def _back(self, a: ReviewActionIn) -> ReviewActionOut:
        cur = self.cursor()
        trail = list(cur.trail)
        current = cur.current_block_id
        if trail:
            current = trail.pop()
        new_cur = cur.model_copy(update={"current_block_id": current, "trail": trail})
        item: QueueItem | None = None
        status: BlockStatus | None = None
        if current is not None:
            try:
                slug, _m, ov, r = self._find(current)
                card = self._card_context(slug, self._derive_doc(slug))
                item, status = self._item(ov, r, card), ov.status
            except NotFound:
                item = None
        with self.store.tx():
            aid = self.store.next_action_id()
            out = ReviewActionOut(
                action_id=aid,
                decision=None,
                flag=None,
                block_status=status,
                next=item,
                cursor=new_cur,
                counts=self._scan(new_cur).counts,
            )
            self.store.append_action(
                ActionKind.back,
                "verify",
                target_id=current,
                payload={"to": current, "_outcome": out.model_dump(mode="json")},
                request_id=a.request_id,
                action_id=aid,
            )
            self.store.set_cursor(new_cur, aid)
        return out

    # -- flags ------------------------------------------------------------------------------

    def flags(self, status: FlagStatus | None) -> list[Flag]:
        return self.store.flags(status)

    def resolve_flag(self, flag_id: str, resolution: str, request_id: str) -> Flag:
        prev = self.store.action_by_request(request_id, (ActionKind.resolve_flag,))
        if prev is not None:
            return Flag.model_validate(prev.payload["_outcome"])
        flag = self.store.get_flag(flag_id)
        if flag is None:
            raise NotFound(flag_id)
        if flag.status != FlagStatus.open:
            raise InvalidOp(f"{flag_id} is already resolved")
        with self.store.tx():
            aid = self.store.next_action_id()
            done = self.store.resolve_flag(flag_id, resolution, aid)
            self.store.append_action(
                ActionKind.resolve_flag,
                "verify",
                target_id=flag.target_id,
                payload={
                    "flag_id": flag_id,
                    "resolution": resolution,
                    "_outcome": done.model_dump(mode="json"),
                },
                request_id=request_id,
                action_id=aid,
            )
        return done

    # -- pages ------------------------------------------------------------------------------

    def render_page(self, slug: str, page: int, dpi: int) -> Path:
        if slug not in self.paths.list_slugs():
            raise NotFound(slug)
        doc = self.data.document(slug)
        if doc.kind == DocKind.docx:
            raise NoPageRender(slug)
        if not 1 <= page <= doc.page_count:
            raise NotFound(f"{slug} page {page}")
        dpi = max(36, min(int(dpi), 300))
        from manuallabor.parse.render import render_page_png

        out = self.paths.doc(slug).page_view(page, dpi)
        render_page_png(self.paths.source(doc.filename), page - 1, dpi, out)
        return out

    def page_blocks(self, slug: str, page: int) -> list[dict[str, Any]]:
        if slug not in self.paths.list_slugs():
            raise NotFound(slug)
        if not self.data.scored(slug):
            return []

        def index(derived: Sequence[tuple[Block, Block, Derived]]) -> dict[int, list[Any]]:
            out: dict[int, list[Any]] = {}
            for _m, ov, _r in derived:
                out.setdefault(ov.page, []).append(
                    {
                        "block_id": ov.id,
                        "bbox": ov.bbox,
                        "type": ov.type.value,
                        "status": ov.status.value,
                    }
                )
            return out

        by_page: dict[int, list[dict[str, Any]]] = self._derived_view("pages", slug, index)
        return [dict(r) for r in by_page.get(page, [])]

    def titles(self, block_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Where each block is, for naming it elsewhere (Export blockers): document, page, type
        and the section heading above it, the same fields a queue card carries, in the order
        asked (once per id). Unknown ids and documents not scored yet are left out."""
        ready = set(self._ready_docs())
        wanted: dict[str, list[str]] = {}
        for b in block_ids:
            try:
                slug = ids.parse_block_id(b)[0]
            except ValueError:
                continue
            if slug in ready:
                wanted.setdefault(slug, []).append(b)
        found: dict[str, dict[str, Any]] = {}
        for slug, bids in sorted(wanted.items()):
            rows: dict[str, dict[str, Any]] = self._derived_view(
                "titles",
                slug,
                lambda d, slug=slug: _title_rows(slug, [ov for _m, ov, _r in d]),
            )
            found.update({b: dict(rows[b]) for b in bids if b in rows})
        return [found[b] for b in dict.fromkeys(block_ids) if b in found]

    # -- queries used by module 11 / status ---------------------------------------------------

    def decisions_json(self) -> str:
        return json.dumps([d.model_dump(mode="json") for d in self.store.decisions()])


__all__ += ["Decision", "Signal"]
