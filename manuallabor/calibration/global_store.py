"""The cross-project outcome store of one machine (design 10 section 4.4).

`$MANUALLABOR_HOME/calibration/<project_uuid>.jsonl`: one canonical line per outcome with the
score, whether it was edited, whether the block was numeric, its type, document kind and signal
values. No text, no ids, no file names; nothing leaves the machine."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from manuallabor.calibration.types import Outcome
from manuallabor.contracts.io import write_text_atomic
from manuallabor.state.learning import global_home

__all__ = ["load_global", "publish_outcomes"]


def _dir() -> Path:
    return global_home() / "calibration"


def publish_outcomes(project_uuid: str, outs: Iterable[Outcome]) -> int:
    lines = [
        json.dumps(
            {
                "score": o.score,
                "edited": o.edited,
                "numeric": o.numeric,
                "block_type": o.block_type,
                "doc_kind": o.doc_kind,
                "signals": {n: v for n, v, _c in o.signals},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for o in outs
    ]
    write_text_atomic(_dir() / f"{project_uuid}.jsonl", "".join(x + "\n" for x in lines))
    return len(lines)


def load_global(exclude_uuid: str | None = None) -> list[Outcome]:
    out: list[Outcome] = []
    d = _dir()
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.jsonl")):
        if exclude_uuid is not None and p.stem == exclude_uuid:
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if not ln.strip():
                continue
            r = json.loads(ln)
            out.append(
                Outcome(
                    block_id=f"{p.stem}:{i}",
                    raw_sha="",
                    action_id=i,
                    score=float(r["score"]),
                    numeric=bool(r["numeric"]),
                    block_type=str(r["block_type"]),
                    doc_kind=str(r["doc_kind"]),
                    edited=bool(r["edited"]),
                    source="human",
                    provenance="global",
                    signals=tuple(sorted((k, float(v), False) for k, v in r["signals"].items())),
                )
            )
    return out
