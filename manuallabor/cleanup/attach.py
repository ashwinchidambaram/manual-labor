"""Figure attachment to articles (design 5). Pure given its inputs.

Rules in priority order: an explicit reference in a selected block (``see Fig. 3``) ->
caption text match within the figure's own structure section -> the figure's own article
(proximity). Human overrides apply last, on every run."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from manuallabor import ids
from manuallabor.cleanup.refs import CAPTION_NUM_RE, caption_number, find_refs, is_chaptered
from manuallabor.cleanup.types import (
    CLEANUP_ALGO_VERSION,
    EVIDENCE_TEXT_MAX,
    MATCH_MIN_TOKENS,
    STOPWORDS,
    T_MATCH,
    ArticleAttachments,
    AttachEvidence,
    AttachFile,
    Attachment,
    AttachOverride,
    Unattached,
    UnresolvedRef,
)
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import ArticleSplit, AttachRule, BlockType
from manuallabor.contracts.group import GroupsFile
from manuallabor.scoring.types import ATTACH

REF_TYPES: Final = frozenset(
    {BlockType.paragraph, BlockType.list, BlockType.heading, BlockType.table, BlockType.other}
)
MATCH_TYPES: Final = frozenset(
    {BlockType.paragraph, BlockType.list, BlockType.table, BlockType.other}
)
STRENGTH: Final = {
    AttachRule.human: 4,
    AttachRule.caption_ref: 3,
    AttachRule.caption_match: 2,
    AttachRule.proximity: 1,
    AttachRule.none: 0,
}
_CWORD_RE: Final = re.compile(r"[^\W\d_]{3,}")
_LABEL_TAIL_RE: Final = re.compile(r"^[\s.:)\-–—]*")


@dataclass(frozen=True)
class FigureInfo:
    figure_id: str
    block_id: str
    caption: str | None  # caption_original from the sidecar
    failed: bool  # extraction failed (no sidecar)


def content(s: str) -> set[str]:
    """Content words: 3+ letters, casefolded, a plural ``s`` dropped, stopwords removed."""
    out: set[str] = set()
    for w in _CWORD_RE.findall(s):
        w = w.casefold()
        stem = w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
        if w in STOPWORDS or stem in STOPWORDS:
            continue
        out.add(stem)
    return out


def caption_content(caption: str) -> set[str]:
    """content() of a caption without its label (``Figure 3.``)."""
    c = caption.strip()
    m = CAPTION_NUM_RE.match(c)
    if m is not None:
        c = _LABEL_TAIL_RE.sub("", c[m.end() :], count=1)
    return content(c)


def build_articles(
    slug: str, gf: GroupsFile, selected: set[str], split: ArticleSplit, order: Mapping[str, int]
) -> dict[str, list[str]]:
    """article id -> its selected blocks in reading order (design 5, 04 §5)."""
    if split == ArticleSplit.per_document:
        members = sorted((b for b in selected if b in order), key=lambda b: order[b])
        return {ids.article_id(slug, None): members} if members else {}
    out: dict[str, list[str]] = {}
    for t in gf.topics:
        members = sorted((b for b in t.block_ids if b in selected), key=lambda b: order[b])
        if members:
            out[ids.article_id(slug, t.slug)] = members
    return dict(sorted(out.items()))


def _ev_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s[:EVIDENCE_TEXT_MAX]


def attach_document(
    slug: str,
    blocks: Sequence[Block],
    gf: GroupsFile,
    selected: set[str],
    split: ArticleSplit,
    figures: Sequence[FigureInfo],
    overrides: Sequence[AttachOverride] = (),
    fingerprint: str = "0" * 64,
) -> AttachFile:
    order = {b.id: b.reading_order for b in blocks}
    by_id = {b.id: b for b in blocks}
    articles = build_articles(slug, gf, selected, split, order)
    art_of = {b: a for a, members in articles.items() for b in members}
    sec_of = {b: g.id for g in gf.structure for b in g.block_ids}

    live = [f for f in figures if not f.failed and f.block_id in order]
    nums = {f.figure_id: caption_number(f.caption) for f in live}
    chaptered = is_chaptered(list(nums.values()))
    by_num: dict[str, list[FigureInfo]] = {}
    for f in live:
        n = nums[f.figure_id]
        if n is not None:
            by_num.setdefault(n, []).append(f)

    att: dict[tuple[str, str], Attachment] = {}
    unresolved: dict[tuple[str, str], UnresolvedRef] = {}

    def put(article: str, a: Attachment) -> None:
        key = (article, a.figure_id)
        old = att.get(key)
        if old is None or STRENGTH[a.rule] > STRENGTH[old.rule]:
            att[key] = a

    # -- caption_ref: every referencing selected block pulls the figure into its article ----
    referenced: set[str] = set()
    sel_text = sorted(
        (by_id[b] for b in selected if b in by_id and by_id[b].type in REF_TYPES),
        key=lambda b: b.reading_order,
    )
    for b in sel_text:
        for ref in find_refs(b.raw_text, chaptered):
            cands = by_num.get(ref.number, [])
            if len(cands) > 1:
                cands = [f for f in cands if sec_of.get(f.block_id) == sec_of.get(b.id)]
                if len(cands) != 1:
                    unresolved.setdefault(
                        (b.id, ref.number),
                        UnresolvedRef(block_id=b.id, ref=ref.number, reason="ambiguous_number"),
                    )
                    continue
            if not cands:
                unresolved.setdefault(
                    (b.id, ref.number),
                    UnresolvedRef(block_id=b.id, ref=ref.number, reason="no_such_figure"),
                )
                continue
            f = cands[0]
            referenced.add(f.figure_id)
            article = art_of[b.id]
            if (article, f.figure_id) in att:
                continue  # the first referencing block in reading order is the anchor
            put(
                article,
                Attachment(
                    figure_id=f.figure_id,
                    rule=AttachRule.caption_ref,
                    confidence=ATTACH[AttachRule.caption_ref],
                    anchor_block_id=b.id,
                    evidence=AttachEvidence(block_id=b.id, text=_ev_text(ref.text)),
                ),
            )

    # -- caption_match (own section only) and proximity, for selected figures -------------
    match_blocks = [by_id[b] for b in selected if b in by_id and by_id[b].type in MATCH_TYPES]
    for f in live:
        if f.block_id not in selected:
            continue
        if f.figure_id not in referenced and f.caption:
            cap = caption_content(f.caption)
            best: tuple[float, int, str, set[str]] | None = None
            if len(cap) >= MATCH_MIN_TOKENS:
                for b in match_blocks:
                    if sec_of.get(b.id) is None or sec_of.get(b.id) != sec_of.get(f.block_id):
                        continue
                    common = cap & content(b.raw_text)
                    score = len(common) / len(cap)
                    if len(common) < MATCH_MIN_TOKENS or score < T_MATCH:
                        continue
                    cand = (-score, abs(order[b.id] - order[f.block_id]), b.id, common)
                    if best is None or cand[:3] < best[:3]:
                        best = cand
            if best is not None:
                b_id, common = best[2], best[3]
                put(
                    art_of[b_id],
                    Attachment(
                        figure_id=f.figure_id,
                        rule=AttachRule.caption_match,
                        confidence=ATTACH[AttachRule.caption_match],
                        anchor_block_id=b_id,
                        evidence=AttachEvidence(
                            block_id=b_id,
                            text=_ev_text(" ".join(sorted(common))),
                            tokens=sorted(common),
                        ),
                    ),
                )
        own = art_of[f.block_id]
        if (own, f.figure_id) not in att:
            put(
                own,
                Attachment(
                    figure_id=f.figure_id,
                    rule=AttachRule.proximity,
                    confidence=ATTACH[AttachRule.proximity],
                    anchor_block_id=f.block_id,
                    evidence=AttachEvidence(block_id=f.block_id),
                ),
            )

    # -- human overrides, in seq order, on every run ---------------------------------------
    known = {f.figure_id for f in live}
    applied = 0
    stale: list[int] = []
    for ov in sorted(overrides, key=lambda o: o.seq):
        if ov.article_id not in articles or ov.figure_id not in known:
            stale.append(ov.seq)
            continue
        applied += 1
        key = (ov.article_id, ov.figure_id)
        if ov.op == "detach":
            att.pop(key, None)
            continue
        anchor = ov.anchor_block_id if ov.anchor_block_id in order else None
        att[key] = Attachment(
            figure_id=ov.figure_id,
            rule=AttachRule.human,
            confidence=ATTACH[AttachRule.human],
            anchor_block_id=anchor,
            evidence=AttachEvidence(block_id=anchor),
        )

    fig_block = {f.figure_id: f.block_id for f in live}

    def place(a: Attachment) -> tuple[int, str]:
        anchor = a.anchor_block_id or fig_block[a.figure_id]
        return (order.get(anchor, order[fig_block[a.figure_id]]), a.figure_id)

    per_article: dict[str, list[Attachment]] = {}
    for (article, _), a in att.items():
        per_article.setdefault(article, []).append(a)
    out_articles = [
        ArticleAttachments(article_id=k, figures=sorted(v, key=place))
        for k, v in sorted(per_article.items())
    ]
    attached = {fid for (_, fid) in att}
    unattached = [
        Unattached(
            figure_id=f.figure_id,
            reason="extraction_failed"
            if f.failed or f.block_id not in order
            else ("not_selected" if f.block_id not in selected else "detached"),
        )
        for f in figures
        if f.failed or f.block_id not in order or f.figure_id not in attached
    ]
    return AttachFile(
        doc_id=slug,
        algo_version=CLEANUP_ALGO_VERSION,
        fingerprint=fingerprint,
        article_split=split,
        articles=out_articles,
        unattached=sorted(unattached, key=lambda u: ids.block_sort_key(u.figure_id)),
        unresolved_refs=sorted(
            unresolved.values(), key=lambda u: (ids.block_sort_key(u.block_id), u.ref)
        ),
        overrides_applied=applied,
        overrides_stale=stale,
    )


def figure_projection(af: AttachFile) -> dict[str, tuple[list[str], AttachRule]]:
    """figure id -> (sorted article ids, strongest rule) for the sidecar."""
    out: dict[str, tuple[list[str], AttachRule]] = {}
    for art in af.articles:
        for a in art.figures:
            arts, rule = out.get(a.figure_id, ([], AttachRule.none))
            arts.append(art.article_id)
            out[a.figure_id] = (arts, a.rule if STRENGTH[a.rule] > STRENGTH[rule] else rule)
    return {k: (sorted(v[0]), v[1]) for k, v in out.items()}
