"""Group stage: build both views of a document, enforce the partition invariant, persist
(design §6). `group_document` is pure given its providers; `run_group` does the I/O."""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import GroupView, Task, UnassignedReason
from manuallabor.contracts.group import (
    GroupingParams,
    GroupOverride,
    GroupsFile,
)
from manuallabor.contracts.io import canonical_json, read_json, write_json
from manuallabor.grouping.coverage import overlap
from manuallabor.grouping.learning import BASELINE, LearnedGrouping, load_learned_grouping
from manuallabor.grouping.overrides import load_overrides
from manuallabor.grouping.structure import build_structure, is_header_footer
from manuallabor.grouping.topics import build_topics
from manuallabor.grouping.types import (
    GROUPING_ALGO_VERSION,
    GroupingError,
    GroupStats,
    default_params,
    embed_prefix_for,
)
from manuallabor.parse.pipeline import Emit, stdout_emit
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import ProviderSet, build_provider_set
from manuallabor.providers.sinks import JsonlSink
from manuallabor.scoring.pipeline import load_scored_blocks
from manuallabor.scoring.types import SCORING_ALGO_VERSION

__all__ = [
    "check_partition",
    "fingerprint",
    "group_document",
    "group_document_ex",
    "run_group",
]

ZERO_FP = "0" * 64


def fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _ref(m: Any) -> str:
    return f"{m.provider}:{m.model}"


# ---------------------------------------------------------------------------------------------
# pure core


def group_document_ex(
    doc: Document,
    blocks: Sequence[Block],
    providers: ProviderSet,
    *,
    params: GroupingParams | None = None,
    overrides: Sequence[GroupOverride] = (),
    learned: LearnedGrouping | None = None,
    fingerprint_hex: str = ZERO_FP,
) -> tuple[GroupsFile, GroupStats]:
    emb = providers.get(Task.embeddings)
    chat = providers.get(Task.grouping)
    if params is None:
        params = default_params(embed_prefix_for(emb.ref.model))
    structure = build_structure(doc, blocks)
    topics = build_topics(
        doc, blocks, structure, providers, params, overrides=overrides, learned=learned
    )
    unassigned = sorted(
        [*structure.unassigned, *topics.unassigned],
        key=lambda u: (u.view.value, ids.block_sort_key(u.block_id)),
    )
    sources = {**structure.title_sources, **topics.title_sources}
    gf = GroupsFile(
        doc_id=doc.slug,
        algo_version=GROUPING_ALGO_VERSION,
        fingerprint=fingerprint_hex,
        embedding_model=_ref(emb.ref),
        embedding_dim=topics.embedding_dim,
        grouping_model=_ref(chat.ref),
        learning_snapshot=learned.snapshot if learned is not None else BASELINE,
        params=params,
        structure=structure.groups,
        topics=topics.topics,
        unassigned=unassigned,
        stragglers=topics.stragglers,
        overlap=overlap(structure.groups, topics.topics),
        title_sources=dict(sorted(sources.items())),
        topic_status=topics.status,
        topic_error=topics.error,
        overrides_applied=topics.overrides_applied,
        overrides_stale=topics.overrides_stale,
    )
    return gf, topics.stats


def group_document(
    doc: Document,
    blocks: Sequence[Block],
    providers: ProviderSet,
    *,
    params: GroupingParams | None = None,
    overrides: Sequence[GroupOverride] = (),
    learned: LearnedGrouping | None = None,
    fingerprint_hex: str = ZERO_FP,
) -> GroupsFile:
    return group_document_ex(
        doc,
        blocks,
        providers,
        params=params,
        overrides=overrides,
        learned=learned,
        fingerprint_hex=fingerprint_hex,
    )[0]


def check_partition(blocks: Sequence[Block], gf: GroupsFile) -> list[str]:
    """Every problem that makes `gf` an invalid accounting of `blocks`; empty when sound."""
    problems: list[str] = []
    all_ids = {b.id for b in blocks}
    hf_ids = {b.id for b in blocks if is_header_footer(b)}
    for view, groups in ((GroupView.structure, gf.structure), (GroupView.topic, gf.topics)):
        seen: Counter[str] = Counter()
        for g in groups:
            seen.update(g.block_ids)
            if g.block_count != len(g.block_ids):
                problems.append(f"{view.value}: {g.id} block_count mismatch")
        hf_entries = [
            u.block_id
            for u in gf.unassigned
            if u.view == view and u.reason == UnassignedReason.header_footer
        ]
        seen.update(hf_entries)
        for b in sorted(all_ids - set(seen)):
            problems.append(f"{view.value}: block {b} is in no group")
        for b in sorted(set(seen) - all_ids):
            problems.append(f"{view.value}: unknown block {b}")
        for b, n in sorted(seen.items()):
            if n > 1:
                problems.append(f"{view.value}: block {b} appears {n} times")
        if set(hf_entries) != hf_ids:
            problems.append(
                f"{view.value}: header/footer entries do not match header/footer blocks"
            )
        if len({g.id for g in groups}) != len(groups):
            problems.append(f"{view.value}: duplicate group ids")
        if len({g.slug for g in groups}) != len(groups):
            problems.append(f"{view.value}: duplicate group slugs")
    for u in gf.unassigned:
        if u.view == GroupView.structure and u.reason != UnassignedReason.header_footer:
            problems.append(f"structure: {u.block_id} has reason {u.reason.value}")
    t000 = [g for g in gf.topics if g.is_unassigned]
    if len(t000) != 1:
        problems.append(f"topics: expected exactly one unassigned group, found {len(t000)}")
    else:
        listed = [
            u.block_id
            for u in gf.unassigned
            if u.view == GroupView.topic and u.reason != UnassignedReason.header_footer
        ]
        if listed != t000[0].block_ids:
            problems.append("topics: t000 does not match the unassigned topic-view entries")
        if t000[0].block_ids and set(t000[0].block_ids) & hf_ids:
            problems.append("topics: t000 holds a header/footer block")
    for g in gf.topics:
        if g.is_unassigned:
            continue
        if g.block_count < 2:
            problems.append(f"topics: {g.id} has fewer than 2 blocks")
        if g.cohesion is None or not 0.0 <= g.cohesion <= 1.0:
            problems.append(f"topics: {g.id} cohesion is missing or out of range")
    if gf.overlap != overlap(gf.structure, gf.topics):
        problems.append("overlap does not match the two views")
    return problems


# ---------------------------------------------------------------------------------------------
# I/O


def _progress(
    slug: str,
    status: str,
    gf: GroupsFile | None,
    stats: GroupStats | None,
    t0: float,
    detail: str | None,
) -> dict[str, Any]:
    topics = [g for g in gf.topics if not g.is_unassigned] if gf else []
    t000 = [g for g in gf.topics if g.is_unassigned] if gf else []
    return {
        "doc": slug,
        "stage": "group",
        "status": status,
        "structure_groups": len(gf.structure) if gf else None,
        "topics": len(topics) if gf else None,
        "unassigned": t000[0].block_count if t000 else (0 if gf else None),
        "low_cohesion": sum(
            1
            for g in topics
            if g.cohesion is not None and g.cohesion < (gf.params.low_cohesion if gf else 0)
        ),
        "stragglers": len(gf.stragglers) if gf else None,
        "llm_fallbacks": (stats.llm_fallbacks + stats.straggler_fallbacks) if stats else None,
        "elapsed_ms": int(round((time.perf_counter() - t0) * 1000.0)),
        "detail": detail,
    }


def _load_prior(path: Path) -> GroupsFile | None:
    if not path.is_file():
        return None
    try:
        gf = read_json(path, GroupsFile)
    except ValueError:
        return None
    return gf if gf.algo_version == GROUPING_ALGO_VERSION else None


def _group_doc(
    paths: ProjectPaths,
    slug: str,
    config: ProjectConfig,
    force: bool,
    get_providers: Callable[[], ProviderSet],
    emit: Emit,
) -> bool:
    """True when the document is fully grouped (or up to date)."""
    t0 = time.perf_counter()
    dp = paths.doc(slug)
    if not dp.blocks.is_file():
        raise GroupingError("document is not parsed (blocks.json missing)")
    blocks = load_scored_blocks(paths, slug)
    doc = paths.load_document(slug)
    overrides = load_overrides(dp.group_overrides)
    learned = load_learned_grouping(paths, config)
    eref = config.model_for(Task.embeddings)
    gref = config.model_for(Task.grouping)
    if eref is None or gref is None:
        raise GroupingError("embeddings and grouping models must be configured")
    params = default_params(embed_prefix_for(eref.model))
    fp = fingerprint(
        {
            "algo": GROUPING_ALGO_VERSION,
            "scoring_algo": SCORING_ALGO_VERSION,
            "document_sha": _sha(dp.document),
            "blocks_sha": _sha(dp.blocks),
            "params": params.model_dump(mode="json"),
            "embeddings_ref": eref.model_dump(mode="json"),
            "grouping_ref": gref.model_dump(mode="json"),
            "overrides_sha": _sha(dp.group_overrides),
            "learning_snapshot": learned.snapshot if learned is not None else BASELINE,
        }
    )
    prior = _load_prior(dp.groups)
    if not force and prior is not None and prior.fingerprint == fp:
        emit(_progress(slug, "skip", prior, None, t0, "up to date"))
        return prior.topic_status == "ok"
    gf, stats = group_document_ex(
        doc,
        blocks,
        get_providers(),
        params=params,
        overrides=overrides,
        learned=learned,
        fingerprint_hex=fp,
    )
    problems = check_partition(blocks, gf)
    if problems:
        shown = "; ".join(problems[:5])
        raise GroupingError(f"partition check failed ({len(problems)} problems): {shown}")
    write_json(dp.groups, gf)
    if gf.topic_status == "failed":
        emit(_progress(slug, "topic_failed", gf, stats, t0, gf.topic_error))
        return False
    stale = f"{len(gf.overrides_stale)} stale overrides" if gf.overrides_stale else None
    emit(_progress(slug, "done", gf, stats, t0, stale))
    return True


def run_group(
    paths: ProjectPaths,
    *,
    only: str | None = None,
    force: bool = False,
    providers: ProviderSet | Callable[[], ProviderSet] | None = None,
    emit: Emit = stdout_emit,
) -> list[str]:
    """Group every scored document (slug order). Returns the slugs that failed."""
    config = paths.load_config()
    slugs = paths.list_slugs()
    if only is not None:
        if only not in slugs:
            emit({"doc": only, "stage": "group", "status": "error", "detail": "unknown document"})
            return [only]
        slugs = [only]
    built: list[ProviderSet] = []

    def get_providers() -> ProviderSet:
        if isinstance(providers, ProviderSet):
            return providers
        if callable(providers):
            return providers()
        if not built:
            built.append(
                build_provider_set(
                    config,
                    cache_dir=paths.root / ".llm_cache",
                    sink=JsonlSink(paths.root / "llm_calls.jsonl"),
                )
            )
        return built[0]

    failed: list[str] = []
    for slug in slugs:
        t0 = time.perf_counter()
        try:
            if not _group_doc(paths, slug, config, force, get_providers, emit):
                failed.append(slug)
        except Exception as exc:
            failed.append(slug)
            emit(_progress(slug, "error", None, None, t0, f"{type(exc).__name__}: {exc}"))
    return failed


def unassigned_reasons(gf: GroupsFile) -> Counter[str]:
    """Reason histogram of the topic view (reporting helper)."""
    return Counter(u.reason.value for u in gf.unassigned if u.view == GroupView.topic)
