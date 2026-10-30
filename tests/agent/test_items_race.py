"""`GET /api/agent/items` while a flag is resolved between its two reads (Playwright run,
2026-10-30: `KeyError: 'flag-000002'` at `flags[it.flag_id]`). The eligible items and the open
flags were read separately; an item whose flag is no longer open is not listed."""

from __future__ import annotations

from typing import Any

import pytest

import manuallabor.agent.service as service_mod
from tests.agent.conftest import AEnv


def test_items_skip_a_flag_resolved_between_the_two_reads(
    aenv: AEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    gone, kept = aenv.seed([0, 1])
    real = service_mod.eligible_items

    def racing(*a: Any, **k: Any) -> Any:
        out = real(*a, **k)
        aenv.review.resolve_flag(gone, "fixed by hand", "t-resolve")  # lands between the reads
        return out

    monkeypatch.setattr(service_mod, "eligible_items", racing)
    views = aenv.agent.items()
    assert [v.flag.id for v in views] == [kept]
