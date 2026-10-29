"""Test 22: 1,000 cleaned blocks score in under 10 s without the verifier."""

from __future__ import annotations

import re
import time

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType
from manuallabor.scoring.pipeline import score_document
from tests.scoring.conftest import Scored

_HYPH = re.compile(r"(?<=[^\W\d_])-\n(?=[^\W\d_])")


def test_thousand_blocks(scoredproj: Scored) -> None:
    doc = scoredproj.doc("clean")
    src = [
        b
        for b in sorted(scoredproj.blocks("clean"), key=lambda b: b.reading_order)
        if b.type != BlockType.figure
    ]
    blocks: list[Block] = []
    i = 0
    while len(blocks) < 1000:
        b = src[i % len(src)]
        page, n = i // 20 + 1, i % 20 + 1
        clean = " ".join(_HYPH.sub("", b.raw_text).split())
        blocks.append(
            b.model_copy(
                update={
                    "id": f"b-clean-p{page:03d}-{n:02d}",
                    "page": page,
                    "reading_order": i,
                    "order_by_parser": {"pymupdf": n, "docling": n},
                    "clean_text": clean,
                }
            )
        )
        i += 1
    t0 = time.perf_counter()
    scores = score_document(doc, blocks, [], {}, {}, 0.85)
    elapsed = time.perf_counter() - t0
    print(f"\n1,000 blocks scored in {elapsed:.2f} s (no verifier)")
    assert len(scores) == 1000
    assert all(s.faithfulness is not None and s.faithfulness.passed for s in scores)
    assert elapsed < 10.0
