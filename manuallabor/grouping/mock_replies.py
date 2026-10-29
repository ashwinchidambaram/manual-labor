"""Canned grouping replies for MockProvider. Imports only the standard library and two tiny
manuallabor helpers, so providers/mock.py can register it without loading scipy."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from manuallabor.contracts.llm import Message
from manuallabor.ids import slugify
from manuallabor.parse.text import collapse_ws

_INPUT_RE = re.compile(r"<input>(.*)</input>", re.S)
_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+")


def _payload(messages: Sequence[Message]) -> dict[str, Any]:
    for m in messages:
        if m.role == "user":
            found = _INPUT_RE.search(m.content)
            if found:
                data = json.loads(found.group(1))
                if isinstance(data, dict):
                    return data
    return {}


def mock_grouping_reply(messages: Sequence[Message]) -> str:
    """Valid-by-construction answers: the most frequent heading names a topic; a straggler goes
    to its best candidate."""
    data = _payload(messages)
    kind = data.get("kind")
    if kind == "assign_stragglers":
        out = []
        for b in data.get("blocks", []):
            cands = b.get("candidates") or ["unassigned"]
            out.append({"block_id": b["block_id"], "topic": cands[0]})
        return json.dumps({"assignments": out}, sort_keys=True)
    title = ""
    heads = data.get("headings") or []
    if heads:
        title = collapse_ws(_NUMBER_RE.sub("", str(heads[0])))
    if not title:
        blocks = data.get("blocks") or []
        first = str(blocks[0]).split(":", 1)[-1] if blocks else ""
        title = " ".join(collapse_ws(first).split()[:4])
    title = title[:80].strip() or "Topic"
    slug = slugify(title, 40)
    if slug == "unassigned" or slug == "front-matter" or slug.startswith("pages-"):
        slug = ("topic-" + slug)[:40].strip("-")
    return json.dumps({"slug": slug, "title": title}, sort_keys=True)
