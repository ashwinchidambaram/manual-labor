"""Clean stage (design 8): per document, clean -> attach -> describe -> re-score.

``clean_document`` is pure given its providers; ``run_clean`` does the I/O. Each output file is
written once per document, atomically, and only when its fingerprint changed."""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from manuallabor import ids
from manuallabor.cleanup.attach import FigureInfo, attach_document, figure_projection
from manuallabor.cleanup.describe import describe_figure
from manuallabor.cleanup.learned import (
    LearningRejected,
    load_learned_cleanup_ex,
    select_examples,
)
from manuallabor.cleanup.lexicon import Lexicon, doc_lexicon
from manuallabor.cleanup.residual import residual_reasons
from manuallabor.cleanup.rules import DH_RE, PassCtx, compose, plan_passes
from manuallabor.cleanup.types import (
    BASELINE,
    CLEANABLE,
    CLEANUP_ALGO_VERSION,
    DESCRIBE_PROMPT_VERSION,
    PROMPT_VERSION,
    AttachFile,
    AttachOverride,
    CleanEntry,
    CleanFile,
    CleanupError,
    DescribeEntry,
    DescribeFile,
    LearnedCleanup,
    LlmMode,
)
from manuallabor.cleanup.verify import clean_block
from manuallabor.contracts.block import Block, NumericVariant
from manuallabor.contracts.config import ModelRef, ProjectConfig
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import AttachRule, BlockType, Task
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.group import GroupsFile
from manuallabor.contracts.io import (
    canonical_json,
    dump_json,
    read_json,
    read_json_list,
    write_json,
    write_text_atomic,
)
from manuallabor.contracts.selection import Selection
from manuallabor.figures.types import FigureReport
from manuallabor.grouping.selection import load_selection
from manuallabor.grouping.types import GROUPING_ALGO_VERSION
from manuallabor.jobs import progress
from manuallabor.parse.pipeline import Emit, stdout_emit
from manuallabor.parse.text import collapse_ws
from manuallabor.parse.types import PageLayout
from manuallabor.project import DocPaths, ProjectPaths
from manuallabor.providers.base import Provider, ProviderSet, build_provider_set
from manuallabor.providers.sinks import JsonlSink
from manuallabor.scoring.faithfulness import glyph_identity, hf_tables
from manuallabor.scoring.pipeline import block_contexts, run_score
from manuallabor.scoring.types import SCORING_ALGO_VERSION, BlockContext, ScoreFile

__all__ = [
    "clean_document",
    "clean_fingerprints",
    "clean_provenance",
    "fingerprint",
    "run_clean",
]

STAGES = ("clean", "attach", "describe", "score")


def fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _ref(m: ModelRef | None) -> str | None:
    return f"{m.provider}:{m.model}" if m is not None else None


def _ms(t0: float) -> int:
    return int(round((time.perf_counter() - t0) * 1000.0))


# ---------------------------------------------------------------------------------------------
# clean: pure core


@dataclass
class CleanStats:
    llm_calls: int = 0
    llm_cached: int = 0
    llm_accepted: int = 0
    llm_rejected: Counter[str] = field(default_factory=Counter)
    residual: Counter[str] = field(default_factory=Counter)
    reused: int = 0


def _lexicon_view(raw: str, lexicon: Lexicon) -> list[list[Any]]:
    """The lexicon facts a block's dehyphenation decisions depend on (part of its input hash:
    another block's text can change them)."""
    t = glyph_identity(raw.replace("\r\n", "\n").replace("\r", "\n")).text
    out: list[list[Any]] = []
    for m in DH_RE.finditer(t):
        left, right = m.group("L"), m.group("R")
        out.append([left, right, lexicon.has_compound(left, right), lexicon.has_word(left + right)])
    return out


def block_input_hash(
    block: Block,
    ctx: BlockContext,
    *,
    variants: Sequence[NumericVariant],
    mode: LlmMode,
    cleanup_ref: str | None,
    rules: Sequence[Any],
    examples: Sequence[Any],
    lexicon: Lexicon,
) -> str:
    return fingerprint(
        {
            "algo": CLEANUP_ALGO_VERSION,
            "raw_text": block.raw_text,
            "type": block.type.value,
            "table": block.table.model_dump(mode="json") if block.table else None,
            "raw_source": block.raw_source,
            "raw_text_by_parser": dict(sorted(block.raw_text_by_parser.items())),
            "page": block.page,
            "hf_strings": list(ctx.hf_strings),
            "hf_pages": ctx.hf_pages,
            "layout_risk": ctx.layout_risk,
            "variants": [v.model_dump(mode="json") for v in variants],
            "llm_mode": mode,
            "cleanup_ref": cleanup_ref,
            "prompt_version": PROMPT_VERSION,
            "rules": [r.model_dump(mode="json") for r in rules],
            "few_shot": [e.model_dump(mode="json") for e in examples],
            "lexicon": _lexicon_view(block.raw_text, lexicon),
        }
    )


def cleanable(block: Block) -> bool:
    return block.type in CLEANABLE and bool(collapse_ws(block.raw_text))


@dataclass
class _Planned:
    block: Block
    ctx: BlockContext
    passes: Any
    pctx: PassCtx
    variants: list[NumericVariant]
    chosen: list[Any]
    input_hash: str


def _plan_blocks(
    doc: Document,
    blocks: Sequence[Block],
    layouts: Sequence[PageLayout],
    selected: set[str],
    *,
    variants: Mapping[str, Sequence[NumericVariant]],
    mode: LlmMode,
    cleanup_ref: str | None,
    learned: LearnedCleanup | None,
) -> tuple[list[_Planned], dict[str, BlockContext]]:
    """Per selected cleanable block (reading order): passes, context, chosen few-shot examples
    and the input hash. Deterministic and LLM-free."""
    ordered = sorted(blocks, key=lambda b: b.reading_order)
    ctxs = block_contexts(doc, blocks, layouts)
    lexicon = doc_lexicon(b.raw_text for b in ordered)
    rules = list(learned.rules) if learned is not None else []
    examples = list(learned.examples) if learned is not None else []
    hf_cache: dict[str, Any] = {}
    planned: list[_Planned] = []
    for b in ordered:
        if b.id not in selected or not cleanable(b):
            continue
        ctx = ctxs[b.id]
        key = canonical_json([ctx.hf_strings, ctx.hf_pages]).decode()
        if key not in hf_cache:
            hf_cache[key] = hf_tables(ctx.hf_strings, ctx.hf_pages)
        passes = plan_passes(b.type, b.table is not None, rules)
        pctx = PassCtx(
            block_type=b.type, page=b.page, hf=hf_cache[key], lexicon=lexicon, table=b.table
        )
        bv = list(variants.get(b.id, ()))
        chosen: list[Any] = []
        if examples and mode != "off":
            preview = compose(b.raw_text, passes, pctx)
            chosen = select_examples(examples, b, residual_reasons(b, preview, ctx.layout_risk))
        applicable = [r for r in rules if b.type in r.block_types]
        h = block_input_hash(
            b,
            ctx,
            variants=bv,
            mode=mode,
            cleanup_ref=cleanup_ref,
            rules=applicable,
            examples=chosen,
            lexicon=lexicon,
        )
        planned.append(_Planned(b, ctx, passes, pctx, bv, chosen, h))
    return planned, ctxs


def _clean_fp(selected: set[str], ctxs: Mapping[str, Any], hashes: Sequence[str]) -> str:
    return fingerprint(
        {
            "algo": CLEANUP_ALGO_VERSION,
            "scoring_algo": SCORING_ALGO_VERSION,
            "selected": sorted((s for s in selected if s in ctxs), key=ids.block_sort_key),
            "input_hashes": list(hashes),
        }
    )


def clean_document(
    doc: Document,
    blocks: Sequence[Block],
    layouts: Sequence[PageLayout],
    selected: set[str],
    *,
    variants: Mapping[str, Sequence[NumericVariant]] | None = None,
    mode: LlmMode = "residual",
    provider: Provider | None = None,
    cleanup_ref: str | None = None,
    learned: LearnedCleanup | None = None,
    prior: Mapping[str, CleanEntry] | None = None,
    prefilter: bool = True,
    stats: CleanStats | None = None,
) -> tuple[list[CleanEntry], str]:
    """Clean every selected cleanable block in reading order. Returns the entries (sorted by
    block id) and the clean fingerprint. ``prior`` entries whose input hash is unchanged are
    reused as they are."""
    stats = stats if stats is not None else CleanStats()
    prior = prior or {}
    planned, ctxs = _plan_blocks(
        doc,
        blocks,
        layouts,
        selected,
        variants=variants or {},
        mode=mode,
        cleanup_ref=cleanup_ref,
        learned=learned,
    )
    entries: list[CleanEntry] = []
    hashes: list[str] = []
    for i, pl in enumerate(planned):
        # the jobs bar (design 07 section 4.1): blocks done before this one
        progress.report(doc.slug, i, len(planned), "block")
        b, h = pl.block, pl.input_hash
        hashes.append(h)
        old = prior.get(b.id)
        if old is not None and old.input_hash == h:
            entries.append(old)
            stats.reused += 1
            for r in old.residual:
                stats.residual[r] += 1
            continue
        res = clean_block(
            b,
            pl.ctx,
            input_hash=h,
            passes=pl.passes,
            pctx=pl.pctx,
            variants=pl.variants,
            mode=mode,
            provider=provider,
            examples=pl.chosen,
            prefilter=prefilter,
        )
        e = res.entry
        entries.append(e)
        for r in e.residual:
            stats.residual[r] += 1
        if res.llm_called:
            stats.llm_calls += 1
            stats.llm_cached += res.llm_cached
        if e.llm is not None and e.llm.outcome == "accepted":
            stats.llm_accepted += 1
        if e.llm is not None and e.llm.outcome == "rejected":
            stats.llm_rejected[e.llm.reason or "rejected"] += 1
    progress.report(doc.slug, len(planned), len(planned), "block")
    fp = _clean_fp(selected, ctxs, hashes)
    return sorted(entries, key=lambda e: ids.block_sort_key(e.block_id)), fp


# ---------------------------------------------------------------------------------------------
# I/O helpers


def _load_model[M: BaseModel](path: Path, model: type[M]) -> M | None:
    if not path.is_file():
        return None
    try:
        return read_json(path, model)
    except ValueError:
        return None


def _scores(dp: DocPaths) -> ScoreFile:
    sf = _load_model(dp.scores, ScoreFile)
    if sf is None or sf.algo_version != SCORING_ALGO_VERSION:
        raise CleanupError("scores.json missing or stale (run `labor score`)")
    return sf


def _groups(dp: DocPaths) -> GroupsFile:
    gf = _load_model(dp.groups, GroupsFile)
    if gf is None or gf.algo_version != GROUPING_ALGO_VERSION:
        raise CleanupError("groups.json missing or stale (run `labor group`)")
    return gf


def _variants(sf: ScoreFile) -> dict[str, list[NumericVariant]]:
    return {
        s.block_id: list(s.faithfulness.numeric_variants)
        for s in sf.blocks
        if s.faithfulness is not None and s.faithfulness.numeric_variants
    }


def _load_overrides(path: Path) -> list[AttachOverride]:
    if not path.is_file():
        return []
    try:
        data = TypeAdapter(list[AttachOverride]).validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CleanupError(f"{path.name} is invalid: {exc}") from exc
    return sorted(data, key=lambda o: o.seq)


def _write_sidecar(path: Path, rec: FigureRecord, update: Mapping[str, Any]) -> bool:
    new = FigureRecord.model_validate({**rec.model_dump(), **update})
    data = dump_json(new)
    if path.read_text(encoding="utf-8") == data:
        return False
    write_text_atomic(path, data)
    return True


def _figure_blocks(blocks: Sequence[Block]) -> list[Block]:
    return sorted(
        (b for b in blocks if b.type == BlockType.figure and b.figure_id is not None),
        key=lambda b: ids.block_sort_key(str(b.figure_id)),
    )


# ---------------------------------------------------------------------------------------------
# stages


@dataclass
class DocRun:
    paths: ProjectPaths
    slug: str
    config: ProjectConfig
    selection: Selection
    mode: LlmMode
    describe: bool
    force: bool
    learned: LearnedCleanup | None
    get_providers: Callable[[], ProviderSet]
    emit: Emit
    prefilter: bool = True
    learned_rejected: LearningRejected = field(default_factory=LearningRejected)

    @property
    def dp(self) -> DocPaths:
        return self.paths.doc(self.slug)

    def selected(self) -> set[str]:
        return {b for b in self.selection.block_ids if ids.parse_block_id(b)[0] == self.slug}


def _stage_clean(run: DocRun, blocks: Sequence[Block]) -> None:
    t0 = time.perf_counter()
    dp = run.dp
    sf = _scores(dp)
    _groups(dp)
    doc = run.paths.load_document(run.slug)
    layouts = read_json_list(dp.layout, PageLayout) if dp.layout.is_file() else []
    selected = run.selected()
    cref = run.config.model_for(Task.cleanup)
    prior_file = _load_model(dp.clean, CleanFile)
    prior = (
        {e.block_id: e for e in prior_file.blocks}
        if prior_file is not None
        and not run.force
        and prior_file.algo_version == CLEANUP_ALGO_VERSION
        else {}
    )
    provider = (
        run.get_providers().get(Task.cleanup) if run.mode != "off" and cref is not None else None
    )
    stats = CleanStats()
    entries, fp = clean_document(
        doc,
        blocks,
        layouts,
        selected,
        variants=_variants(sf),
        mode=run.mode,
        provider=provider,
        cleanup_ref=_ref(cref),
        learned=run.learned,
        prior=prior,
        prefilter=run.prefilter,
        stats=stats,
    )
    status = "done"
    snapshot = run.learned.snapshot if run.learned is not None else BASELINE
    provenance = (snapshot, run.learned_rejected.rules, run.learned_rejected.examples)
    if (
        not run.force
        and prior_file is not None
        and prior_file.fingerprint == fp
        and (prior_file.learning_snapshot, prior_file.rejected_rules, prior_file.rejected_examples)
        == provenance
    ):
        status = "skip"
    else:
        write_json(
            dp.clean,
            CleanFile(
                doc_id=run.slug,
                algo_version=CLEANUP_ALGO_VERSION,
                fingerprint=fp,
                scoring_algo=SCORING_ALGO_VERSION,
                cleanup_model=_ref(cref),
                llm_mode=run.mode,
                prompt_version=PROMPT_VERSION,
                learning_snapshot=snapshot,
                rejected_rules=list(run.learned_rejected.rules),
                rejected_examples=list(run.learned_rejected.examples),
                blocks=entries,
            ),
        )
    raw = {b.id: b.raw_text for b in blocks}
    run.emit(
        {
            "doc": run.slug,
            "stage": "clean",
            "status": status,
            "selected": len(selected),
            "cleaned": len(entries),
            "changed": sum(1 for e in entries if e.clean_text != raw.get(e.block_id)),
            "by_stage": dict(sorted(Counter(e.stage for e in entries).items())),
            "det_rejected": sum(
                1
                for e in entries
                if e.passes_rejected or any(r.stage == "deterministic" for r in e.rejected)
            ),
            "llm_calls": stats.llm_calls,
            "llm_cached": stats.llm_cached,
            "llm_accepted": stats.llm_accepted,
            "llm_rejected": dict(sorted(stats.llm_rejected.items())),
            "residual": dict(sorted(stats.residual.items())),
            "elapsed_ms": _ms(t0),
            "detail": f"reused {stats.reused} entries"
            if stats.reused and status == "done"
            else None,
        }
    )


def _figure_infos(
    run: DocRun, blocks: Sequence[Block]
) -> tuple[list[FigureInfo], dict[str, FigureRecord]]:
    dp = run.dp
    report = _load_model(dp.figure_report, FigureReport)
    failed = {f.figure_id for f in report.failures} if report is not None else set()
    infos: list[FigureInfo] = []
    recs: dict[str, FigureRecord] = {}
    for b in _figure_blocks(blocks):
        fid = str(b.figure_id)
        rec = _load_model(run.paths.figure_file(run.slug, fid, "json"), FigureRecord)
        if rec is not None:
            recs[fid] = rec
        infos.append(
            FigureInfo(
                figure_id=fid,
                block_id=b.id,
                caption=rec.caption_original if rec is not None else None,
                failed=fid in failed or rec is None,
            )
        )
    return infos, recs


def _attach_fp(run: DocRun, infos: Sequence[FigureInfo]) -> str:
    dp = run.dp
    return fingerprint(
        {
            "algo": CLEANUP_ALGO_VERSION,
            "grouping_algo": GROUPING_ALGO_VERSION,
            "groups_sha": _sha(dp.groups),
            "blocks_sha": _sha(dp.blocks),
            "selected": sorted(run.selected(), key=ids.block_sort_key),
            "split": run.selection.article_split.value,
            "captions": {f.figure_id: [f.caption, f.failed] for f in infos},
            "figures_report_sha": _sha(dp.figure_report),
            "overrides_sha": _sha(dp.attach_overrides),
        }
    )


def _stage_attach(run: DocRun, blocks: Sequence[Block]) -> AttachFile:
    t0 = time.perf_counter()
    dp = run.dp
    gf = _groups(dp)
    infos, recs = _figure_infos(run, blocks)
    selected = run.selected()
    split = run.selection.article_split
    fp = _attach_fp(run, infos)
    prior = _load_model(dp.attach, AttachFile)
    if not run.force and prior is not None and prior.fingerprint == fp:
        af, status = prior, "skip"
    else:
        af = attach_document(
            run.slug,
            blocks,
            gf,
            selected,
            split,
            infos,
            _load_overrides(dp.attach_overrides),
            fp,
        )
        write_json(dp.attach, af)
        status = "done"
    proj = figure_projection(af)
    written = 0
    for fid, rec in sorted(recs.items()):
        arts, rule = proj.get(fid, ([], AttachRule.none))
        path = run.paths.figure_file(run.slug, fid, "json")
        written += _write_sidecar(path, rec, {"articles": arts, "attach_rule": rule})
    by_rule = Counter(rule.value for _, rule in proj.values())
    run.emit(
        {
            "doc": run.slug,
            "stage": "attach",
            "status": status,
            "figures": len(infos),
            "attached": len(proj),
            "by_rule": dict(sorted(by_rule.items())),
            "unattached": len(af.unattached),
            "unresolved_refs": len(af.unresolved_refs),
            "overrides_stale": len(af.overrides_stale),
            "elapsed_ms": _ms(t0),
            "detail": f"{written} sidecars updated" if written else None,
        }
    )
    return af


@dataclass
class _DescribeInputs:
    fp: str
    infos: list[FigureInfo]
    recs: dict[str, FigureRecord]
    images: dict[str, bytes]
    shas: dict[str, str]
    in_scope: set[str]
    enabled: bool
    vref: ModelRef | None


def _describe_inputs(run: DocRun, blocks: Sequence[Block], af: AttachFile) -> _DescribeInputs:
    infos, recs = _figure_infos(run, blocks)
    in_scope = set(figure_projection(af))
    vref = run.config.model_for(Task.vision)
    enabled = run.describe and vref is not None
    images: dict[str, bytes] = {}
    for fid, rec in recs.items():
        p = (run.paths.figure_dir(run.slug) / rec.file).resolve()
        if p.is_file():
            images[fid] = p.read_bytes()
    shas = {fid: hashlib.sha256(data).hexdigest() for fid, data in images.items()}
    fp = fingerprint(
        {
            "algo": CLEANUP_ALGO_VERSION,
            "vision_ref": _ref(vref),
            "prompt_version": DESCRIBE_PROMPT_VERSION,
            "describe": enabled,
            "figures": [
                [f.figure_id, shas.get(f.figure_id), f.caption, f.figure_id in in_scope]
                for f in infos
            ],
        }
    )
    return _DescribeInputs(fp, infos, recs, images, shas, in_scope, enabled, vref)


def _stage_describe(run: DocRun, blocks: Sequence[Block], af: AttachFile) -> None:
    t0 = time.perf_counter()
    dp = run.dp
    di = _describe_inputs(run, blocks, af)
    infos, recs, images, shas = di.infos, di.recs, di.images, di.shas
    in_scope, enabled, fp, vref = di.in_scope, di.enabled, di.fp, di.vref
    prior = _load_model(dp.describe, DescribeFile)
    counts: Counter[str] = Counter()
    if not run.force and prior is not None and prior.fingerprint == fp:
        df, status = prior, "skip"
    else:
        old = {e.figure_id: e for e in prior.figures} if prior is not None else {}
        # one call per distinct image: duplicates share the canonical's bytes, and the
        # first figure (id order) with those bytes gives the caption context
        first_caption: dict[str, str | None] = {}
        for f in infos:
            sha = shas.get(f.figure_id)
            if sha is not None and f.figure_id in in_scope and sha not in first_caption:
                first_caption[sha] = f.caption
        done: dict[str, Any] = {}
        entries: list[DescribeEntry] = []
        for f in infos:
            sha = shas.get(f.figure_id)
            prev = old.get(f.figure_id)
            keep_prev = prev is not None and prev.outcome == "ok" and prev.image_sha256 == sha
            if f.failed or sha is None:
                e = DescribeEntry(figure_id=f.figure_id, image_sha256=sha, outcome="skipped_failed")
            elif not enabled:
                e = DescribeEntry(
                    figure_id=f.figure_id, image_sha256=sha, outcome="skipped_disabled"
                )
            elif f.figure_id not in in_scope:
                e = (
                    prev
                    if keep_prev and prev is not None
                    else DescribeEntry(
                        figure_id=f.figure_id, image_sha256=sha, outcome="skipped_not_in_scope"
                    )
                )
            else:
                if sha not in done:
                    done[sha] = describe_figure(
                        run.get_providers().get(Task.vision),
                        images[f.figure_id],
                        first_caption[sha],
                    )
                d = done[sha]
                e = DescribeEntry(
                    figure_id=f.figure_id,
                    image_sha256=sha,
                    outcome=d.outcome,
                    description=d.description,
                    tags=d.tags,
                )
            entries.append(e)
        df = DescribeFile(
            doc_id=run.slug,
            algo_version=CLEANUP_ALGO_VERSION,
            fingerprint=fp,
            vision_model=_ref(vref),
            prompt_version=DESCRIBE_PROMPT_VERSION,
            figures=entries,
        )
        write_json(dp.describe, df)
        status = "done"
    for e in df.figures:
        counts[e.outcome] += 1
        sidecar = recs.get(e.figure_id)
        if sidecar is None:
            continue
        ok = e.outcome == "ok"
        _write_sidecar(
            run.paths.figure_file(run.slug, e.figure_id, "json"),
            sidecar,
            {
                "description_generated": e.description if ok else None,
                "tags": list(e.tags) if ok else [],
            },
        )
    run.emit(
        {
            "doc": run.slug,
            "stage": "describe",
            "status": status,
            "described": counts["ok"],
            "skipped": sum(v for k, v in counts.items() if k.startswith("skipped_")),
            "invalid": counts["invalid"],
            "errors": counts["error"],
            "elapsed_ms": _ms(t0),
            "detail": None,
        }
    )


# ---------------------------------------------------------------------------------------------
# fingerprints of the current inputs (module 7: stage graph freshness, pure)


def _noop_providers() -> ProviderSet:
    raise CleanupError("fingerprints never call a model")


def _doc_run(paths: ProjectPaths, slug: str, config: ProjectConfig) -> DocRun:
    learned, rejected = load_learned_cleanup_ex(paths, config)
    selection, _ = load_selection(paths)
    return DocRun(
        paths=paths,
        slug=slug,
        config=config,
        selection=selection,
        mode=config.cleanup.llm,
        describe=config.cleanup.describe,
        force=False,
        learned=learned,
        get_providers=_noop_providers,
        emit=lambda _o: None,
        learned_rejected=rejected,
    )


def clean_provenance(
    paths: ProjectPaths, config: ProjectConfig
) -> tuple[str, list[str], list[str]]:
    """(learning snapshot, rejected rule ids, rejected example ids) the stage would record."""
    learned, rejected = load_learned_cleanup_ex(paths, config)
    snap = learned.snapshot if learned is not None else BASELINE
    return snap, list(rejected.rules), list(rejected.examples)


def clean_fingerprints(
    paths: ProjectPaths, slug: str, config: ProjectConfig
) -> tuple[str, str, str]:
    """The fingerprints `clean.json`, `attach.json` and `describe.json` must carry to be
    current: (clean, attach, describe). Runs no pass and no model."""
    run = _doc_run(paths, slug, config)
    dp = run.dp
    if not dp.blocks.is_file():
        raise CleanupError("document is not parsed (blocks.json missing)")
    blocks = read_json_list(dp.blocks, Block)
    sf = _scores(dp)
    gf = _groups(dp)
    doc = paths.load_document(slug)
    layouts = read_json_list(dp.layout, PageLayout) if dp.layout.is_file() else []
    selected = run.selected()
    cref = config.model_for(Task.cleanup)
    planned, ctxs = _plan_blocks(
        doc,
        blocks,
        layouts,
        selected,
        variants=_variants(sf),
        mode=run.mode,
        cleanup_ref=_ref(cref),
        learned=run.learned,
    )
    fp_clean = _clean_fp(selected, ctxs, [p.input_hash for p in planned])
    infos, _recs = _figure_infos(run, blocks)
    fp_attach = _attach_fp(run, infos)
    af = _load_model(dp.attach, AttachFile)
    if af is None or af.fingerprint != fp_attach:
        af = attach_document(
            slug,
            blocks,
            gf,
            selected,
            run.selection.article_split,
            infos,
            _load_overrides(dp.attach_overrides),
            fp_attach,
        )
    fp_desc = _describe_inputs(run, blocks, af).fp
    return fp_clean, fp_attach, fp_desc


# ---------------------------------------------------------------------------------------------
# entry point


def run_clean(
    paths: ProjectPaths,
    *,
    only: str | None = None,
    force: bool = False,
    providers: ProviderSet | Callable[[], ProviderSet] | None = None,
    emit: Emit = stdout_emit,
    llm_mode: LlmMode | None = None,
    describe: bool | None = None,
    rescore: bool = True,
    prefilter: bool = True,
) -> list[str]:
    """Clean, attach, describe and re-score every document (slug order). Returns the slugs
    that failed; a failing document never stops the next one."""
    config = paths.load_config()
    slugs = paths.list_slugs()
    if only is not None:
        if only not in slugs:
            emit({"doc": only, "stage": "clean", "status": "error", "detail": "unknown document"})
            return [only]
        slugs = [only]
    built: list[ProviderSet] = []

    def get_providers() -> ProviderSet:
        if isinstance(providers, ProviderSet):
            return providers
        if callable(providers):
            if not built:
                built.append(providers())
            return built[0]
        if not built:
            built.append(
                build_provider_set(
                    config,
                    cache_dir=paths.llm_cache,
                    sink=JsonlSink(paths.llm_log),
                )
            )
        return built[0]

    mode: LlmMode = llm_mode or config.cleanup.llm
    do_describe = config.cleanup.describe if describe is None else describe
    learned, learned_rejected = load_learned_cleanup_ex(paths, config)
    selection, _ = load_selection(paths)
    failed: list[str] = []
    for slug in slugs:
        run = DocRun(
            paths=paths,
            slug=slug,
            config=config,
            selection=selection,
            mode=mode,
            describe=do_describe,
            force=force,
            learned=learned,
            get_providers=get_providers,
            emit=emit,
            prefilter=prefilter,
            learned_rejected=learned_rejected,
        )
        stage = "clean"
        t0 = time.perf_counter()
        try:
            dp = run.dp
            if not dp.blocks.is_file():
                raise CleanupError("document is not parsed (blocks.json missing)")
            blocks = read_json_list(dp.blocks, Block)
            _stage_clean(run, blocks)
            stage = "attach"
            af = _stage_attach(run, blocks)
            stage = "describe"
            _stage_describe(run, blocks, af)
        except Exception as exc:
            failed.append(slug)
            emit(
                {
                    "doc": slug,
                    "stage": stage,
                    "status": "error",
                    "elapsed_ms": _ms(t0),
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if rescore and run_score(paths, only=slug, providers=get_providers, emit=emit):
            failed.append(slug)
    return failed
