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
    def score_history(self) -> Path:
        return self.root / "score_history.jsonl"

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
    def figures_index(self) -> Path:
        return self.figures_root / "index.json"

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
