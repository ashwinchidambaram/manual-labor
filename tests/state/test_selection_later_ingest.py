"""Selection on later ingest (design 08 section 10): a document grouped after the selection was
first written enters the selection fully selected, like every document does on a fresh project.

Reproduces the first-use report: the reviewer touched the selection while the second manual was
still being read; when it arrived every one of its topics was at 0 percent while the screen said
"Everything starts selected"."""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from manuallabor import ids
from manuallabor.api.models import ScopeBlocks
from manuallabor.api.routers.scope import get_blocks
from manuallabor.contracts.io import read_json
from manuallabor.contracts.selection import Selection
from manuallabor.grouping.selection import load_selection, selectable_ids
from manuallabor.jobs.inline import run_inline
from manuallabor.project import ProjectPaths
from manuallabor.state.models import ActionKind, RunPlanIn, SelectionOp
from tests.conftest import FIXTURES
from tests.state.helpers import Env

NEW = "manual"  # manual.docx: parsed without Docling, so the late ingest stays quick


@pytest.fixture
def env(lp: ProjectPaths) -> Iterator[Env]:
    e = Env(lp)
    yield e
    e.close()


def _ingest_and_group(env: Env) -> None:
    res = run_inline(
        env.paths,
        RunPlanIn(to="group", docs=[NEW]),
        mode="mock",
        emit=lambda _o: None,
        store=env.store,
        files=[FIXTURES / "manual.docx"],
    )
    assert res.ok, res
    assert env.paths.doc(NEW).groups.is_file()


def _doc_ids(env: Env, slug: str) -> set[str]:
    return {b for b in selectable_ids(env.data.all_groups()) if ids.parse_block_id(b)[0] == slug}


def _deselect_first_topic(env: Env, slug: str) -> list[str]:
    gf = env.data.groups(slug)
    assert gf is not None
    topic = next(t for t in gf.topics if t.block_ids)
    env.scope.apply(
        SelectionOp(op="deselect_group", group_id=topic.id, doc_id=slug, request_id=env.rid())
    )
    return list(topic.block_ids)


def test_a_document_grouped_after_the_first_selection_write_enters_selected(env: Env) -> None:
    dropped = _deselect_first_topic(env, "clean")
    before = env.scope.summary()
    assert NEW not in env.paths.list_slugs()

    _ingest_and_group(env)

    new_ids = _doc_ids(env, NEW)
    assert new_ids
    out = env.scope.get()
    chosen = set(out.selection.block_ids)
    assert new_ids <= chosen, "the new manual must start selected"
    assert not chosen & set(dropped), "the reviewer's earlier choice is kept"
    assert out.summary.blocks == before.blocks + len(new_ids)
    cov = {c.doc_id: c for c in out.coverage}
    assert cov[NEW].selected == cov[NEW].selectable == len(new_ids)
    # the summary endpoint and the coverage agree with the selection
    assert env.scope.summary() == out.summary
    # the worker's reader (the selection.json projection) sees the same selection
    from_file, _ = load_selection(env.paths)
    assert set(from_file.block_ids) == chosen


def test_a_document_still_processing_at_the_first_write_enters_selected(env: Env) -> None:
    """The report's exact order: the second manual is registered (still reading) when the
    reviewer first touches the selection, and is grouped afterwards."""
    gp = env.paths.doc("scanned").groups
    held = gp.read_bytes()
    gp.unlink()  # scanned.pdf is ingested but not grouped yet
    _deselect_first_topic(env, "clean")
    assert not _doc_ids(env, "scanned")
    gp.write_bytes(held)  # its grouping finishes
    scanned = _doc_ids(env, "scanned")
    assert scanned and scanned <= set(env.scope.get().selection.block_ids)


def test_a_new_document_the_reviewer_then_clears_stays_cleared(env: Env) -> None:
    _deselect_first_topic(env, "clean")
    _ingest_and_group(env)
    new_ids = _doc_ids(env, NEW)
    env.scope.apply(SelectionOp(op="deselect", block_ids=sorted(new_ids), request_id=env.rid()))
    assert not set(env.scope.get().selection.block_ids) & new_ids
    stored = Selection.model_validate_json(env.store.get_selection_json() or "")
    assert stored.known_docs is not None and NEW in stored.known_docs
    assert not set(read_json(env.paths.selection, Selection).block_ids) & new_ids


def test_a_selection_saved_before_known_docs_existed_keeps_its_meaning(env: Env) -> None:
    """A stored selection without `known_docs` (an older project) means what it lists."""
    clean = _doc_ids(env, "clean")
    legacy = Selection(block_ids=sorted(clean))
    assert legacy.known_docs is None
    body = legacy.model_dump_json()
    with env.store.tx():
        aid = env.store.next_action_id()
        env.store.append_action(
            ActionKind.import_, "cli", payload={"what": "selection"}, after=body, action_id=aid
        )
        env.store.set_selection_json(body, aid)
    assert set(env.scope.get().selection.block_ids) == clean


def _expected_docs_pages(chosen: set[str]) -> tuple[set[str], set[tuple[str, int]]]:
    """What the summary must say from the selection alone: the documents and pages that hold a
    selected block (invariant 3: `docs` and `pages` reconcile with `blocks`)."""
    parsed = [ids.parse_block_id(b) for b in chosen]
    return {s for s, _p, _n in parsed}, {(s, p) for s, p, _n in parsed}


def test_a_grouped_document_not_yet_cleaned_counts_in_the_summary(env: Env) -> None:
    """e2e/later-ingest.spec.ts: a manual ingested to `group` has first-pass scores and no
    clean.json. The Scope summary is the pre-cleanup estimate (design 08 G1): it counts that
    manual's document, pages and review load, exactly as `/api/scope/blocks` lists its rows."""
    _deselect_first_topic(env, "clean")
    before = env.scope.summary()
    _ingest_and_group(env)
    assert not env.paths.doc(NEW).clean.is_file() and env.paths.doc(NEW).scores.is_file()

    out = env.scope.get()
    docs, pages = _expected_docs_pages(set(out.selection.block_ids))
    assert NEW in docs
    assert out.summary.docs == before.docs + 1 == len(docs)
    assert out.summary.articles_per_document == out.summary.docs
    assert out.summary.pages == len(pages)
    # the review estimate includes the new manual, as the client's block index does
    rows = {r.doc_id for r in _scope_rows(env)}
    assert NEW in rows


def _scope_rows(env: Env) -> list[ScopeBlocks]:
    """`GET /api/scope/blocks` (the client's block index) over the same ProjectData."""
    ctx = SimpleNamespace(paths=env.paths, review=SimpleNamespace(data=env.data))
    return get_blocks(ctx, None)  # type: ignore[arg-type]


@pytest.mark.parametrize("how", ["missing", "old_algo"])
def test_a_grouped_document_whose_scores_are_pending_stays_in_scope(env: Env, how: str) -> None:
    """A grouped document whose scores are missing or from another algo version (design 03
    section 2.10a) is still in scope: its selected blocks count in `blocks`, so the same
    document counts in `docs` and its pages in `pages`. Only the figure count and the review
    estimate, which need scores, leave it out (Verify shows it as pending)."""
    _deselect_first_topic(env, "clean")
    full = env.scope.summary()
    p = env.paths.doc("scanned").scores
    if how == "missing":
        p.unlink()
    else:
        body = json.loads(p.read_text(encoding="utf-8"))
        body["algo_version"] = "5"
        p.write_text(json.dumps(body), encoding="utf-8")
    assert not env.data.scored("scanned")

    out = env.scope.get()
    chosen = set(out.selection.block_ids)
    docs, pages = _expected_docs_pages(chosen)
    assert "scanned" in docs
    s = out.summary
    assert s.blocks == len(chosen) == full.blocks
    assert s.docs == len(docs) == full.docs
    assert s.articles_per_document == s.docs
    assert s.articles_per_topic == full.articles_per_topic
    assert s.pages == len(pages) == full.pages
    assert env.scope.summary() == s
    # what needs scores leaves the pending document out, as the client's block index does
    assert "scanned" not in {r.doc_id for r in _scope_rows(env)}
    assert s.review_load.queued <= full.review_load.queued
    assert s.figures <= full.figures
