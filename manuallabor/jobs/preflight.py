"""Fail fast when a model service is unreachable (design 07 section 20).

Before a job runs a unit, every Ollama host the plan's model tasks would call is asked
`GET <host>/api/tags` once. An unreachable host ends the job with one plain sentence before any
stage runs, and records it on the first node of each document that needs it, so the Scope card
says why. Only the host the provider itself would call is contacted; other providers are never
checked (a remote API would be one more network call, invariant 6) and mock mode checks nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.enums import Task
from manuallabor.jobs import graph
from manuallabor.project import ProjectPaths

__all__ = [
    "CODE",
    "Unreachable",
    "check",
    "check_agent",
    "message",
    "plan_tasks",
    "reacher",
    "record_unreachable",
]

CODE = "provider_unreachable"
TIMEOUT = 2.0
Get = Callable[[str, float], bool]
Units = Sequence[tuple[str, str]]


@dataclass(frozen=True)
class Unreachable:
    host: str
    tasks: tuple[str, ...]  # the plan's tasks that call this host, in Task order
    message: str


def message(host: str) -> str:
    return f"Ollama is not running at {host}. Start it (`ollama serve`) and press Retry."


def http_get(url: str, timeout: float) -> bool:
    """True when the server answered 2xx. Any error (refused, timeout, offline guard) is False."""
    try:
        import httpx

        # never through a proxy from the environment: only the configured host is asked
        return httpx.get(url, timeout=timeout, trust_env=False).is_success
    except Exception:
        return False


def _node_tasks(paths: ProjectPaths, cfg: ProjectConfig, node: str, slug: str) -> list[Task]:
    if node == "group":
        return [Task.embeddings, Task.grouping]
    if node == "clean":
        out = [] if cfg.cleanup.llm == "off" else [Task.cleanup]
        return [*out, Task.vision] if cfg.cleanup.describe else out
    if node == "score2":
        return [Task.verifier]
    if node == "score":
        # a first-pass score has no cleaned text, so the verifier is never asked (design 03)
        return [Task.verifier] if paths.doc(slug).clean.is_file() else []
    return []  # ingest, parse, figures, assemble, export call no model


def plan_tasks(
    paths: ProjectPaths, cfg: ProjectConfig, units: Units
) -> dict[Task, list[tuple[str, str]]]:
    """Each model task the units would call, with the units that call it (in plan order)."""
    out: dict[Task, list[tuple[str, str]]] = {}
    for node, slug in units:
        for t in _node_tasks(paths, cfg, node, slug):
            if cfg.model_for(t) is not None:
                out.setdefault(t, []).append((node, slug))
    return out


def _hosts(cfg: ProjectConfig, tasks: Iterable[Task]) -> dict[str, list[Task]]:
    from manuallabor.providers.base import ProviderError
    from manuallabor.providers.registry import resolve_endpoint

    hosts: dict[str, list[Task]] = {}
    for t in sorted(set(tasks), key=lambda x: list(Task).index(x)):
        ref = cfg.model_for(t)
        if ref is None or ref.provider != "ollama":
            continue
        try:
            base = resolve_endpoint(ref).api_base
        except ProviderError:
            continue  # a broken reference fails at the call with its own message
        if base:
            hosts.setdefault(base, []).append(t)
    return hosts


def check(cfg: ProjectConfig, tasks: Iterable[Task], *, get: Get = http_get) -> Unreachable | None:
    """The first Ollama host (in task order) that does not answer, or None."""
    for host, ts in _hosts(cfg, tasks).items():
        if not get(f"{host}/api/tags", TIMEOUT):
            return Unreachable(host, tuple(t.value for t in ts), message(host))
    return None


def check_agent(cfg: ProjectConfig, *, get: Get = http_get) -> Unreachable | None:
    return check(cfg, [Task.agent], get=get)


def reacher(
    paths: ProjectPaths, cfg: ProjectConfig, mode: str, *, get: Get = http_get
) -> Callable[[Units], Unreachable | None] | None:
    """The executor's `reach`: checks the hosts the given units need. None in mock mode."""
    if mode == "mock":
        return None

    def reach(units: Units) -> Unreachable | None:
        return check(cfg, plan_tasks(paths, cfg, units), get=get)

    return reach


def record_unreachable(
    paths: ProjectPaths, cfg: ProjectConfig, units: Units, u: Unreachable
) -> list[str]:
    """For each document of `units`, mark the first of its units that calls the unreachable host
    `failed` with the sentence and `code` (the Scope card's reason; section 19 rule 3 re-runs it).
    The caller holds the worker lock. Returns the documents marked."""
    needed = {Task(t) for t in u.tasks}
    first: dict[str, str] = {}
    for node, slug in units:
        if slug and slug not in first and needed & set(_node_tasks(paths, cfg, node, slug)):
            first[slug] = node
    for slug, node in sorted(first.items()):
        st = graph.load_stages(paths, slug)
        st.record(node, "failed", None, u.message, code=CODE)
        graph.save_stages(paths, slug, st)
    return sorted(first)
