"""Test 16 (H10): every CorruptingMockProvider mode is rejected by the faithfulness check on
every non-empty body block of 4 fixtures; the echo MockProvider control passes 100%."""

from __future__ import annotations

import pytest

from manuallabor.contracts.enums import BlockType, Task
from manuallabor.contracts.llm import Message
from manuallabor.providers import (
    RAW_CLOSE,
    RAW_OPEN,
    CorruptingMockProvider,
    ListSink,
    MockProvider,
)
from manuallabor.providers.mock import CorruptMode
from manuallabor.scoring.pipeline import score_block
from tests.scoring.conftest import Scored

FIXTURES = ("clean", "tables", "twocol", "scanned")
MODES: tuple[CorruptMode | None, ...] = ("digit", "insert", "delete", None)  # None = cycle


def _cleanup(provider: MockProvider, raw: str) -> str:
    msg = [Message(role="user", content=f"{RAW_OPEN}{raw}{RAW_CLOSE}")]
    return provider.chat(Task.cleanup, msg).text


def _targets(sp: Scored, slug: str) -> list:  # type: ignore[type-arg]
    return [
        b
        for b in sorted(sp.blocks(slug), key=lambda b: b.reading_order)
        if b.type not in (BlockType.header, BlockType.footer, BlockType.figure)
        and b.raw_text.strip()
    ]


@pytest.mark.parametrize("slug", FIXTURES)
def test_corrupting_mock_always_rejected(scoredproj: Scored, slug: str) -> None:
    ctxs = scoredproj.contexts(slug)
    blocks = _targets(scoredproj, slug)
    assert blocks
    summary = []
    for mode in MODES:
        prov = CorruptingMockProvider(mode=mode, sink=ListSink())
        failed = 0
        for b in blocks:
            clean = _cleanup(prov, b.raw_text)
            assert clean != b.raw_text
            s = score_block(b.model_copy(update={"clean_text": clean}), ctxs[b.id], threshold=0.85)
            assert s.faithfulness is not None
            assert not s.faithfulness.passed, (mode, b.id, b.raw_text, clean)
            assert s.confidence == 0.0 and s.status == "queued"
            failed += 1
        summary.append(f"{mode or 'cycle'} {failed}/{len(blocks)}")
    print(f"\n{slug}: rejected " + ", ".join(summary))


@pytest.mark.parametrize("slug", FIXTURES)
def test_echo_control_always_passes(scoredproj: Scored, slug: str) -> None:
    ctxs = scoredproj.contexts(slug)
    prov = MockProvider(sink=ListSink())
    for b in _targets(scoredproj, slug):
        clean = _cleanup(prov, b.raw_text)
        assert clean == b.raw_text
        s = score_block(b.model_copy(update={"clean_text": clean}), ctxs[b.id], threshold=0.85)
        assert s.faithfulness is not None and s.faithfulness.passed, b.id
