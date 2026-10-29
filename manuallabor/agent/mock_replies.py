"""The mock agent model (design 10 section 3.4). Standard library only: it is imported by
`providers.mock` at import time.

It parses the `<item>` bundle of the user message and answers deterministically: for text it
proposes the first independent reader's text, for a table the rows of the first alternative
reader, for choices the first candidate. Real models are never this agreeable; the point is a
stable reply whose rechecks the tests can reason about."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

_ITEM_RE = re.compile(r"<item>(.*)</item>", re.S)


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def mock_agent_reply(messages: Sequence[Any]) -> str:
    users = [m for m in messages if m.role == "user"]
    content = users[-1].content if users else ""
    m = _ITEM_RE.search(content)
    if m is None:
        return json.dumps({"action": "none", "rationale": "mock: no item"})
    item = json.loads(m.group(1))
    cat = item["flag"]["category"]
    readers: dict[str, str] = item["readers"]["raw_text_by_parser"]
    raw_source = item["readers"]["raw_source"]
    raw = item["readers"]["raw_text"]
    alt = [k for k in sorted(readers) if k != raw_source]
    out: dict[str, Any] = {"action": "propose", "rationale": f"mock: {cat}"}
    if cat == "wrong_text":
        pick = next((k for k in alt if readers[k].strip() != raw.strip()), None)
        text = readers[pick] if pick is not None else _ws(raw)
        src = pick if pick is not None else raw_source
        out["proposal_text"] = text if text.strip() else raw
        out["evidence"] = [{"source": src, "span": (text if text.strip() else raw)[:40].strip()}]
    elif cat == "table_structure":
        pick = alt[0] if alt else raw_source
        text = readers.get(pick, raw)
        rows = [
            [c.strip() for c in line.split("|")] for line in text.split("\n") if line.strip()
        ] or [[_ws(raw)]]
        width = max(len(r) for r in rows)
        out["cells"] = [r + [""] * (width - len(r)) for r in rows]
        out["header_rows"] = 0
        out["evidence"] = [{"source": pick, "span": text[:40].strip() or "table"}]
    else:
        cands = item.get("candidates") or []
        if not cands:
            return json.dumps({"action": "none", "rationale": f"mock: no candidate for {cat}"})
        first = cands[0]
        cid = first.get("id") or first.get("slug")
        out["choice"] = cid
        out["evidence"] = [{"source": "candidate", "span": str(cid)}]
    return json.dumps(out, sort_keys=True, ensure_ascii=False)
