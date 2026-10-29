from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from manuallabor.api.app import create_app
from manuallabor.api.deps import Hooks
from manuallabor.contracts.enums import DocKind
from manuallabor.contracts.io import write_json
from manuallabor.project import ProjectPaths
from manuallabor.state.interfaces import AppServices
from manuallabor.state.models import DocStatus, NodeState, ProjectStatus
from tests.api.fakes import FakeState, bid, make_services
from tests.providers.probe_support import mac_probe

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def build_project(root: Path) -> ProjectPaths:
    from manuallabor.contracts.document import Document

    root.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "project-a" / "project.json", root / "project.json")
    paths = ProjectPaths(root)
    (root / "sources").mkdir()
    (root / "sources" / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
    doc = Document(
        slug="doc",
        sha256="a" * 64,
        filename="doc.pdf",
        kind=DocKind.born_digital_pdf,
        page_count=1,
        block_ids=[bid(1)],
        pages_without_text_layer=[1],
    )
    paths.doc("doc").root.mkdir(parents=True)
    write_json(paths.doc("doc").document, doc)
    return paths


def fake_status(paths: ProjectPaths, runner: object) -> ProjectStatus:
    doc = paths.load_document("doc")
    return ProjectStatus(
        project=paths.load_config().name,
        docs=[
            DocStatus(
                doc_id="doc",
                kind=doc.kind,
                pages=1,
                nodes=[
                    NodeState(node="parse", state="fresh"),
                    NodeState(node="clean", state="stale", reason="inputs changed"),
                ],
            )
        ],
    )


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.paths = build_project(tmp_path / "proj")
        self.st = FakeState(tmp_path)
        self.services: AppServices = make_services(self.paths, self.st)
        self.hooks = Hooks(status=fake_status, probe=lambda p: mac_probe())

    def app(self, **kw: object):  # type: ignore[no-untyped-def]
        return create_app(self.services, hooks=self.hooks, **kw)  # type: ignore[arg-type]

    def client(self, **kw: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app(**kw)), base_url="http://t"
        )


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
async def api(env: Env) -> AsyncIterator[httpx.AsyncClient]:
    async with env.client() as c:
        yield c


ClientFactory = Callable[..., httpx.AsyncClient]
