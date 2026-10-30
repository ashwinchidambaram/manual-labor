"""Stage graph: per-document node states (design 07 section 3.1-3.2) and project status.

A node is `fresh`, `stale`, `missing` or `failed`; the rules below are evaluated in order. The
fingerprint functions are the stages' own (F1), so this never disagrees with a stage's skip
decision."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from manuallabor.cleanup.pipeline import clean_fingerprints, clean_provenance
from manuallabor.cleanup.types import AttachFile, CleanFile, DescribeFile
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.io import read_json, write_text_atomic
from manuallabor.figures.pipeline import figures_fingerprint
from manuallabor.figures.types import FigureReport
from manuallabor.grouping.pipeline import group_fingerprint
from manuallabor.ingest import sha256_file
from manuallabor.parse.pipeline import parse_is_current
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import score_fingerprint
from manuallabor.scoring.types import ScoreFile
from manuallabor.state.interfaces import JobRunnerP
from manuallabor.state.models import DocLearning, DocStatus, NodeState, ProjectStatus

if TYPE_CHECKING:
    from manuallabor.contracts.document import Document
    from manuallabor.state.store import Store

__all__ = [
    "DOC_NODES",
    "NODES",
    "Stages",
    "doc_node_states",
    "load_stages",
    "node_state",
    "project_node_states",
    "project_status",
    "save_stages",
    "upstream",
]

Node = Literal[
    "ingest", "parse", "figures", "score", "group", "clean", "score2", "assemble", "export"
]
NODES: Final[tuple[str, ...]] = (
    "ingest", "parse", "figures", "score", "group", "clean", "score2", "assemble", "export",
)  # fmt: skip
DOC_NODES: Final[tuple[str, ...]] = NODES[:7]


def upstream(node: str) -> tuple[str, ...]:
    i = DOC_NODES.index(node)
    return DOC_NODES[:i]


class NodeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int
    status: Literal["done", "failed"]
    fingerprint: str | None = None
    error: str | None = None


class Stages(BaseModel):
    """docs/<slug>/stages.json: no timestamps (byte-stable across runs)."""

    model_config = ConfigDict(extra="forbid")
    counter: int = 0
    nodes: dict[str, NodeRecord] = {}

    def record(
        self, node: str, status: Literal["done", "failed"], fp: str | None, error: str | None
    ) -> None:
        self.counter += 1
        self.nodes[node] = NodeRecord(seq=self.counter, status=status, fingerprint=fp, error=error)

    def seq(self, node: str) -> int:
        r = self.nodes.get(node)
        return 0 if r is None else r.seq


def load_stages(paths: ProjectPaths, slug: str) -> Stages:
    p = paths.doc(slug).stages
    if not p.is_file():
        return Stages()
    try:
        return read_json(p, Stages)
    except ValueError:
        return Stages()


def save_stages(paths: ProjectPaths, slug: str, st: Stages) -> None:
    write_text_atomic(
        paths.doc(slug).stages,
        json.dumps(st.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
    )


# -- output existence and recorded fingerprints ------------------------------------------------


def _exists(paths: ProjectPaths, slug: str, node: str) -> bool:
    dp = paths.doc(slug)
    if node == "ingest":
        return dp.document.is_file()
    if node == "parse":
        return dp.state.is_file() and dp.blocks.is_file()
    if node == "figures":
        return dp.figure_report.is_file()
    if node == "score":
        return dp.scores.is_file()
    if node == "group":
        return dp.groups.is_file()
    if node == "clean":
        return dp.clean.is_file() and dp.attach.is_file() and dp.describe.is_file()
    if node == "score2":
        return dp.clean.is_file() and dp.scores.is_file()
    return False


def _fingerprint_state(paths: ProjectPaths, slug: str, node: str, cfg: ProjectConfig) -> str | None:
    """None when the node's output matches its inputs, else the reason."""
    dp = paths.doc(slug)
    if node == "ingest":
        doc = paths.load_document(slug)
        src = paths.source(doc.filename)
        if not src.is_file():
            return "source file missing"
        return None if sha256_file(src) == doc.sha256 else "source file changed"
    if node == "parse":
        return None if parse_is_current(paths, slug, cfg) else "inputs changed"
    if node == "figures":
        rep = read_json(dp.figure_report, FigureReport)
        return None if rep.fingerprint == figures_fingerprint(paths, slug) else "inputs changed"
    if node in ("score", "score2"):
        sf = read_json(dp.scores, ScoreFile)
        if sf.threshold != cfg.threshold_for(slug):
            return "project threshold changed"
        if node == "score" and dp.clean.is_file():
            return None  # the file carries score2's fingerprint; score2 checks it
        return None if sf.fingerprint == score_fingerprint(paths, slug, cfg) else "inputs changed"
    if node == "group":
        from manuallabor.contracts.group import GroupsFile

        gf = read_json(dp.groups, GroupsFile)
        return None if gf.fingerprint == group_fingerprint(paths, slug, cfg) else "inputs changed"
    if node == "clean":
        fp_clean, fp_attach, fp_desc = clean_fingerprints(paths, slug, cfg)
        cf = read_json(dp.clean, CleanFile)
        af = read_json(dp.attach, AttachFile)
        df = read_json(dp.describe, DescribeFile)
        if (cf.fingerprint, af.fingerprint, df.fingerprint) != (fp_clean, fp_attach, fp_desc):
            return "inputs changed"
        snap, rr, re_ = clean_provenance(paths, cfg)
        if (cf.learning_snapshot, cf.rejected_rules, cf.rejected_examples) != (snap, rr, re_):
            return "learning layer changed"
        return None
    return None


def node_state(
    paths: ProjectPaths,
    slug: str,
    node: str,
    cfg: ProjectConfig,
    stages: Stages,
    memo: dict[str, NodeState] | None = None,
) -> NodeState:
    memo = {} if memo is None else memo
    if node in memo:
        return memo[node]
    rec = stages.nodes.get(node)
    out: NodeState
    if rec is not None and rec.status == "failed":
        out = NodeState(node=node, state="failed", reason=rec.error)
    elif not _exists(paths, slug, node):
        out = NodeState(node=node, state="missing")
    else:
        try:
            why = _fingerprint_state(paths, slug, node, cfg)
        except Exception as exc:  # unreadable/stale inputs: the stage will say why when it runs
            why = f"{type(exc).__name__}: {exc}"
        out = NodeState(node=node, state="fresh")
        if why is not None:
            out = NodeState(node=node, state="stale", reason=why)
        else:
            mine = stages.seq(node)
            for up in upstream(node):
                if stages.seq(up) > mine:
                    out = NodeState(node=node, state="stale", reason=f"upstream re-run: {up}")
                    break
            else:
                for up in upstream(node):
                    s = node_state(paths, slug, up, cfg, stages, memo)
                    if s.state != "fresh":
                        out = NodeState(
                            node=node, state="stale", reason=f"upstream {up} is {s.state}"
                        )
                        break
    memo[node] = out
    return out


# -- cached per-document states --------------------------------------------------------------

_CACHE: dict[tuple[str, str], tuple[tuple[Any, ...], list[NodeState]]] = {}
_CACHE_LOCK = threading.Lock()


def _stat(p: Path) -> Any:
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _signature(paths: ProjectPaths, slug: str) -> tuple[Any, ...]:
    dp = paths.doc(slug)
    files = [
        paths.config, paths.selection, paths.learned_cleanup, paths.learned_grouping,
        paths.learning_active, paths.figures_index, paths.figure_dir(slug),
        dp.document, dp.blocks, dp.state, dp.layout, dp.figures, dp.figure_report, dp.scores,
        dp.groups, dp.clean, dp.attach, dp.describe, dp.group_overrides, dp.attach_overrides,
        dp.figure_overrides, dp.stages,
    ]  # fmt: skip
    sig = [_stat(p) for p in files]
    try:
        sig.append(_stat(paths.source(paths.load_document(slug).filename)))
    except (OSError, ValueError):
        sig.append(None)
    return tuple(sig)


def doc_node_states(paths: ProjectPaths, slug: str, cfg: ProjectConfig) -> list[NodeState]:
    key = (str(paths.root), slug)
    sg = _signature(paths, slug)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == sg:
            return hit[1]
    stages = load_stages(paths, slug)
    memo: dict[str, NodeState] = {}
    states = [node_state(paths, slug, n, cfg, stages, memo) for n in DOC_NODES]
    with _CACHE_LOCK:
        _CACHE[key] = (sg, states)
    return states


def project_node_states(paths: ProjectPaths) -> list[NodeState]:
    """State of the project-level nodes `assemble` and `export` (module 11)."""
    from manuallabor.export.pipeline import node_states

    return node_states(paths)


# -- project status --------------------------------------------------------------------------


_STATUS_CACHE: dict[tuple[str, str, str], tuple[tuple[Any, ...], Any]] = {}


def _memo(paths: ProjectPaths, slug: str, kind: str, sg: tuple[Any, ...], make: Any) -> Any:
    """`project_status` parts cached on file stats (and the last action id where the DB is read),
    beside the node states: `/api/status` and `/api/sources` are fetched on every screen change
    (review F5)."""
    key = (str(paths.root), slug, kind)
    with _CACHE_LOCK:
        hit = _STATUS_CACHE.get(key)
        if hit is not None and hit[0] == sg:
            return hit[1]
    value = make()
    with _CACHE_LOCK:
        _STATUS_CACHE[key] = (sg, value)
    return value


def _orphans(paths: ProjectPaths, slug: str, store: Store | None) -> int:
    """Decisions of this document whose block raw text has changed since (re-parse)."""
    if store is None:
        return 0
    dp = paths.doc(slug)
    if not dp.blocks.is_file():
        return 0

    def count() -> int:
        from manuallabor.contracts.block import Block
        from manuallabor.contracts.io import read_json_list
        from manuallabor.state.store import sha_text

        raw = {b.id: sha_text(b.raw_text) for b in read_json_list(dp.blocks, Block)}
        return sum(
            1 for d in store.decisions(doc_id=slug) if raw.get(d.decision.block_id) != d.raw_sha256
        )

    if store.in_tx:
        return count()
    n: int = _memo(paths, slug, "orphans", (_stat(dp.blocks), store.max_action_id()), count)
    return n


def _status_store(paths: ProjectPaths, runner: JobRunnerP | None) -> tuple[Store | None, bool]:
    """The serving store (the runner's), else a read-only one this call opens and closes."""
    from manuallabor.state.store import Store

    own = getattr(runner, "store", None)
    if isinstance(own, Store):
        return own, False
    if not paths.db.is_file():
        return None, False
    try:
        return Store.open(paths, readonly=True), True
    except Exception:
        return None, False


def _learning(paths: ProjectPaths, slug: str) -> DocLearning:
    dp = paths.doc(slug)

    def read() -> DocLearning:
        group = clean = "baseline"
        try:
            if dp.groups.is_file():
                group = json.loads(dp.groups.read_text(encoding="utf-8")).get(
                    "learning_snapshot", group
                )
            if dp.clean.is_file():
                clean = json.loads(dp.clean.read_text(encoding="utf-8")).get(
                    "learning_snapshot", clean
                )
        except (OSError, ValueError):
            pass
        return DocLearning(group=str(group), clean=str(clean))

    out: DocLearning = _memo(paths, slug, "learning", (_stat(dp.groups), _stat(dp.clean)), read)
    return out.model_copy()


def project_status(paths: ProjectPaths, runner: JobRunnerP | None) -> ProjectStatus:
    cfg = paths.load_config() if paths.config.is_file() else ProjectConfig(name=paths.root.name)
    docs: list[DocStatus] = []
    names: set[str] = set()
    store, own = _status_store(paths, runner)
    try:
        for slug in paths.list_slugs():
            doc: Document = _memo(
                paths,
                slug,
                "document",
                (_stat(paths.doc(slug).document),),
                lambda slug=slug: paths.load_document(slug),
            )
            names.add(doc.filename)
            docs.append(
                DocStatus(
                    doc_id=slug,
                    kind=doc.kind,
                    pages=doc.page_count,
                    nodes=doc_node_states(paths, slug, cfg),
                    learning=_learning(paths, slug),
                    orphaned_decisions=_orphans(paths, slug, store),
                )
            )
    finally:
        if own and store is not None:
            store.close()
    unreg = (
        sorted(p.name for p in paths.sources.iterdir() if p.is_file() and p.name not in names)
        if paths.sources.is_dir()
        else []
    )
    running = runner.list({"running", "queued"}) if runner is not None else []
    return ProjectStatus(
        project=cfg.name, docs=docs, unregistered_sources=unreg, jobs_running=running
    )
