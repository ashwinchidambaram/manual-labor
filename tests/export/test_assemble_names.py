"""Article file names (design 11 section 15): `articles/<doc slug>--<topic slug>.md`, where the
topic slug is made from the topic's shown title (design 04 section 3.4.1), never a bare `-2`
suffix, and the same inputs give the same names on every export."""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Sequence

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.llm import Message
from manuallabor.grouping.pipeline import group_document
from manuallabor.providers import ListSink
from tests.export.synth import SLUG, blk, run, synth_inputs
from tests.grouping.conftest import doc_of, provider_set


def _blocks() -> list[Block]:
    out: list[Block] = []
    for p in range(1, 7):
        out.append(
            blk(1, f"{p}. Section {p}", type=BlockType.heading, page=p, reading_order=p * 1000 + 1)
        )
        out += [
            blk(
                n,
                f"Words about part {p} item {n} torque {n * p} N·m.",
                page=p,
                reading_order=p * 1000 + n,
            )
            for n in range(2, 14)
        ]
    return out


def _small_model(messages: Sequence[Message]) -> str:
    """A small model: every cluster named alike in lower case, with a slug unrelated to it."""
    data = next(m.content for m in messages if m.role == "user")
    if '"assign_stragglers"' in data:
        payload = json.loads(data[len("<input>") : -len("</input>")])
        picks = [
            {"block_id": b["block_id"], "topic": b["candidates"][0]} for b in payload["blocks"]
        ]
        return json.dumps({"assignments": picks})
    return json.dumps(
        {"title": "connector data", "slug": "belt-path-3-1-harness-3-2-4-drive-train"}
    )


def _export_names() -> list[tuple[str, str]]:
    blocks = _blocks()
    gf = group_document(
        doc_of(blocks, SLUG), blocks, provider_set(ListSink(), grouping=_small_model)
    )
    inp = synth_inputs(blocks)
    inp.docs[SLUG] = dataclasses.replace(inp.docs[SLUG], groups=gf)
    return [(a.path, a.title) for a in run(inp).articles]


def test_article_files_read_as_the_topic_title() -> None:
    names = _export_names()
    assert len(names) >= 2, names
    paths = [p for p, _ in names]
    assert len(set(paths)) == len(paths)
    for path, title in names:
        m = re.fullmatch(rf"articles/{SLUG}--([a-z0-9-]+)\.md", path)
        assert m, path
        topic = m.group(1)
        # the file name is the title's own words: no model slug, no bare counter suffix
        assert topic.startswith("connector-data"), (path, title)
        assert "belt-path" not in topic, path
        qualifier = title.removeprefix("Connector Data").strip(" ()")
        expected = "connector-data" + (
            "-" + re.sub(r"[^a-z0-9]+", "-", qualifier.lower()).strip("-") if qualifier else ""
        )
        assert topic == expected, (path, title)
    assert names[0][1] == "Connector Data"
    assert all(t.startswith("Connector Data (") for _, t in names[1:])


def test_article_names_are_stable_across_re_exports() -> None:
    assert _export_names() == _export_names()
