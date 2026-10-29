"""Test 16: CorruptingMockProvider is rejected on every eligible block of every fixture, in all
four modes, with and without the V2/V3 pre-filters; 0 corrupted outputs reach clean_text."""

from __future__ import annotations

from collections import Counter

import pytest

from manuallabor.cleanup.pipeline import clean_document
from manuallabor.cleanup.types import LLM_TYPES, fallback_detail
from manuallabor.providers import CorruptingMockProvider, ListSink
from manuallabor.providers.mock import CorruptMode
from manuallabor.scoring.pipeline import score_block
from tests.cleanup.conftest import Proj
from tests.cleanup.test_gt import independent_check
from tests.conftest import ALL_FIXTURES

MODES: tuple[CorruptMode | None, ...] = ("digit", "insert", "delete", None)


@pytest.mark.parametrize("slug", ALL_FIXTURES)
def test_16_corrupting_mock_always_rejected(groupedproj: Proj, slug: str) -> None:
    doc = groupedproj.doc(slug)
    raw = groupedproj.raw_blocks(slug)
    layouts = groupedproj.layouts(slug)
    ctxs = groupedproj.contexts(slug)
    selected = {b.id for b in raw}
    base, _ = clean_document(doc, raw, layouts, selected, mode="off")
    d = {e.block_id: e.clean_text for e in base}
    by_id = {b.id: b for b in raw}
    summary = []
    for prefilter in (True, False):
        for mode in MODES:
            prov = CorruptingMockProvider(mode=mode, sink=ListSink())
            entries, _ = clean_document(
                doc, raw, layouts, selected, mode="always", provider=prov, prefilter=prefilter
            )
            eligible = [e for e in entries if by_id[e.block_id].type in LLM_TYPES]
            assert eligible
            reasons: Counter[str] = Counter()
            for e in eligible:
                b = by_id[e.block_id]
                assert e.llm is not None and e.llm.outcome == "rejected", (mode, e.block_id)
                assert [r.stage for r in e.rejected] == ["llm"]
                assert e.clean_text == d[e.block_id]
                cleaned = b.model_copy(update={"clean_text": e.clean_text})
                assert independent_check(cleaned, ctxs[b.id]) == []
                s = score_block(cleaned, ctxs[b.id], threshold=0.85, fallback=fallback_detail(e))
                faith = {x.name.value: x for x in s.signals}["faithfulness"]
                assert faith.value == 0.5 and s.status == "queued"
                reasons[e.llm.reason or ""] += 1
                if not prefilter and e.llm.reason == "empty":
                    # V1 saw an empty reply (delete mode on a one-token block): V4 alone
                    # rejects it too
                    empty = b.model_copy(update={"clean_text": ""})
                    assert independent_check(empty, ctxs[b.id]) != []
            if not prefilter:
                assert set(reasons) <= {"faithfulness", "empty"}
            summary.append(
                f"{'V1-V4' if prefilter else 'V4 only'} {mode or 'cycle'}: "
                f"{sum(reasons.values())}/{len(eligible)} rejected {dict(reasons)}"
            )
    print(f"\n{slug}:\n  " + "\n  ".join(summary))
