"""Score stage: pure per-block scoring, the scores.json overlay, sidecar confidence, history
(design 7). blocks.json is never modified (module 2's figures fingerprint hashes it)."""

from __future__ import annotations

import functools
import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manuallabor import faults, ids
from manuallabor.calibration.types import LexiconEntry
from manuallabor.cleanup.types import CleanFile, fallback_detail, raw_sha256
from manuallabor.contracts.block import Block, NumericVariant, Signal
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockStatus, BlockType, SignalName, Task
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import (
    canonical_json,
    dump_json,
    read_json,
    read_json_list,
    write_json,
    write_text_atomic,
)
from manuallabor.figures.types import FigureIndex, FigureReport
from manuallabor.jobs import progress
from manuallabor.parse.pipeline import Emit, stdout_emit
from manuallabor.parse.text import collapse_ws
from manuallabor.parse.types import PageLayout
from manuallabor.project import DocPaths, ProjectPaths
from manuallabor.providers.base import ProviderSet, build_provider_set
from manuallabor.providers.sinks import JsonlSink
from manuallabor.scoring.agreement import parser_agreement, textlayer_vs_ocr
from manuallabor.scoring.combine import combine
from manuallabor.scoring.faithfulness import check_faithfulness_ex
from manuallabor.scoring.figures import figure_attach_rule, figure_method, figure_resolution
from manuallabor.scoring.garbage import garbage_ratio
from manuallabor.scoring.layout import displaced_blocks, reading_order_risk
from manuallabor.scoring.learned import (
    LearnedScoring,
    active_lexicon,
    block_texts,
    learned_confusables,
    lexicon_specs,
    load_learned_scoring,
    promote,
)
from manuallabor.scoring.numeric import numeric_specs_for
from manuallabor.scoring.ocr import ocr_signals
from manuallabor.scoring.queue import assign_status
from manuallabor.scoring.tables import table_consistency
from manuallabor.scoring.types import (
    FAITH_FALLBACK_VALUE,
    FAITH_REORDER_VALUE,
    SCORING_ALGO_VERSION,
    BlockContext,
    BlockScore,
    FigureInputs,
    HistoryEntry,
    ReorderEvidence,
    ScoreFile,
    ScoringError,
    truncate,
)
from manuallabor.scoring.verifier import VerifierPlan, llm_verifier, plan_verifier

__all__ = [
    "block_contexts",
    "faith_kwargs",
    "fingerprint",
    "load_clean_overlay",
    "load_scored_blocks",
    "run_score",
    "score_block",
    "score_document",
    "score_fingerprint",
    "scores_current",
]

NO_VERIFIER = VerifierPlan(None, "skip_no_verifier", None)


# ---------------------------------------------------------------------------------------------
# pure core


def _faith_detail(violations: Sequence[Any]) -> str:
    parts = []
    for v in violations[:3]:
        r, c = v.raw[:24], v.clean[:24]
        if v.raw and v.clean:
            parts.append(f"{v.kind.value} {r!r}→{c!r}")
        else:
            parts.append(f"{v.kind.value} {(r or c)!r}")
    n = len(violations)
    return truncate(f"{n} violation{'s' if n != 1 else ''}: " + "; ".join(parts))


def block_contexts(
    doc: Document, blocks: Sequence[Block], layouts: Sequence[PageLayout]
) -> dict[str, BlockContext]:
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    lay = {pl.page: pl for pl in layouts}
    hf = sorted(set(doc.stripped_headers) | set(doc.stripped_footers))
    hf_pages: dict[str, set[int]] = {}
    for b in blocks:
        if b.type in (BlockType.header, BlockType.footer) and b.raw_text.strip():
            hf_pages.setdefault(collapse_ws(b.raw_text), set()).add(b.page)
    hf_pages_out = {k: sorted(v) for k, v in sorted(hf_pages.items())}
    out: dict[str, BlockContext] = {}
    for page in sorted(by_page):
        disp = displaced_blocks(by_page[page])
        pl = lay.get(page)
        overl = {o.a for o in pl.overlaps} | {o.b for o in pl.overlaps} if pl else set()
        for b in by_page[page]:
            out[b.id] = BlockContext(
                displaced_in=disp.get(b.id, []),
                in_overlap=b.id in overl,
                n_columns=pl.n_columns if pl else None,
                parser_versions=dict(doc.parser_versions),
                product_model=doc.product_model,
                hf_strings=hf,
                hf_pages=hf_pages_out,
            )
    return out


def faith_kwargs(
    block: Block, ctx: BlockContext, variants: Sequence[NumericVariant] = ()
) -> dict[str, Any]:
    """The full-context keyword arguments of ``check_faithfulness_ex`` for one block (design
    05 S4). Scoring and cleanup both call the check with exactly these, so their verdicts on
    the same (raw, clean) pair are identical by construction."""
    texts = block.raw_text_by_parser
    return {
        "block_type": block.type,
        "table": block.table,
        "hf_strings": ctx.hf_strings,
        "hf_pages": ctx.hf_pages,
        "variant_sources": texts,
        "raw_source": block.raw_source,
        "page": block.page,
        "variants": list(variants),
        "evidence": ReorderEvidence(
            layout_risk=ctx.layout_risk,
            alt_texts=tuple(texts[k] for k in sorted(texts) if k != block.raw_source),
        ),
    }


def score_block(
    block: Block,
    ctx: BlockContext,
    *,
    threshold: float,
    fig: FigureInputs | None = None,
    variants: Sequence[NumericVariant] = (),
    plan: VerifierPlan = NO_VERIFIER,
    counters: Counter[str] | None = None,
    fallback: str | None = None,
    learned: LearnedScoring | None = None,
    lexicon: Sequence[LexiconEntry] = (),
) -> BlockScore:
    """All signals of one block, its confidence and machine status. Pure except the optional
    verifier call. ``fallback``: cleanup rejected a candidate for this block and kept its
    deterministic result (the reason), which caps faithfulness at FAITH_FALLBACK_VALUE."""
    counters = counters if counters is not None else Counter()
    signals: list[Signal] = []
    if block.type == BlockType.figure:
        if fig is None or (fig.extraction is None and fig.failure is None):
            raise ScoringError(f"{block.id}: no figures_report entry (run `labor figures`)")
        signals.append(figure_method(fig))
        for s in (figure_resolution(fig), figure_attach_rule(fig)):
            if s is not None:
                signals.append(s)
        conf = combine(signals)
        return BlockScore(
            block_id=block.id,
            signals=sorted(signals, key=lambda s: s.name.value),
            confidence=conf,
            status=assign_status(conf, False, threshold).value,  # type: ignore[arg-type]
            has_numeric_spec=False,
            numeric_specs=[],
            faithfulness=None,
        )

    numeric, specs = numeric_specs_for(block, ctx.product_model)
    learned_why: list[str] = []
    forced_queue = False
    if learned is not None and block.type not in (BlockType.header, BlockType.footer):
        extra: list[str] = []
        for t in block_texts(block):
            extra.extend(lexicon_specs(t, lexicon))
        extra = [x for x in dict.fromkeys(extra) if x not in specs]
        if extra:
            if not numeric:
                learned_why.append("learned: lexicon " + ", ".join(repr(x) for x in extra[:3]))
            numeric = True
            specs = [*specs, *extra]
        conf_why = learned_confusables(block.raw_text, learned.confusions)
        if conf_why:
            forced_queue = True
            learned_why.extend(conf_why)
    signals.extend(ocr_signals(block, numeric=numeric))
    pa, note = parser_agreement(block, ctx.parser_versions, numeric=numeric)
    if pa is not None:
        signals.append(pa)
    if note is not None:
        counters[note] += 1
    tvo = textlayer_vs_ocr(block, numeric=numeric)
    if tvo is not None:
        signals.append(tvo)
    signals.append(reading_order_risk(ctx.displaced_in, ctx.in_overlap, ctx.n_columns))
    if block.type == BlockType.table and block.table is not None:
        signals.append(table_consistency(block.table, block.raw_text))
    g = garbage_ratio(block.raw_text, is_table=block.type == BlockType.table)
    if g is not None:
        signals.append(g)

    kw = faith_kwargs(block, ctx, variants)
    faith_result = None
    if block.clean_text is None:
        common = {k: v for k, v in kw.items() if k not in ("variants", "evidence")}
        self_test = check_faithfulness_ex(block.raw_text, block.raw_text, **common)
        if not self_test.result.passed:
            raise ScoringError(f"{block.id}: canonicalizer self-test failed (raw vs raw)")
        signals.append(
            Signal(
                name=SignalName.faithfulness,
                value=1.0,
                critical=True,
                detail="raw (no cleanup yet)",
            )
        )
        faith_passed = True
    else:
        out = check_faithfulness_ex(block.raw_text, block.clean_text, **kw)
        faith_result = out.result
        faith_passed = out.result.passed
        if not faith_passed:
            value, detail = 0.0, _faith_detail(out.result.violations)
            counters["faith_failed"] += 1
        elif fallback is not None:
            value = FAITH_FALLBACK_VALUE
            detail = truncate(f"cleanup candidate rejected ({fallback}); kept deterministic result")
            counters["faith_fallback"] += 1
        elif out.reordered:
            value, detail = FAITH_REORDER_VALUE, "passed via evidence-backed reorder"
        else:
            value, detail = 1.0, "passed"
        signals.append(
            Signal(name=SignalName.faithfulness, value=value, critical=True, detail=detail)
        )
    if numeric:
        shown = "; ".join(specs[:5])
        signals.append(
            Signal(
                name=SignalName.has_numeric_spec,
                value=1.0 if block.numbers_verified else 0.0,
                critical=False,
                detail=truncate(f"numeric spec: {shown} (always reviewed)"),
            )
        )
    outcome, vs = llm_verifier(
        block.raw_text,
        block.clean_text,
        faith_passed=faith_passed,
        plan=plan,
        block_type=block.type,
        hf_strings=ctx.hf_strings,
        page=block.page,
        hf_pages=ctx.hf_pages,
    )
    counters[outcome] += 1
    if vs is not None:
        signals.append(vs)
    conf = combine(signals)
    if learned is not None and learned.promotions:
        # a promoted signal can only lower confidence: take the promoted signals only when
        # they do (the min-of-critical x geometric-mean combiner alone does not guarantee it)
        promoted = promote(signals, learned.promotions)
        if promoted != signals:
            c2 = combine(promoted)
            if conf is not None and c2 is not None and c2 < conf:
                signals, conf = promoted, c2
                learned_why.append("learned: promoted signal critical")
    return BlockScore(
        block_id=block.id,
        signals=sorted(signals, key=lambda s: s.name.value),
        confidence=conf,
        status=assign_status(conf, numeric or forced_queue, threshold).value,  # type: ignore[arg-type]
        has_numeric_spec=numeric,
        numeric_specs=specs,
        faithfulness=faith_result,
        learned_why=learned_why,
    )


def score_document(
    doc: Document,
    blocks: Sequence[Block],
    layouts: Sequence[PageLayout],
    fig_inputs: Mapping[str, FigureInputs],
    variants: Mapping[str, Sequence[NumericVariant]],
    threshold: float,
    plan: VerifierPlan = NO_VERIFIER,
    counters: Counter[str] | None = None,
    fallbacks: Mapping[str, str] | None = None,
    learned: LearnedScoring | None = None,
) -> list[BlockScore]:
    """Score every block of one document; sorted by block id."""
    ctxs = block_contexts(doc, blocks, layouts)
    fallbacks = fallbacks or {}
    lexicon, _ignored = active_lexicon(learned, blocks)
    ordered = sorted(blocks, key=lambda b: b.reading_order)
    out: list[BlockScore] = []
    for b in ordered:
        out.append(
            score_block(
                b,
                ctxs[b.id],
                threshold=threshold,
                fig=fig_inputs.get(b.id),
                variants=variants.get(b.id, ()),
                plan=plan,
                counters=counters,
                fallback=fallbacks.get(b.id),
                learned=learned,
                lexicon=lexicon,
            )
        )
        progress.report(doc.slug, len(out), len(ordered), "block")  # the jobs bar (07 §4.1)
    return sorted(out, key=lambda s: ids.block_sort_key(s.block_id))


# ---------------------------------------------------------------------------------------------
# I/O


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _load_prior(path: Path) -> ScoreFile | None:
    if not path.is_file():
        return None
    try:
        sf = read_json(path, ScoreFile)
    except ValueError:
        return None
    return sf if sf.algo_version == SCORING_ALGO_VERSION else None


def scores_current(paths: ProjectPaths, slug: str) -> bool:
    """Whether the document's scores.json exists, validates and was written by this
    `SCORING_ALGO_VERSION`. A score file of another version reads exactly like a missing one
    on every read path ("not scored yet", design 03 section 2.10a), never as an error.
    Memoised on the file's stat, so a poll costs one `stat`."""
    p = paths.doc(slug).scores
    try:
        st = p.stat()
    except OSError:
        return False
    return _current_at(str(p), st.st_mtime_ns, st.st_size, st.st_ino)


@functools.lru_cache(maxsize=256)
def _current_at(path: str, _mtime_ns: int, _size: int, _ino: int) -> bool:
    return _load_prior(Path(path)) is not None


def _variants_from(prior: ScoreFile | None) -> dict[str, list[NumericVariant]]:
    if prior is None:
        return {}
    return {
        s.block_id: list(s.faithfulness.numeric_variants)
        for s in prior.blocks
        if s.faithfulness is not None and s.faithfulness.numeric_variants
    }


def _figure_inputs(
    paths: ProjectPaths, slug: str, blocks: Sequence[Block], report: FigureReport | None
) -> tuple[dict[str, FigureInputs], dict[str, Any], list[Any]]:
    fig_blocks = [b for b in blocks if b.type == BlockType.figure and b.figure_id]
    if not fig_blocks:
        return {}, {}, []
    if report is None:
        raise ScoringError("figures_report.json missing or stale (run `labor figures`)")
    index = read_json(paths.figures_index, FigureIndex) if paths.figures_index.is_file() else None
    entries = {e.figure_id: e for e in (index.entries if index else []) if e.source_doc == slug}
    ext = {f.figure_id: f for f in report.figures}
    fail = {f.figure_id: f for f in report.failures}
    out: dict[str, FigureInputs] = {}
    sidecar_inputs: dict[str, Any] = {}
    for b in fig_blocks:
        fid = str(b.figure_id)
        if fid not in ext and fid not in fail:
            raise ScoringError(f"{b.id}: no figures_report entry for {fid} (run `labor figures`)")
        sc = paths.figure_file(slug, fid, "json")
        rec = read_json(sc, FigureRecord) if sc.is_file() else None
        fi = FigureInputs(
            extraction=ext.get(fid),
            failure=fail.get(fid),
            dedupe=entries.get(fid),
            attach_rule=rec.attach_rule if rec else FigureInputs().attach_rule,
            articles=list(rec.articles) if rec else [],
        )
        out[b.id] = fi
        if rec is not None:
            sidecar_inputs[fid] = [rec.attach_rule.value, list(rec.articles)]
    dedupe_dump = [entries[k].model_dump(mode="json") for k in sorted(entries)]
    return out, sidecar_inputs, dedupe_dump


def load_clean_overlay(
    dp: DocPaths, raw_by_id: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, str], str | None]:
    """clean.json (module 5) as (block id -> clean_text, block id -> fallback reason, sha of the
    file). No file: empty maps and None. ``raw_by_id``: each block's current raw_text. An
    entry for a block that does not exist, or whose recorded raw_text sha256 differs from the
    block's raw_text now, is an error: clean.json is stale for this parse and must be
    re-generated (never scored as a faithfulness failure of the stale text)."""
    if not dp.clean.is_file():
        return {}, {}, None
    data = dp.clean.read_bytes()
    try:
        cf = CleanFile.model_validate_json(data)
    except ValueError as exc:
        raise ScoringError(f"clean.json is invalid (re-run `labor clean`): {exc}") from exc
    texts: dict[str, str] = {}
    fallbacks: dict[str, str] = {}
    stale: list[str] = []
    for e in cf.blocks:
        if e.block_id not in raw_by_id:
            raise ScoringError(
                f"clean.json names unknown block {e.block_id} (stale for this parse: delete "
                f"{dp.clean.name} and run `labor clean`)"
            )
        if raw_sha256(raw_by_id[e.block_id]) != e.raw_sha256:
            stale.append(e.block_id)
            continue
        texts[e.block_id] = e.clean_text
        reason = fallback_detail(e)
        if reason is not None:
            fallbacks[e.block_id] = reason
    if stale:
        shown = ", ".join(stale[:5]) + (f" (+{len(stale) - 5} more)" if len(stale) > 5 else "")
        raise ScoringError(
            f"clean.json is stale: raw_text changed since cleanup for {shown}; re-run `labor clean`"
        )
    return texts, fallbacks, hashlib.sha256(data).hexdigest()


def fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _apply_sidecars(
    paths: ProjectPaths, slug: str, blocks: Sequence[Block], scores: Sequence[BlockScore]
) -> int:
    """Figure sidecar confidence/review from the figure block's score. Human review decisions
    (anything but queued/auto_approved) are never overwritten. Returns files rewritten."""
    by_id = {s.block_id: s for s in scores}
    n = 0
    for b in blocks:
        if b.type != BlockType.figure or b.figure_id is None:
            continue
        sc = paths.figure_file(slug, b.figure_id, "json")
        s = by_id.get(b.id)
        if s is None or s.confidence is None or not sc.is_file():
            continue
        rec = read_json(sc, FigureRecord)
        upd: dict[str, Any] = {"confidence": s.confidence}
        if rec.review in (BlockStatus.queued, BlockStatus.auto_approved):
            upd["review"] = BlockStatus(s.status)
        new = FigureRecord.model_validate({**rec.model_dump(), **upd})
        data = dump_json(new)
        if sc.read_text(encoding="utf-8") != data:
            write_text_atomic(sc, data)
            n += 1
    return n


def _history_key(confidence: float | None, status: str, signals: Sequence[Signal]) -> str:
    return json.dumps(
        {
            "confidence": confidence,
            "status": status,
            "signals": [s.model_dump(mode="json") for s in signals],
        },
        sort_keys=True,
    )


def _repair_history(path: Path) -> list[str]:
    """The complete lines of the history. A trailing line without its newline (a kill during an
    append) is cut off the file first, so a replay appends exactly what the killed run would
    have."""
    if not path.is_file():
        return []
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        cut = data.rfind(b"\n") + 1
        with open(path, "r+b") as f:
            f.truncate(cut)
        data = data[:cut]
    return [ln for ln in data.decode("utf-8").splitlines() if ln.strip()]


def _append_history(path: Path, fp: str, scores: Sequence[BlockScore]) -> int:
    last: dict[str, str] = {}
    seq = 0
    for line in _repair_history(path):
        h = HistoryEntry.model_validate_json(line)
        seq = max(seq, h.seq)
        last[h.block_id] = _history_key(h.confidence, h.status, h.signals)
    lines: list[str] = []
    for s in scores:
        key = _history_key(s.confidence, s.status, s.signals)
        if last.get(s.block_id) == key:
            continue
        seq += 1
        h = HistoryEntry(
            seq=seq,
            block_id=s.block_id,
            fingerprint=fp[:16],
            confidence=s.confidence,
            status=s.status,
            signals=s.signals,
        )
        lines.append(
            json.dumps(
                h.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        )
    if lines:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    return len(lines)


def _progress(
    slug: str,
    status: str,
    scores: Sequence[BlockScore] | None,
    blocks: Sequence[Block],
    t0: float,
    detail: str | None,
) -> dict[str, Any]:
    types = {b.id: b.type for b in blocks}
    sc = scores or []
    return {
        "doc": slug,
        "stage": "score",
        "status": status,
        "blocks": len(sc) if scores is not None else None,
        "auto_approved": sum(1 for s in sc if s.status == "auto_approved"),
        "queued": sum(
            1
            for s in sc
            if s.status == "queued"
            and types.get(s.block_id) not in (BlockType.header, BlockType.footer)
        ),
        "numeric": sum(1 for s in sc if s.has_numeric_spec),
        "figures": sum(1 for s in sc if types.get(s.block_id) == BlockType.figure),
        "faith_failed": sum(
            1 for s in sc if s.faithfulness is not None and not s.faithfulness.passed
        ),
        "elapsed_ms": int(round((time.perf_counter() - t0) * 1000.0)),
        "detail": detail,
    }


def _detail(counters: Counter[str]) -> str | None:
    """Verifier and reader-availability counters for the progress line."""
    names = {"ok": "verifier_ok", "flag": "verifier_flagged"}
    parts = [
        f"{names.get(k, k)}: {counters[k]}"
        for k in sorted(counters)
        if k in names or k.startswith(("verifier_", "parser_agreement unavailable"))
    ]
    skipped = sum(v for k, v in counters.items() if k.startswith("skip_") and k != "skip_no_clean")
    if skipped:
        parts.append(f"verifier skipped: {skipped}")
    return "; ".join(parts) if parts else None


def _write_outputs(
    paths: ProjectPaths,
    slug: str,
    blocks: Sequence[Block],
    fp: str,
    threshold: float,
    scores: list[BlockScore],
    learning_snapshot: str = "baseline",
) -> None:
    """History first, then scores.json (atomic), then sidecars (only changed bytes). A kill
    between any two steps heals on replay: the history only appends lines that differ from a
    block's last line, and the skip path restores sidecars (module 7, kill-safe resume)."""
    dp = paths.doc(slug)
    _append_history(dp.score_history, fp, scores)
    faults.fault("score.after_history")
    write_json(
        dp.scores,
        ScoreFile(
            doc_id=slug,
            algo_version=SCORING_ALGO_VERSION,
            fingerprint=fp,
            threshold=threshold,
            learning_snapshot=learning_snapshot,
            blocks=scores,
        ),
    )
    faults.fault("score.after_scores")
    _apply_sidecars(paths, slug, blocks, scores)


@dataclass
class _ScoreInputs:
    doc: Document
    blocks: list[Block]
    layouts: list[PageLayout]
    fig_inputs: dict[str, FigureInputs]
    variants: dict[str, list[NumericVariant]]
    fallbacks: dict[str, str]
    prior: ScoreFile | None
    fp: str
    learned: LearnedScoring | None = None


def _score_inputs(paths: ProjectPaths, slug: str, config: ProjectConfig) -> _ScoreInputs:
    dp = paths.doc(slug)
    if not dp.blocks.is_file():
        raise ScoringError("document is not parsed (blocks.json missing)")
    doc = paths.load_document(slug)
    blocks = read_json_list(dp.blocks, Block)
    clean_texts, fallbacks, clean_sha = load_clean_overlay(dp, {b.id: b.raw_text for b in blocks})
    if clean_texts:
        blocks = [
            b.model_copy(update={"clean_text": clean_texts[b.id]}) if b.id in clean_texts else b
            for b in blocks
        ]
    layouts = read_json_list(dp.layout, PageLayout) if dp.layout.is_file() else []
    report = read_json(dp.figure_report, FigureReport) if dp.figure_report.is_file() else None
    fig_inputs, sidecar_inputs, dedupe_dump = _figure_inputs(paths, slug, blocks, report)
    prior = _load_prior(dp.scores)
    variants = _variants_from(prior)
    vref = config.model_for(Task.verifier)
    cref = config.model_for(Task.cleanup)
    learned = load_learned_scoring(paths, config)
    fp = fingerprint(
        {
            "algo": SCORING_ALGO_VERSION,
            "learned": [learned.snapshot, learned.sha] if learned is not None else None,
            "document_sha": _sha(dp.document),
            "blocks_sha": _sha(dp.blocks),
            "layout_sha": _sha(dp.layout),
            "figures_report_sha": _sha(dp.figure_report) if fig_inputs else None,
            "figures_index_entries": dedupe_dump,
            "sidecar_inputs": sidecar_inputs,
            "verifier_ref": vref.model_dump(mode="json") if vref else None,
            "cleanup_ref": cref.model_dump(mode="json") if cref else None,
            "clean_sha": clean_sha,
            "variants": {
                k: [v.model_dump(mode="json") for v in vs] for k, vs in sorted(variants.items())
            },
        }
    )
    return _ScoreInputs(doc, blocks, layouts, fig_inputs, variants, fallbacks, prior, fp, learned)


def score_fingerprint(paths: ProjectPaths, slug: str, config: ProjectConfig) -> str:
    """The fingerprint `scores.json` must carry to be current (pure; no stage runs)."""
    return _score_inputs(paths, slug, config).fp


def _score_doc(
    paths: ProjectPaths,
    slug: str,
    config: ProjectConfig,
    force: bool,
    plan: VerifierPlan,
    emit: Emit,
) -> None:
    t0 = time.perf_counter()
    inp = _score_inputs(paths, slug, config)
    doc, blocks, layouts = inp.doc, inp.blocks, inp.layouts
    fig_inputs, variants, fallbacks = inp.fig_inputs, inp.variants, inp.fallbacks
    prior, fp = inp.prior, inp.fp
    thr = config.threshold_for(slug)
    snap = inp.learned.snapshot if inp.learned is not None else "baseline"
    if not force and prior is not None and prior.fingerprint == fp:
        if prior.threshold != thr:
            # design 6: a threshold change re-runs assign_status on the stored confidences only
            restated = [
                s.model_copy(
                    update={
                        "status": assign_status(
                            s.confidence, s.has_numeric_spec or bool(s.learned_why), thr
                        ).value
                    }
                )
                for s in prior.blocks
            ]
            _write_outputs(paths, slug, blocks, fp, thr, restated, snap)
            emit(_progress(slug, "restatus", restated, blocks, t0, "threshold changed"))
            return
        n = _apply_sidecars(paths, slug, blocks, prior.blocks)
        emit(
            _progress(
                slug,
                "sidecars" if n else "skip",
                prior.blocks,
                blocks,
                t0,
                f"restored {n} sidecars" if n else "up to date",
            )
        )
        return
    counters: Counter[str] = Counter()
    scores = score_document(
        doc, blocks, layouts, fig_inputs, variants, thr, plan, counters, fallbacks, inp.learned
    )
    _write_outputs(paths, slug, blocks, fp, thr, scores, snap)
    emit(_progress(slug, "done", scores, blocks, t0, _detail(counters)))


def run_score(
    paths: ProjectPaths,
    *,
    only: str | None = None,
    force: bool = False,
    providers: ProviderSet | Callable[[], ProviderSet] | None = None,
    emit: Emit = stdout_emit,
) -> list[str]:
    """Score every parsed document (slug order). Returns the slugs that failed."""
    config = paths.load_config()
    slugs = paths.list_slugs()
    if only is not None:
        if only not in slugs:
            emit({"doc": only, "stage": "score", "status": "error", "detail": "unknown document"})
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
                    cache_dir=paths.llm_cache,
                    sink=JsonlSink(paths.llm_log),
                )
            )
        return built[0]

    plan = plan_verifier(config, get_providers)
    failed: list[str] = []
    for slug in slugs:
        t0 = time.perf_counter()
        try:
            _score_doc(paths, slug, config, force, plan, emit)
        except Exception as exc:
            failed.append(slug)
            out = _progress(slug, "error", None, [], t0, f"{type(exc).__name__}: {exc}")
            emit(out)
    return failed


def load_scored_blocks(paths: ProjectPaths, slug: str) -> list[Block]:
    """blocks.json merged with the scores.json and clean.json overlays, validated as contract
    Blocks. Modules 4-11 and the API read blocks only through this."""
    dp = paths.doc(slug)
    blocks = read_json_list(dp.blocks, Block)
    sf = _load_prior(dp.scores)
    if sf is None:
        raise ScoringError(
            f"{slug}: scores.json missing or from another algo version (run `labor score`)"
        )
    by_id = {s.block_id: s for s in sf.blocks}
    clean_texts, _, _ = load_clean_overlay(dp, {b.id: b.raw_text for b in blocks})
    out: list[Block] = []
    for b in blocks:
        s = by_id.get(b.id)
        if s is None:
            raise ScoringError(f"{slug}: {b.id} has no score (run `labor score`)")
        fields: dict[str, Any] = {
            "confidence": s.confidence,
            "signals": [x.model_dump(mode="json") for x in s.signals],
            "status": s.status,
            "has_numeric_spec": s.has_numeric_spec,
            "faithfulness": s.faithfulness.model_dump(mode="json") if s.faithfulness else None,
        }
        if b.id in clean_texts:
            fields["clean_text"] = clean_texts[b.id]
        out.append(Block.model_validate({**b.model_dump(mode="json"), **fields}))
    return out
