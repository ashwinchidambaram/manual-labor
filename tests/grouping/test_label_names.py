"""Topic names after naming (design 04 section 3.4.1): case-normalised titles, slugs derived from
the shown title, and a section or page disambiguator instead of a `-2` suffix."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from manuallabor import ids
from manuallabor.contracts.llm import Message
from manuallabor.grouping.label import TopicNameInput, finalize_topic_names, title_case
from manuallabor.grouping.pipeline import check_partition, group_document
from manuallabor.grouping.types import TITLE_MAX, TOPIC_SLUG_MAX
from manuallabor.providers import ListSink
from tests.grouping.conftest import doc_of, heading, mk, provider_set


def _in(
    key: str, title: str, section: str | None = None, pages: Sequence[int] = (1,)
) -> TopicNameInput:
    return TopicNameInput(key=key, title=title, section=section, pages=tuple(pages))


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("idler", "Idler"),
        ("pulley", "Pulley"),
        ("connector data", "Connector Data"),
        ("removal of the belt", "Removal of the Belt"),
        ("of mice", "Of Mice"),
        ("  fluid   data ", "Fluid Data"),
        ("4. service intervals", "4. Service Intervals"),
        ("self-test", "Self-test"),
        # any capital means the writer chose the case: kept as written
        ("Parts List", "Parts List"),
        ("pH sensor", "pH sensor"),
        ("X200 belt path", "X200 belt path"),
    ],
)
def test_title_case_capitalises_only_all_lowercase_titles(raw: str, shown: str) -> None:
    assert title_case(raw) == shown


def test_case_insensitive_duplicate_gets_its_section_number() -> None:
    out = finalize_topic_names(
        [
            _in("c01", "connector data", "2", [2, 5]),
            _in("c02", "Connector Data", "5", [5]),
        ]
    )
    assert out == {
        "c01": ("Connector Data", "connector-data"),
        "c02": ("Connector Data (section 5)", "connector-data-section-5"),
    }


def test_same_section_falls_back_to_the_page_range() -> None:
    out = finalize_topic_names(
        [
            _in("c01", "Electrical Data", "2", [2]),
            _in("c02", "electrical data", "2", [2, 6]),
            _in("c03", "ELECTRICAL DATA", None, [7, 8, 9]),
        ]
    )
    assert out["c02"] == ("Electrical Data (pages 2, 6)", "electrical-data-pages-2-6")
    # an all-capitals title is the writer's choice and kept; it still collides case-insensitively
    assert out["c03"] == ("ELECTRICAL DATA (pages 7–9)", "electrical-data-pages-7-9")


def test_same_section_and_pages_fall_back_to_a_part_number() -> None:
    out = finalize_topic_names(
        [
            _in("c01", "Parts List", "3", [3]),
            _in("c02", "parts list", "3", [3]),
            _in("c03", "parts list", "3", [3]),
        ]
    )
    assert [out[k] for k in ("c01", "c02", "c03")] == [
        ("Parts List", "parts-list"),
        ("Parts List (part 2)", "parts-list-part-2"),
        ("Parts List (part 3)", "parts-list-part-3"),
    ]


def test_a_leading_section_number_does_not_distinguish_a_title() -> None:
    """Dana's second run (design 04 section 3.4.2): "Connector Data" and "5. Connector Data"
    were shown and exported side by side as two names for one topic."""
    out = finalize_topic_names(
        [
            _in("c01", "Connector Data", "2", [2, 5]),
            _in("c02", "4. Service Intervals", "4", [4]),
            _in("c03", "5. Connector Data", "5", [5]),
        ]
    )
    assert out == {
        "c01": ("Connector Data", "connector-data"),
        "c02": ("4. Service Intervals", "4-service-intervals"),
        "c03": ("Connector Data (section 5)", "connector-data-section-5"),
    }


def test_two_numbered_titles_alike_but_for_the_number() -> None:
    out = finalize_topic_names(
        [
            _in("c01", "5. connector data", "5", [5]),
            _in("c02", "6.1 Connector Data", "6.1", [6]),
            _in("c03", "6.2. Connector data", "6.1", [6]),
        ]
    )
    assert out["c01"] == ("5. Connector Data", "5-connector-data")
    assert out["c02"] == ("Connector Data (section 6.1)", "connector-data-section-6-1")
    # same section and page as c02: the part number tells it apart
    assert out["c03"] == ("Connector data (part 3)", "connector-data-part-3")


def test_a_numbered_title_alone_is_kept_and_numbers_inside_words_are_not_stripped() -> None:
    out = finalize_topic_names(
        [
            _in("c01", "X200 Belt Path", "1", [1]),
            _in("c02", "4WD Drive", "2", [2]),
            _in("c03", "12 Volt Supply", "3", [3]),
            _in("c04", "Volt Supply", "4", [4]),
            _in("c05", "Belt Path", "5", [5]),
        ]
    )
    assert out["c01"] == ("X200 Belt Path", "x200-belt-path")
    assert out["c02"] == ("4WD Drive", "4wd-drive")
    # a section number has a dot ("5.", "5.1"): "12 Volt Supply" is not "Volt Supply"
    assert out["c03"] == ("12 Volt Supply", "12-volt-supply")
    assert out["c04"] == ("Volt Supply", "volt-supply")
    # "X200 " is not a section number: "Belt Path" is a different title
    assert out["c05"] == ("Belt Path", "belt-path")


def test_a_measurement_is_not_a_section_number() -> None:
    """Review of the change: "2.5 Inch Drive Bay" and "3.5 Inch Drive Bay" are different
    topics; a dotted number without a trailing dot is a section number only when it is the
    topic's own section."""
    out = finalize_topic_names(
        [
            _in("c01", "2.5 Inch Drive Bay", "4", [5]),
            _in("c02", "3.5 Inch Drive Bay", "4", [6]),
            _in("c03", "1.5 Litre Engine", "2", [2]),
            _in("c04", "2.0 Litre Engine", "2", [2]),
            _in("c05", "3.1 Belt Path", "3.1", [3]),
            _in("c06", "Belt Path", "4", [4]),
        ]
    )
    assert out["c01"] == ("2.5 Inch Drive Bay", "2-5-inch-drive-bay")
    assert out["c02"] == ("3.5 Inch Drive Bay", "3-5-inch-drive-bay")
    assert out["c03"] == ("1.5 Litre Engine", "1-5-litre-engine")
    assert out["c04"] == ("2.0 Litre Engine", "2-0-litre-engine")
    # "3.1 " is c05's own section: "Belt Path" is the same title, told apart by its section
    assert out["c05"] == ("3.1 Belt Path", "3-1-belt-path")
    assert out["c06"] == ("Belt Path (section 4)", "belt-path-section-4")
    # a measurement whose whole part happens to be the section number is still a measurement
    out = finalize_topic_names(
        [_in("c01", "2.5 Inch Drive Bay", "2", [2]), _in("c02", "3.5 Inch Drive Bay", "3", [3])]
    )
    assert out["c02"] == ("3.5 Inch Drive Bay", "3-5-inch-drive-bay")


def test_slug_follows_the_shown_title_not_the_model_slug() -> None:
    # the model said slug "belt-path-3-1-harness-3-2-4-drive-train" for the title "Belt Path";
    # the slug is made from the title alone, so a model slug never reaches the input
    out = finalize_topic_names([_in("c01", "Belt Path", "3.1", [3, 4])])
    assert out == {"c01": ("Belt Path", "belt-path")}


def test_names_are_unique_valid_and_deterministic() -> None:
    items = [
        _in(f"c{i:02d}", t, s, p)
        for i, (t, s, p) in enumerate(
            [
                ("Overview", None, [1]),
                ("overview", None, [1]),
                ("unassigned", None, [2]),
                ("Front matter", None, [1]),
                ("pages 3-4", None, [3, 4]),
                ("Überblick", None, [5]),
                ("———", None, [6]),
                ("A" * 120, "1", [7]),
                ("a" * 120, "1", [8]),
                ("3. Overview", "3", [9]),
                ("3.1 overview", "3", [9]),
            ]
        )
    ]
    a = finalize_topic_names(items)
    assert a == finalize_topic_names(items)
    titles = [t for t, _ in a.values()]
    slugs = [s for _, s in a.values()]
    assert len({t.casefold() for t in titles}) == len(titles)
    assert len(set(slugs)) == len(slugs)
    for t, s in a.values():
        assert 0 < len(t) <= TITLE_MAX
        assert ids.SLUG_RE.match(s) and len(s) <= TOPIC_SLUG_MAX
        assert s not in (ids.UNASSIGNED, "front-matter") and not s.startswith("pages-")
    assert a["c01"] == ("Overview (part 2)", "overview-part-2")
    assert a["c02"][1] == "topic-unassigned" and a["c03"][1] == "topic-front-matter"
    assert a["c04"][1] == "topic-pages-3-4" and a["c05"] == ("Überblick", "uberblick")
    assert a["c06"] == ("———", "topic-07")  # nothing sluggable: numbered by position
    assert a["c08"][0].endswith("(page 8)") and a["c08"][1].endswith(
        "-page-8"
    )  # same section as c07
    # a leading section number does not tell titles apart (design 04 section 3.4.2)
    assert a["c09"] == ("Overview (section 3)", "overview-section-3")
    # "3.1" below section "3" may be a measurement: kept, and no longer alike "Overview"
    assert a["c10"] == ("3.1 Overview", "3-1-overview")


def _same_name(_messages: Sequence[Message]) -> str:
    data = next(m.content for m in _messages if m.role == "user")
    if '"assign_stragglers"' in data:
        payload = json.loads(data[len("<input>") : -len("</input>")])
        return json.dumps(
            {
                "assignments": [
                    {"block_id": b["block_id"], "topic": b["candidates"][0]}
                    for b in payload["blocks"]
                ]
            }
        )
    # a small model naming every cluster alike, in varying case, with a slug unrelated to the title
    return json.dumps({"title": "parts list", "slug": "belt-path-3-1-harness-3-2-4-drive-train"})


def test_group_document_never_shows_two_topics_with_the_same_name() -> None:
    blocks = []
    for p in range(1, 7):
        blocks.append(heading(p, 1, f"{p}. Section {p}"))
        blocks += [
            mk(p, n, f"Words about part {p} item {n} torque {n * p} N·m.") for n in range(2, 14)
        ]
    doc = doc_of(blocks)
    gf = group_document(doc, blocks, provider_set(ListSink(), grouping=_same_name))
    assert check_partition(blocks, gf) == []
    topics = [t for t in gf.topics if not t.is_unassigned]
    assert len(topics) >= 2, "the fixture must produce several topics to name"
    titles = [t.title for t in topics]
    assert len({t.casefold() for t in titles}) == len(titles), titles
    assert titles[0] == "Parts List"
    assert all(t.startswith("Parts List (") for t in titles[1:]), titles
    for t in topics:
        assert t.slug.startswith("parts-list"), t.slug
        assert "belt-path" not in t.slug
    again = group_document(doc, blocks, provider_set(ListSink(), grouping=_same_name))
    assert [(t.title, t.slug) for t in again.topics] == [(t.title, t.slug) for t in gf.topics]
