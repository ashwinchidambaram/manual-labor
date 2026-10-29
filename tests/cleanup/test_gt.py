"""Tests 17-21: parity with scoring, ground-truth text reproduction, numbers, the gate."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from manuallabor.cleanup.pipeline import run_clean
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockStatus, BlockType, Task
from manuallabor.project import ProjectPaths
from manuallabor.providers import CorruptingMockProvider, ListSink, MockProvider, ProviderSet
from manuallabor.scoring.faithfulness import (
    check_faithfulness,
    glyph_identity,
    hf_tables,
    is_hf_line,
)
from manuallabor.scoring.numeric import FAITH_NUM_RE
from manuallabor.scoring.types import BlockContext, ReorderEvidence
from tests.cleanup.conftest import Proj, nfc, parse_exact
from tests.conftest import ALL_FIXTURES, copy_project

TEXT_TYPES = ("paragraph", "heading", "caption", "list")


def independent_check(b: Block, ctx: BlockContext) -> list[Any]:
    """The faithfulness check called directly with the full context (not via faith_kwargs)."""
    assert b.clean_text is not None
    others = sorted(k for k in b.raw_text_by_parser if k != b.raw_source)
    r = check_faithfulness(
        b.raw_text,
        b.clean_text,
        block_type=b.type,
        table=b.table,
        hf_strings=ctx.hf_strings,
        hf_pages=ctx.hf_pages,
        variant_sources=b.raw_text_by_parser,
        raw_source=b.raw_source,
        page=b.page,
        evidence=ReorderEvidence(
            layout_risk=ctx.layout_risk, alt_texts=tuple(b.raw_text_by_parser[k] for k in others)
        ),
    )
    return list(r.violations)


# -- 17 parity ------------------------------------------------------------------------------


@pytest.mark.parametrize("slug", ALL_FIXTURES)
def test_17_parity_with_scores(cleanedproj: Proj, slug: str) -> None:
    sf = {s.block_id: s for s in cleanedproj.scores(slug).blocks}
    cf = cleanedproj.clean(slug)
    assert cf.blocks
    for e in cf.blocks:
        f = sf[e.block_id].faithfulness
        assert f is not None, e.block_id
        assert (e.faith_passed, e.alignment_ratio) == (f.passed, f.alignment_ratio), e.block_id


# -- 18 / 19 GT reproduction ----------------------------------------------------------------


def _strip_bullets(s: str) -> str:
    return "\n".join(ln[2:] if ln.startswith("• ") else ln for ln in s.split("\n"))


def test_18_hyphenated(cleanedproj: Proj) -> None:
    pairs, _ = parse_exact("clean", cleanedproj.blocks("clean"))
    hyph = [(g, b) for g, b in pairs if g["hyphenated"]]
    assert len(hyph) == 4
    for g, b in hyph:
        assert b.clean_text == nfc(g["text"]), b.id


@pytest.mark.parametrize("slug", ["clean", "twocol", "tables", "figures"])
def test_19_gt_text_rate(cleanedproj: Proj, slug: str) -> None:
    pairs, missing = parse_exact(slug, cleanedproj.blocks(slug))
    rows = [(g, b) for g, b in pairs if g["type"] in TEXT_TYPES and b.type.value in TEXT_TYPES]
    ok = 0
    bad = []
    for g, b in rows:
        have = b.clean_text or ""
        want = nfc(g["text"])
        if g["type"] == "list":
            have = _strip_bullets(have)
        if have == want:
            ok += 1
        else:
            bad.append((b.id, have, want))
    rate = ok / len(rows)
    print(
        f"\n{slug}: {ok}/{len(rows)} = {rate:.3f} reproduce GT text; "
        f"{missing} GT blocks not parse-exact"
    )
    assert rate >= 0.98, bad[:3]


# -- 20 numbers -----------------------------------------------------------------------------


def _raw_minus_hf(b: Block, ctx: BlockContext) -> str:
    tables = hf_tables(ctx.hf_strings, ctx.hf_pages)
    t = glyph_identity(b.raw_text).text
    keep = [ln for ln in t.split("\n") if not is_hf_line(ln, tables, b.page)]
    if b.type == BlockType.heading and not any(ln.strip() for ln in keep):
        return t  # a heading that reads like the running header (a title) is never emptied
    return "\n".join(keep)


@pytest.mark.parametrize("slug", ALL_FIXTURES)
def test_20_numeric_tokens_kept(cleanedproj: Proj, slug: str) -> None:
    ctxs = cleanedproj.contexts(slug)
    blocks = {b.id: b for b in cleanedproj.blocks(slug)}
    for e in cleanedproj.clean(slug).blocks:
        b = blocks[e.block_id]
        if b.type == BlockType.table and b.table is not None:
            continue  # the GFM grid: cells are compared by the check (test 9)
        want = Counter(FAITH_NUM_RE.findall(_raw_minus_hf(b, ctxs[b.id])))
        assert Counter(FAITH_NUM_RE.findall(e.clean_text)) == want, e.block_id
    if slug == "clean":
        pairs, _ = parse_exact("clean", list(blocks.values()))
        n = 0
        for g, b in pairs:
            for spec in g["numeric_specs"]:
                assert spec in (b.clean_text or ""), (b.id, spec)
                n += 1
        assert n > 0


# -- 21 gate --------------------------------------------------------------------------------


def _auto_violations(proj: Proj, slug: str) -> tuple[int, int, int]:
    ctxs = proj.contexts(slug)
    n_auto = n_viol = 0
    queued = 0
    for b in proj.blocks(slug):
        if b.type in (BlockType.header, BlockType.footer):
            continue
        queued += b.status == BlockStatus.queued
        if b.status != BlockStatus.auto_approved or b.clean_text is None:
            continue
        n_auto += 1
        n_viol += len(independent_check(b, ctxs[b.id]))
    return n_auto, n_viol, queued


@pytest.mark.parametrize("slug", ["scanned", *[s for s in ALL_FIXTURES if s != "scanned"]])
def test_21_gate_no_violation_on_auto_approved(
    cleanedproj: Proj, groupedproj: Proj, slug: str
) -> None:
    n_auto, n_viol, queued = _auto_violations(cleanedproj, slug)
    cf = cleanedproj.clean(slug)
    det_rejected = sum(1 for e in cf.blocks if e.passes_rejected)
    llm_rejected = sum(1 for e in cf.blocks if e.llm is not None and e.llm.outcome == "rejected")
    before = sum(
        1
        for b in groupedproj.blocks(slug)
        if b.status == BlockStatus.queued and b.type not in (BlockType.header, BlockType.footer)
    )
    print(
        f"\n{slug}: auto_approved with clean_text {n_auto}, violations {n_viol}; "
        f"det_rejected {det_rejected}, llm_rejected {llm_rejected}; queued {before} -> {queued}"
    )
    assert n_viol == 0
    assert n_auto > 0
    assert llm_rejected == 0  # echo mock


def test_21_gate_with_an_adversarial_llm(groupedproj: Proj, tmp_path: Path) -> None:
    """scanned.pdf cleaned by a model that corrupts every output, on every eligible block."""
    root = tmp_path / "adv"
    copy_project(groupedproj.paths.root, root)
    paths = ProjectPaths(root)
    sink = ListSink()
    by_task: dict[Task, Any] = {t: MockProvider(sink=sink) for t in Task}
    by_task[Task.cleanup] = CorruptingMockProvider(sink=sink)
    lines: list[dict[str, Any]] = []
    failed = run_clean(
        paths, only="scanned", providers=ProviderSet(by_task=by_task), llm_mode="always",
        emit=lines.append,
    )  # fmt: skip
    assert failed == []
    proj = Proj(paths)
    cf = proj.clean("scanned")
    eligible = [e for e in cf.blocks if e.llm is not None]
    rejected = [e for e in eligible if e.llm is not None and e.llm.outcome == "rejected"]
    assert eligible and len(rejected) == len(eligible)
    n_auto, n_viol, _ = _auto_violations(proj, "scanned")
    blocks = {b.id: b for b in proj.blocks("scanned")}
    for e in rejected:
        b = blocks[e.block_id]
        assert e.fallback and b.status == BlockStatus.queued
        faith = {s.name.value: s for s in b.signals}["faithfulness"]
        assert faith.value == 0.5 and faith.critical
    print(
        f"\nscanned adversarial: {len(rejected)}/{len(eligible)} corrupted LLM outputs found and "
        f"rejected; auto_approved {n_auto}, violations {n_viol}"
    )
    assert n_viol == 0
