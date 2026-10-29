"""`labor check <project> [--live] [--keep]`: the end-to-end smoke check (design 07 section 6).

Works on a temporary copy, so the project is never touched. Mock mode (default) mocks every
model call; `--live` runs against real local models and skips cleanly when they are missing.
Checks that exist now (module 7): K1-K9. Assemble/export checks arrive with module 11."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockStatus
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.group import GroupsFile
from manuallabor.contracts.io import read_json, read_json_list, write_json
from manuallabor.contracts.selection import Selection
from manuallabor.jobs.providers import ProviderMode
from manuallabor.project import ProjectPaths

__all__ = ["Check", "CheckCtx", "run_check"]

SKIP_EXIT_REQUIRED = 4


@dataclass
class CheckCtx:
    paths: ProjectPaths
    store: Any
    mode: ProviderMode
    live: bool
    lines: list[dict[str, Any]] = field(default_factory=list)


Check = tuple[str, Callable[[CheckCtx], str | None]]


@dataclass
class Row:
    name: str
    status: str
    detail: str
    ms: int


# -- the checks --------------------------------------------------------------------------------


def _slugs(ctx: CheckCtx) -> list[str]:
    return ctx.paths.list_slugs()


def k1_fresh(ctx: CheckCtx) -> str | None:
    from manuallabor.jobs.graph import project_status

    st = project_status(ctx.paths, None)
    bad = [
        f"{d.doc_id}:{n.node}={n.state}" + (f" ({n.reason})" if n.reason else "")
        for d in st.docs
        for n in d.nodes
        if n.state != "fresh"
    ]
    if not st.docs:
        raise AssertionError("no documents")
    if bad:
        raise AssertionError("not fresh: " + "; ".join(bad))
    return f"{len(st.docs)} docs x {len(st.docs[0].nodes)} nodes fresh"


def _jsonschema(rec: FigureRecord) -> None:
    import jsonschema

    here = Path(__file__).resolve().parents[1] / "schemas" / "FigureRecord.json"
    schema = (
        json.loads(here.read_text(encoding="utf-8"))
        if here.is_file()
        else FigureRecord.model_json_schema()
    )
    jsonschema.validate(rec.model_dump(mode="json"), schema)


def k2_artifacts(ctx: CheckCtx) -> str | None:
    from manuallabor.cleanup.pipeline import cleanable
    from manuallabor.cleanup.types import AttachFile, CleanFile, DescribeFile
    from manuallabor.figures.types import FigureReport
    from manuallabor.grouping.pipeline import check_partition
    from manuallabor.scoring.types import ScoreFile
    from manuallabor.state.data import ProjectData

    p = ctx.paths
    data = ProjectData(p, ctx.store)
    selected = set(data.selection().block_ids)
    n_sidecars = n_blocks = 0
    for slug in _slugs(ctx):
        dp = p.doc(slug)
        read_json(dp.document, Document)
        blocks = read_json_list(dp.blocks, Block)
        n_blocks += len(blocks)
        rep = read_json(dp.figure_report, FigureReport)
        for f in rep.figures:
            sc = p.figure_file(slug, f.figure_id, "json")
            rec = read_json(sc, FigureRecord)
            _jsonschema(rec)
            for rel in (rec.file, rec.svg):
                if rel is not None and not (p.figure_dir(slug) / rel).resolve().is_file():
                    raise AssertionError(f"{rec.id}: {rel} does not exist")
            n_sidecars += 1
        sf = read_json(dp.scores, ScoreFile)
        ids_scored = [s.block_id for s in sf.blocks]
        if sorted(ids_scored) != sorted(b.id for b in blocks) or len(set(ids_scored)) != len(
            ids_scored
        ):
            raise AssertionError(f"{slug}: scores.json does not cover every block exactly once")
        gf = read_json(dp.groups, GroupsFile)
        problems = check_partition(blocks, gf)
        if problems:
            raise AssertionError(f"{slug}: {problems[:3]}")
        cf = read_json(dp.clean, CleanFile)
        want = {b.id for b in blocks if b.id in selected and cleanable(b)}
        got = {e.block_id for e in cf.blocks}
        if got != want:
            raise AssertionError(
                f"{slug}: clean.json entries differ from the selected cleanable blocks "
                f"(missing {sorted(want - got)[:3]}, extra {sorted(got - want)[:3]})"
            )
        read_json(dp.attach, AttachFile)
        read_json(dp.describe, DescribeFile)
    sel = read_json(p.selection, Selection)
    return f"{n_blocks} blocks, {n_sidecars} sidecars, selection {len(sel.block_ids)} blocks"


def k3_faithfulness(ctx: CheckCtx) -> str | None:
    from manuallabor.scoring.pipeline import load_scored_blocks

    n = checked = 0
    for slug in _slugs(ctx):
        for b in load_scored_blocks(ctx.paths, slug):
            if b.status == BlockStatus.auto_approved and b.clean_text is not None:
                checked += 1
                if b.faithfulness is None or not b.faithfulness.passed:
                    n += 1
    if n:
        raise AssertionError(f"{n} auto-approved blocks fail the faithfulness check")
    return f"0 violations in {checked} auto-approved cleaned blocks"


def k4_accounting(ctx: CheckCtx) -> str | None:
    total = 0
    for slug in _slugs(ctx):
        dp = ctx.paths.doc(slug)
        blocks = read_json_list(dp.blocks, Block)
        gf = read_json(dp.groups, GroupsFile)
        total += len(blocks)
        for view, groups in (("structure", gf.structure), ("topic", gf.topics)):
            seen: dict[str, int] = {}
            for g in groups:
                for b in g.block_ids:
                    seen[b] = seen.get(b, 0) + 1
            for u in gf.unassigned:
                if u.view.value == view and u.reason.value == "header_footer":
                    seen[u.block_id] = seen.get(u.block_id, 0) + 1
            missing = [b.id for b in blocks if b.id not in seen]
            dup = [b for b, n in seen.items() if n != 1]
            if missing or dup:
                raise AssertionError(f"{slug}/{view}: missing {missing[:3]} duplicated {dup[:3]}")
    return f"{total} blocks each in exactly one group per view"


def k5_figures(ctx: CheckCtx) -> str | None:
    from manuallabor.cleanup.types import AttachFile

    figs = unresolved = 0
    for slug in _slugs(ctx):
        af = read_json(ctx.paths.doc(slug).attach, AttachFile)
        unresolved += len(af.unresolved_refs)
        for art in af.articles:
            for a in art.figures:
                figs += 1
                if not ctx.paths.figure_file(slug, a.figure_id, "json").is_file():
                    raise AssertionError(f"{a.figure_id}: no sidecar")
                if not ctx.paths.figure_file(slug, a.figure_id, "png").is_file():
                    raise AssertionError(f"{a.figure_id}: no image")
    return f"{figs} attachments resolved; {unresolved} unresolved caption refs (reported)"


def _hash_tree(paths: ProjectPaths) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in (paths.docs, paths.figures_root):
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if f.is_file() and f.name != "stages.json":
                out[str(f.relative_to(paths.root))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def k6_idempotent(ctx: CheckCtx) -> str | None:
    from manuallabor.jobs.inline import run_inline
    from manuallabor.state.models import RunPlanIn

    before = _hash_tree(ctx.paths)
    lines: list[dict[str, Any]] = []
    res = run_inline(
        ctx.paths,
        RunPlanIn(to="score2"),
        mode=ctx.mode,
        emit=lines.append,
        store=ctx.store,
        include_fresh=True,
    )
    if not res.ok:
        raise AssertionError(f"second run failed: {res.failed}")
    stage_lines = [o for o in lines if "stage" in o and o.get("stage") not in ("figures_dedupe",)]
    ran = [o for o in stage_lines if o.get("status") not in ("skip", "sidecars", "blocked")]
    if ran:
        raise AssertionError(f"second run did work: {ran[:2]}")
    after = _hash_tree(ctx.paths)
    if before != after:
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        raise AssertionError(f"files changed on a second run: {changed[:3]}")
    return f"{len(stage_lines)} stage calls, all skip; {len(after)} files unchanged"


def k7_mock_only(ctx: CheckCtx) -> str | None:
    if ctx.live:
        return "SKIP"
    log = ctx.paths.llm_log
    if not log.is_file():
        return "no LLM calls"
    n = 0
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        n += 1
        if json.loads(line).get("provider") != "mock":
            raise AssertionError(f"non-mock LLM call: {line[:120]}")
    return f"{n} LLM calls, all mock"


def k8_state(ctx: CheckCtx) -> str | None:
    store = ctx.store
    if not store.integrity_ok():
        raise AssertionError("project.db integrity_check failed")
    prev = 0
    n = 0
    for a in store.iter_actions():
        if a.id <= prev:
            raise AssertionError(f"action ids not monotonic at {a.id}")
        prev = a.id
        n += 1
    body = store.get_selection_json()
    file_sel = read_json(ctx.paths.selection, Selection)
    if body is None or Selection.model_validate_json(body) != file_sel:
        raise AssertionError("selection.json differs from the DB selection")
    return f"integrity ok, {n} actions monotonic, selection == DB"


def k9_baseline(ctx: CheckCtx) -> str | None:
    for slug in _slugs(ctx):
        dp = ctx.paths.doc(slug)
        for f in (dp.groups, dp.clean):
            snap = json.loads(f.read_text(encoding="utf-8")).get("learning_snapshot")
            if snap != "baseline":
                raise AssertionError(f"{f.name}: learning_snapshot={snap!r}")
    return "learning provenance = baseline"


CHECKS: list[Check] = [
    ("K1 nodes fresh", k1_fresh),
    ("K2 artifacts validate", k2_artifacts),
    ("K3 faithfulness", k3_faithfulness),
    ("K4 block accounting", k4_accounting),
    ("K5 figures resolve", k5_figures),
    ("K6 idempotent rerun", k6_idempotent),
    ("K7 mock only", k7_mock_only),
    ("K8 state", k8_state),
    ("K9 baseline learning", k9_baseline),
]


# -- the driver --------------------------------------------------------------------------------

_IGNORE = shutil.ignore_patterns(
    "project.db", "project.db-*", "logs", ".labor*.lock", ".uploads", "pages", "pages_view"
)


def _print_table(rows: Sequence[Row]) -> None:
    w = max([len(r.name) for r in rows] + [5])
    print(f"{'check':<{w}}  {'status':<6}  {'ms':>6}  detail")
    for r in rows:
        print(f"{r.name:<{w}}  {r.status:<6}  {r.ms:>6}  {r.detail}")


def _live_preflight(tmp_cfg: Path) -> tuple[bool, str, list[str]]:
    """(ok, reason, pull commands). Applies the small tier when the config is all-mock."""
    from manuallabor.contracts.config import ProjectConfig
    from manuallabor.contracts.enums import Task
    from manuallabor.providers import probe as pr

    result = pr.run_probe()
    table = pr.suggest(result)
    if not result.ollama.reachable:
        return False, f"Ollama is not reachable at {result.ollama.host}", ["ollama serve"]
    cfg = read_json(tmp_cfg, ProjectConfig)
    refs = [
        getattr(cfg.models, t) for t in ("cleanup", "grouping", "vision", "embeddings", "verifier")
    ]
    if any(r is not None and r.provider == "mock" for r in refs):
        try:
            pr.apply_tier(tmp_cfg, table, "small", probe=result)
        except pr.ApplyError as exc:
            return False, str(exc), []
        cfg = read_json(tmp_cfg, ProjectConfig)
    have = {m.name for m in result.ollama.models}
    have |= {n.removesuffix(":latest") for n in have}
    missing: list[str] = []
    for t in ("cleanup", "grouping", "vision", "embeddings", "verifier"):
        ref = cfg.model_for(Task(t))
        if ref is not None and ref.provider == "ollama" and ref.model not in have:
            missing.append(ref.model)
    if missing:
        pulls = [f"ollama pull {m}" for m in sorted(set(missing))]
        return False, f"missing Ollama model(s): {', '.join(sorted(set(missing)))}", pulls
    return True, "", []


def run_check(
    project: Path,
    *,
    live: bool = False,
    keep: bool = False,
    extra_checks: Sequence[Check] = (),
) -> int:
    from manuallabor.ingest import IngestError, ingest_files
    from manuallabor.jobs.inline import run_inline
    from manuallabor.jobs.providers import mockify
    from manuallabor.state.data import ProjectData
    from manuallabor.state.models import RunPlanIn, SelectionOp
    from manuallabor.state.scope import ScopeService
    from manuallabor.state.store import Store

    project = Path(project).resolve()
    tmp_root = Path(tempfile.mkdtemp(prefix="labor-check-"))
    work = tmp_root / project.name
    shutil.copytree(project, work, ignore=_IGNORE)
    paths = ProjectPaths(work)
    cfg = paths.ensure_config()
    rows: list[Row] = []
    mode: ProviderMode = "config" if live else "mock"
    if live:
        ok, reason, pulls = _live_preflight(paths.config)
        if not ok:
            print(f"SKIP live: {reason}")
            for c in pulls:
                print(f"  {c}")
            shutil.rmtree(tmp_root, ignore_errors=True)
            return SKIP_EXIT_REQUIRED if os.environ.get("MANUALLABOR_LIVE_REQUIRED") == "1" else 0
    else:
        write_json(paths.config, mockify(cfg))
    cfg = paths.load_config()
    store = Store.open(paths)
    failed = False

    def timed(name: str, fn: Callable[[], str | None]) -> None:
        nonlocal failed
        t0 = time.monotonic()
        try:
            detail = fn() or ""
            status = "SKIP" if detail == "SKIP" else "PASS"
            if status == "SKIP":
                detail = "live mode"
        except Exception as exc:
            failed = True
            status = "FAIL"
            detail = f"{type(exc).__name__}: {exc}"
            if os.environ.get("LABOR_CHECK_TRACE"):
                traceback.print_exc()
        rows.append(Row(name, status, detail, int((time.monotonic() - t0) * 1000)))

    ctx = CheckCtx(paths=paths, store=store, mode=mode, live=live)
    from manuallabor.state.errors import LockHeld
    from manuallabor.state.lock import ProjectLock

    locks = [
        ProjectLock(paths.lock, cmd="labor check"),
        ProjectLock(paths.worker_lock, cmd="labor check"),
    ]
    try:
        try:
            for lk in locks:
                lk.acquire()
        except LockHeld as exc:  # a temp copy has no other holder; defensive
            print(str(exc), file=sys.stderr)
            return 3

        def pipeline() -> str:
            if not paths.sources.is_dir() or not any(paths.sources.iterdir()):
                raise AssertionError("project has no sources/")
            registered = {d.filename for d in paths.list_documents()}
            todo = [
                f
                for f in sorted(paths.sources.iterdir())
                if f.is_file() and f.name not in registered
            ]
            provider = None
            if mode == "mock":
                from manuallabor.contracts.enums import Task
                from manuallabor.jobs.providers import provider_set_factory
                from manuallabor.providers.sinks import JsonlSink

                provider = provider_set_factory(paths, cfg, "mock", JsonlSink(paths.llm_log))().get(
                    Task.metadata
                )
            if todo:
                try:
                    ingest_files(paths, todo, provider=provider, emit=lambda o: None)
                except IngestError as exc:
                    raise AssertionError(f"ingest: {exc}") from exc
            lines: list[dict[str, Any]] = []
            res = run_inline(
                paths, RunPlanIn(to="group"), mode=mode, emit=lines.append, store=store
            )
            if not res.ok:
                raise AssertionError(f"run to group failed: {res.failed} {_errs(lines)}")
            data = ProjectData(paths, store)
            from manuallabor.grouping.selection import default_selection

            sel = default_selection(paths, data.all_groups())
            ScopeService(paths, store, data).apply(
                SelectionOp(
                    op="select", block_ids=list(sel.block_ids), request_id="cli-check-select"
                )
            )
            res = run_inline(
                paths, RunPlanIn(to="score2"), mode=mode, emit=lines.append, store=store
            )
            ctx.lines.extend(lines)
            if not res.ok:
                raise AssertionError(f"run to score2 failed: {res.failed} {_errs(lines)}")
            n = len(paths.list_slugs())
            return f"{n} docs ingested, scored, grouped, selected, cleaned"

        timed("pipeline run", pipeline)
        if not failed:
            for name, fn in [*CHECKS, *extra_checks]:
                timed(name, lambda fn=fn: fn(ctx))  # type: ignore[misc]
        else:
            rows.append(Row("K1-K9", "SKIP", "pipeline did not complete", 0))
    finally:
        for lk in locks:
            lk.release()
        store.close()
    _print_table(rows)
    if failed:
        print(f"\nFAIL: kept {work} for inspection")
        return 1
    if keep:
        print(f"\nkept {work}")
    else:
        shutil.rmtree(tmp_root, ignore_errors=True)
    print("\nlabor check: all checks passed")
    return 0


def _errs(lines: Sequence[dict[str, Any]]) -> str:
    errs = [o for o in lines if o.get("status") == "error"]
    return "; ".join(f"{o.get('stage')} {o.get('doc')}: {o.get('detail')}" for o in errs[:3])
