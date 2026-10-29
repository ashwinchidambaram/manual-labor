"""Plan and execute stage-graph nodes (design 07 section 3.3).

`make_plan` decides what is not fresh; `execute` runs it node-major (every doc of a node, in
slug order, before the next node), one stage call per (node, doc) unit, and keeps
`docs/<slug>/stages.json` true. Stages never run inline in a script: callers are `labor ...`
or `python -m manuallabor.jobs.worker` (both have `__main__` guards for the spawn pool)."""

from __future__ import annotations

import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from manuallabor import faults
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.llm import LLMCallLog
from manuallabor.jobs import graph
from manuallabor.jobs.providers import ProviderMode
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import LogSink, ProviderSet

__all__ = [
    "Cancelled",
    "ExecResult",
    "Heartbeat",
    "PROJECT_NODES",
    "Plan",
    "clean_stray_tmp",
    "execute",
    "make_plan",
    "make_project_plan",
    "run_node",
    "run_nodes",
]

Emit = Callable[[dict[str, Any]], None]
EXEC_NODES = ("parse", "figures", "score", "group", "clean", "score2")
PROJECT_NODES = ("assemble", "export")  # project-level (module 11): their unit slug is ""


class Cancelled(BaseException):
    """Raised inside a stage when a cancel was requested (BaseException: stages catch
    Exception per document and must not swallow it)."""


@dataclass
class Plan:
    units: list[tuple[str, str]]
    to: str = "score2"
    force: list[str] = field(default_factory=list)
    allow_reparse: bool = False
    provider_mode: ProviderMode = "config"
    refused: list[tuple[str, str]] = field(default_factory=list)  # (slug, reason)

    def to_json(self) -> dict[str, Any]:
        return {
            "to": self.to,
            "force": sorted(self.force),
            "allow_reparse": self.allow_reparse,
            "mode": self.provider_mode,
            "units": [list(u) for u in self.units],
            "refused": [list(r) for r in self.refused],
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Plan:
        return cls(
            units=[(str(n), str(s)) for n, s in d["units"]],
            to=str(d.get("to", "score2")),
            force=[str(x) for x in d.get("force", [])],
            allow_reparse=bool(d.get("allow_reparse", False)),
            provider_mode=d.get("mode", "config"),
            refused=[(str(a), str(b)) for a, b in d.get("refused", [])],
        )


@dataclass
class ExecResult:
    failed: dict[str, list[str]] = field(default_factory=dict)  # node -> slugs
    blocked: dict[str, list[str]] = field(default_factory=dict)
    refused: list[tuple[str, str]] = field(default_factory=list)
    units_done: int = 0
    errors: list[str] = field(default_factory=list)  # "<node> <slug>: <message>" per failure

    @property
    def ok(self) -> bool:
        return not self.failed and not self.refused and not self.blocked

    def error_message(self, limit: int = 500) -> str | None:
        """The first failure's actual message (for the job row), at most `limit` chars."""
        if self.errors:
            return self.errors[0][:limit]
        if self.refused:
            slug, why = self.refused[0]
            return f"plan {slug}: {why}"[:limit]
        return None


class Heartbeat:
    """LLM call sink wrapper: counts calls, fires the `llm.after_calls` fault points, reports
    liveness and raises Cancelled between calls when a cancel was requested."""

    def __init__(
        self,
        inner: LogSink,
        *,
        on_beat: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.inner = inner
        self.on_beat = on_beat
        self.cancelled = cancelled
        self.node = ""
        self.total = 0
        self.by_node: dict[str, int] = {}

    def __call__(self, log: LLMCallLog) -> None:
        self.inner(log)
        self.total += 1
        n = self.by_node.get(self.node, 0) + 1
        self.by_node[self.node] = n
        if self.on_beat is not None:
            self.on_beat(self.total)
        faults.fault(f"llm.after_calls:{self.total}")
        faults.fault(f"llm.after_calls:{self.node}:{n}")
        if self.cancelled():
            raise Cancelled()


def clean_stray_tmp(paths: ProjectPaths) -> int:
    """Delete `*.tmp` files (and half-built snapshot dirs) a SIGKILL left behind. The caller
    holds the worker lock, so no writer is active."""
    import shutil

    n = 0
    for root in (paths.docs, paths.figures_root, paths.learning):
        if root.is_dir():
            for p in root.rglob("*.tmp"):
                if p.is_file():
                    p.unlink()
                    n += 1
    snaps = paths.learning / "snapshots"
    if snaps.is_dir():
        for d in snaps.glob(".tmp-*"):
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


# -- planning ----------------------------------------------------------------------------------


def _decision_count(paths: ProjectPaths, slug: str) -> int:
    if not paths.db.is_file():
        return 0
    from manuallabor.state.store import Store

    try:
        store = Store.open(paths, readonly=True)
    except Exception:
        return 0
    try:
        return len(store.decisions(doc_id=slug))
    except Exception:
        return 0
    finally:
        store.close()


def _has_decisions(paths: ProjectPaths, slug: str) -> bool:
    return _decision_count(paths, slug) > 0


def reparse_refusal(n: int) -> str:
    """The re-parse guard's message (01 section 14.12): names the decisions at stake."""
    return (
        f"parse would replace blocks that have {n} decision(s); they would be orphaned. "
        "Use --discard-decisions to re-parse anyway"
    )


def make_plan(
    paths: ProjectPaths,
    cfg: ProjectConfig,
    *,
    to: str = "score2",
    docs: list[str] | None = None,
    force: Collection[str] = (),
    allow_reparse: bool = False,
    provider_mode: ProviderMode = "config",
    include_fresh: bool = False,
) -> Plan:
    if to not in EXEC_NODES:
        raise ValueError(f"--to must be one of {', '.join(EXEC_NODES)}, got {to!r}")
    for f in force:
        if f not in EXEC_NODES:
            raise ValueError(f"cannot force {f!r}; nodes: {', '.join(EXEC_NODES)}")
    slugs = paths.list_slugs()
    if docs is not None:
        unknown = sorted(set(docs) - set(slugs))
        if unknown:
            raise ValueError(f"unknown document(s): {', '.join(unknown)}")
        slugs = [s for s in slugs if s in docs]
    last = EXEC_NODES.index(to)
    per_doc: dict[str, list[str]] = {}
    refused: list[tuple[str, str]] = []
    for slug in slugs:
        states = {s.node: s for s in graph.doc_node_states(paths, slug, cfg)}
        chosen: list[str] = []
        planning = include_fresh
        for node in EXEC_NODES[: last + 1]:
            st = states[node].state
            if node in force or st != "fresh":
                planning = True
            if planning:
                chosen.append(node)
        n_dec = _decision_count(paths, slug) if "parse" in chosen and not allow_reparse else 0
        if n_dec:
            refused.append((slug, reparse_refusal(n_dec)))
            continue
        if chosen:
            per_doc[slug] = chosen
    units = [
        (node, slug) for node in EXEC_NODES for slug in sorted(per_doc) if node in per_doc[slug]
    ]
    return Plan(
        units=units,
        to=to,
        force=sorted(force),
        allow_reparse=allow_reparse,
        provider_mode=provider_mode,
        refused=refused,
    )


def make_project_plan(
    paths: ProjectPaths,
    cfg: ProjectConfig,
    *,
    to: str = "export",
    docs: list[str] | None = None,
    force: Collection[str] = (),
    allow_reparse: bool = False,
    provider_mode: ProviderMode = "config",
    include_fresh: bool = False,
) -> Plan:
    """Every stale document node up to score2, then the project-level nodes up to `to`
    (`assemble` or `export`; `export` includes `assemble`). Forcing a project node re-runs it."""
    if to not in PROJECT_NODES:
        raise ValueError(f"--to must be one of {', '.join(PROJECT_NODES)}, got {to!r}")
    doc_force = [f for f in force if f not in PROJECT_NODES]
    base = make_plan(
        paths,
        cfg,
        to="score2",
        docs=docs,
        force=doc_force,
        allow_reparse=allow_reparse,
        provider_mode=provider_mode,
        include_fresh=include_fresh,
    )
    tail = [(n, "") for n in PROJECT_NODES[: PROJECT_NODES.index(to) + 1]]
    return Plan(
        units=[*base.units, *tail],
        to=to,
        force=sorted(force),
        allow_reparse=allow_reparse,
        provider_mode=provider_mode,
        refused=base.refused,
    )


# -- execution ---------------------------------------------------------------------------------


def _stage(
    paths: ProjectPaths,
    node: str,
    slug: str,
    force: bool,
    emit: Emit,
    providers: Callable[[], ProviderSet] | None,
    extra: dict[str, Any],
) -> bool:
    """Run one (node, doc) unit. True when the stage reports the doc as done."""
    if node == "parse":
        from manuallabor.parse.pipeline import parse_project

        failed_n = parse_project(
            paths, force=force, only=slug, emit=emit, workers=extra.get("workers")
        )
        return failed_n == 0
    if node == "figures":
        from manuallabor.figures.pipeline import run_figures

        return slug not in run_figures(paths, only=slug, force=force, emit=emit)
    if node in ("score", "score2"):
        from manuallabor.scoring.pipeline import run_score

        return slug not in run_score(paths, only=slug, force=force, providers=providers, emit=emit)
    if node == "group":
        from manuallabor.grouping.pipeline import run_group

        return slug not in run_group(paths, only=slug, force=force, providers=providers, emit=emit)
    if node == "clean":
        from manuallabor.cleanup.pipeline import run_clean

        return slug not in run_clean(
            paths,
            only=slug,
            force=force,
            providers=providers,
            emit=emit,
            llm_mode=extra.get("llm_mode"),
            describe=extra.get("describe"),
            rescore=False,
        )
    raise ValueError(node)


def _project_unit(
    paths: ProjectPaths,
    node: str,
    plan: Plan,
    emit: Emit,
    res: ExecResult,
    extra: dict[str, Any],
    tag_node: bool,
    on_unit: Callable[[str, str, str], None] | None,
) -> None:
    """One project-level unit (`assemble` / `export`); blocked when any document unit failed."""
    t0 = time.monotonic()

    def tagged(obj: dict[str, Any]) -> None:
        emit({**obj, "node": node} if tag_node else obj)

    if res.failed or res.blocked or res.refused:
        tagged({"doc": "", "stage": node, "status": "blocked"})
        res.blocked.setdefault(node, []).append("")
        status = "blocked"
    else:
        from manuallabor.export import pipeline as ep
        from manuallabor.export.types import GateLocked

        clock = extra.get("clock") or ep.resolve_clock()
        force = node in plan.force
        try:
            if node == "assemble":
                ep.run_assemble(paths, None, clock=clock, emit=tagged, force=force)
            else:
                ep.run_export(paths, None, clock=clock, emit=tagged, force=force)
            res.units_done += 1
            status = "done"
        except Cancelled:
            raise
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            tagged({"doc": "", "stage": node, "status": "error", "detail": detail})
            if isinstance(exc, GateLocked):
                tagged(
                    {"doc": "", "stage": node, "status": "locked", "blockers": exc.blockers[:20]}
                )
            res.failed.setdefault(node, []).append("")
            status = "failed"
    emit({"event": "unit_done", "node": node, "doc": "", "status": status,
          "elapsed_ms": int((time.monotonic() - t0) * 1000)})  # fmt: skip
    if on_unit is not None:
        on_unit(node, "", status)


def execute(
    paths: ProjectPaths,
    plan: Plan,
    *,
    emit: Emit,
    providers: Callable[[], ProviderSet] | None,
    cancelled: Callable[[], bool] = lambda: False,
    heartbeat: Heartbeat | None = None,
    on_unit: Callable[[str, str, str], None] | None = None,
    tag_node: bool = True,
    extra: dict[str, Any] | None = None,
) -> ExecResult:
    """Run the plan. The caller holds the worker lock (and the project lock where it must)."""
    extra = extra or {}
    cfg = paths.load_config() if paths.config.is_file() else None
    res = ExecResult(refused=list(plan.refused))
    for slug, why in plan.refused:
        emit({"doc": slug, "stage": "plan", "status": "error", "detail": why})
    clean_stray_tmp(paths)
    stages: dict[str, graph.Stages] = {}
    blocked: set[str] = set()
    for node, slug in plan.units:
        if cancelled():
            raise Cancelled()
        if heartbeat is not None:
            heartbeat.node = node
        if node in PROJECT_NODES:
            _project_unit(paths, node, plan, emit, res, extra, tag_node, on_unit)
            continue
        if slug in blocked:
            if tag_node:
                emit({"doc": slug, "stage": node, "status": "blocked", "node": node})
            res.blocked.setdefault(node, []).append(slug)
            if on_unit is not None:
                on_unit(node, slug, "blocked")
            continue

        unit_lines: list[dict[str, Any]] = []

        def tagged(
            obj: dict[str, Any], _n: str = node, _lines: list[dict[str, Any]] = unit_lines
        ) -> None:
            _lines.append(obj)
            emit({**obj, "node": _n} if tag_node else obj)

        st = stages.get(slug) or graph.load_stages(paths, slug)
        stages[slug] = st
        was_fresh = (
            cfg is not None and graph.node_state(paths, slug, node, cfg, st).state == "fresh"
        )
        t0 = time.monotonic()
        faults.delay(f"node.before:{node}:{slug}")
        try:
            ok = _stage(paths, node, slug, node in plan.force, tagged, providers, extra)
        except Cancelled:
            raise
        except Exception as exc:  # a stage that raises outright fails its doc
            tagged(
                {
                    "doc": slug,
                    "stage": node,
                    "status": "error",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
            ok = False
        faults.fault(f"node.after:{node}:{slug}")  # the unit is on disk, stages.json not yet
        did_work = any(
            o.get("status") != "skip" for o in unit_lines if o.get("stage") != "figures_dedupe"
        )
        # a node that verified itself current without doing anything leaves stages.json alone,
        # otherwise every no-op `labor parse` would mark everything downstream stale
        if not ok or node in plan.force or did_work or not was_fresh:
            st.record(node, "done" if ok else "failed", None, None if ok else "stage failed")
            graph.save_stages(paths, slug, st)
        if ok:
            res.units_done += 1
        else:
            res.failed.setdefault(node, []).append(slug)
            blocked.add(slug)
            details = [
                str(o["detail"])
                for o in unit_lines
                if o.get("status") == "error" and o.get("detail") is not None
            ]
            msg = details[-1] if details else "stage failed"
            res.errors.append(f"{node} {slug}: {msg}")
        status = "done" if ok else "failed"
        emit({"event": "unit_done", "node": node, "doc": slug, "status": status,
              "elapsed_ms": int((time.monotonic() - t0) * 1000)})  # fmt: skip
        if on_unit is not None:
            on_unit(node, slug, status)
    return res


def run_node(
    paths: ProjectPaths,
    node: str,
    *,
    only: str | None = None,
    force: bool = False,
    emit: Emit,
    providers: Callable[[], ProviderSet] | None = None,
    extra: dict[str, Any] | None = None,
    allow_reparse: bool = False,
) -> list[str]:
    """Run exactly one node for one or every document (the `labor parse|figures|...` commands)
    and keep stages.json true. Returns the slugs that failed or were refused. Output lines are
    the stage's own (no `node` tag), exactly as before module 7. A parse that would run on a
    document with decisions is refused (the same guard as `make_plan`) unless `allow_reparse`."""
    slugs = paths.list_slugs()
    if only is not None:
        if only not in slugs:
            emit(
                {
                    "doc": only,
                    "stage": node.rstrip("2"),
                    "status": "error",
                    "detail": "unknown document",
                }
            )
            return [only]
        slugs = [only]
    refused: list[tuple[str, str]] = []
    if node == "parse" and not allow_reparse:
        cfg = paths.load_config()
        for s in slugs:
            st = next(x for x in graph.doc_node_states(paths, s, cfg) if x.node == "parse")
            n_dec = _decision_count(paths, s) if force or st.state != "fresh" else 0
            if n_dec:
                refused.append((s, reparse_refusal(n_dec)))
        slugs = [s for s in slugs if s not in {r for r, _ in refused}]
    plan = Plan(
        units=[(node, s) for s in slugs],
        to=node,
        force=[node] if force else [],
        allow_reparse=allow_reparse,
        refused=refused,
    )
    lines: list[dict[str, Any]] = []

    def out(o: dict[str, Any]) -> None:
        if o.get("event") == "unit_done":
            return
        lines.append(o)
        emit(o)

    res = execute(paths, plan, emit=out, providers=providers, tag_node=False, extra=extra)
    return sorted({*res.failed.get(node, []), *(s for s, _ in res.refused)})


def run_nodes(
    paths: ProjectPaths,
    nodes: list[str],
    *,
    only: str | None = None,
    force: Collection[str] = (),
    emit: Emit,
    providers: Callable[[], ProviderSet] | None = None,
    extra: dict[str, Any] | None = None,
) -> list[str]:
    """Like `run_node` for several nodes, document-major (doc A: every node, then doc B ...):
    the order `labor clean` has always printed (clean, attach, describe, score per document).
    A document whose node failed does not run its later nodes. Returns the failed slugs."""
    slugs = paths.list_slugs()
    if only is not None:
        if only not in slugs:
            emit({"doc": only, "stage": nodes[0], "status": "error", "detail": "unknown document"})
            return [only]
        slugs = [only]
    plan = Plan(units=[(n, s) for s in slugs for n in nodes], to=nodes[-1], force=sorted(force))

    def out(o: dict[str, Any]) -> None:
        if o.get("event") != "unit_done":
            emit(o)

    res = execute(paths, plan, emit=out, providers=providers, tag_node=False, extra=extra)
    return sorted({s for slugs_ in res.failed.values() for s in slugs_})


def stages_path(paths: ProjectPaths, slug: str) -> Path:
    return paths.doc(slug).stages
