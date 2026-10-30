"""Project directory layout. All on-disk paths are produced here and nowhere else."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.document import Document
from manuallabor.contracts.io import read_json, write_json


@dataclass(frozen=True)
class DocPaths:
    root: Path

    @property
    def document(self) -> Path:
        return self.root / "document.json"

    @property
    def blocks(self) -> Path:
        return self.root / "blocks.json"

    @property
    def parse_dir(self) -> Path:
        return self.root / "parse"

    @property
    def partial_dir(self) -> Path:
        return self.parse_dir / ".partial"

    @property
    def pages_dir(self) -> Path:
        return self.root / "pages"

    def parser_output(self, role: str) -> Path:
        return self.parse_dir / f"{role}.json"

    @property
    def layout(self) -> Path:
        return self.parse_dir / "layout.json"

    @property
    def merge(self) -> Path:
        return self.parse_dir / "merge.json"

    @property
    def figures(self) -> Path:
        return self.parse_dir / "figures.json"

    @property
    def figure_report(self) -> Path:
        return self.root / "figures_report.json"

    @property
    def state(self) -> Path:
        return self.parse_dir / "state.json"

    @property
    def scores(self) -> Path:
        return self.root / "scores.json"

    @property
    def groups(self) -> Path:
        return self.root / "groups.json"

    @property
    def group_overrides(self) -> Path:
        return self.root / "group_overrides.json"

    @property
    def clean(self) -> Path:
        return self.root / "clean.json"

    @property
    def attach(self) -> Path:
        return self.root / "attach.json"

    @property
    def describe(self) -> Path:
        return self.root / "describe.json"

    @property
    def attach_overrides(self) -> Path:
        return self.root / "attach_overrides.json"

    @property
    def score_history(self) -> Path:
        return self.root / "score_history.jsonl"

    @property
    def stages(self) -> Path:
        """Executor bookkeeping (module 7): per-node seq/status; no timestamps."""
        return self.root / "stages.json"

    @property
    def figure_overrides(self) -> Path:
        """Projection of the human crop-bbox overrides (module 7); read by the figures stage."""
        return self.root / "figure_overrides.json"

    def page_view(self, page: int, dpi: int) -> Path:
        return self.root / "pages_view" / f"p{page:03d}-{dpi}.png"

    def page_png(self, page: int) -> Path:
        return self.pages_dir / f"p{page:03d}.png"

    def partial(self, role: str, page: int) -> Path:
        return self.partial_dir / f"{role}-p{page:03d}.json"


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    def __post_init__(self) -> None:
        # Resolve symlinks: Leptonica (Tesseract) rewrites paths that start with "/tmp/" on macOS,
        # so "/tmp/proj/x.png" cannot be opened while "/private/tmp/proj/x.png" can.
        object.__setattr__(self, "root", Path(self.root).resolve())

    @property
    def config(self) -> Path:
        return self.root / "project.json"

    @property
    def sources(self) -> Path:
        return self.root / "sources"

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @property
    def figures_root(self) -> Path:
        return self.root / "figures"

    def figure_dir(self, slug: str) -> Path:
        return self.figures_root / slug

    def figure_file(self, slug: str, fid: str, ext: str) -> Path:
        return self.figure_dir(slug) / f"{fid}.{ext}"

    @property
    def selection(self) -> Path:
        return self.root / "selection.json"

    @property
    def db(self) -> Path:
        return self.root / "project.db"

    @property
    def lock(self) -> Path:
        return self.root / ".labor.lock"

    @property
    def worker_lock(self) -> Path:
        return self.root / ".labor.worker.lock"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def job_log(self, job_id: str) -> Path:
        return self.logs / "jobs" / f"{job_id}.jsonl"

    def job_plan(self, job_id: str) -> Path:
        return self.logs / "jobs" / f"{job_id}.plan.json"

    @property
    def uploads(self) -> Path:
        return self.root / ".uploads"

    @property
    def llm_log(self) -> Path:
        return self.root / "llm_calls.jsonl"

    @property
    def llm_cache(self) -> Path:
        """Cached model responses, one `<sha256>.json` per call (providers/cache.py)."""
        return self.root / ".llm_cache"

    @property
    def probe(self) -> Path:
        """The last `labor probe` / `POST /api/probe` result."""
        return self.root / "probe.json"

    @property
    def learning(self) -> Path:
        return self.root / "learning"

    @property
    def learning_active(self) -> Path:
        return self.learning / "active.json"

    def snapshot_dir(self, snapshot_id: str) -> Path:
        return self.learning / "snapshots" / snapshot_id

    @property
    def learned_calibration(self) -> Path:
        return self.learning / "calibration.json"

    @property
    def learned_grouping(self) -> Path:
        """Materialized active learning snapshot (module 7): grouping layer, if one is active."""
        return self.learning / "grouping.json"

    @property
    def learned_cleanup(self) -> Path:
        """Materialized active learning snapshot (module 7): cleanup layer, if one is active."""
        return self.learning / "cleanup.json"

    @property
    def learned_agent(self) -> Path:
        """Materialized active learning snapshot (module 10): agent examples."""
        return self.learning / "agent.json"

    @property
    def agent(self) -> Path:
        return self.root / "agent"

    @property
    def agent_proposals(self) -> Path:
        """Projection of the proposals table (module 10); the DB is the truth."""
        return self.agent / "proposals.json"

    @property
    def agent_outcomes(self) -> Path:
        """Latest non-proposal outcome per flag (machine output, file only; module 10)."""
        return self.agent / "outcomes.json"

    @property
    def figures_index(self) -> Path:
        return self.figures_root / "index.json"

    @property
    def export_dir(self) -> Path:
        return self.root / "export"

    @property
    def assembled(self) -> Path:
        """Staging tree: the zip's exact layout (module 11)."""
        return self.export_dir / "assembled"

    @property
    def export_state(self) -> Path:
        return self.export_dir / "state.json"

    @property
    def zip_path(self) -> Path:
        from manuallabor import ids

        return self.export_dir / f"{ids.slugify(self.load_config().name)}-kb.zip"

    def source(self, filename: str) -> Path:
        return self.sources / filename

    def doc(self, slug: str) -> DocPaths:
        return DocPaths(self.docs / slug)

    def list_slugs(self) -> list[str]:
        if not self.docs.is_dir():
            return []
        return sorted(p.name for p in self.docs.iterdir() if (p / "document.json").is_file())

    def load_config(self) -> ProjectConfig:
        return read_json(self.config, ProjectConfig)

    def ensure_config(self) -> ProjectConfig:
        """Load project.json, creating a default one named after the directory if missing."""
        if self.config.is_file():
            return self.load_config()
        cfg = ProjectConfig(name=self.root.resolve().name)
        write_json(self.config, cfg)
        return cfg

    def load_document(self, slug: str) -> Document:
        return read_json(self.doc(slug).document, Document)

    def list_documents(self) -> list[Document]:
        return [self.load_document(s) for s in self.list_slugs()]
