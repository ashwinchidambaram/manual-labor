"""A12 OpenAPI stability, A13 static serving, V1 serve subprocess."""

# ruff: noqa: E501

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from manuallabor.api.openapi import DEFAULT_OUT, export_openapi, openapi_text
from tests.api.conftest import Env

pytestmark = pytest.mark.anyio

REPO = Path(__file__).resolve().parents[2]


def test_a12_openapi_byte_stable_and_committed(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert export_openapi(a) and export_openapi(b)
    assert a.read_bytes() == b.read_bytes() == openapi_text().encode()
    assert export_openapi(a, check=True)
    a.write_text("{}")
    assert export_openapi(a, check=True) is False
    # the committed document matches the app
    assert export_openapi(DEFAULT_OUT, check=True), (
        "run: uv run python -m manuallabor.api.export_openapi"
    )


def test_a12_operation_ids_and_schema_names() -> None:
    spec = json.loads(openapi_text())
    ops = [(m, p, o["operationId"]) for p, v in spec["paths"].items() for m, o in v.items()]
    names = [o for _, _, o in ops]
    assert len(names) == len(set(names))
    assert not [k for k in spec["components"]["schemas"] if re.search(r"-(Input|Output)$", k)]
    assert all(re.fullmatch(r"[a-z_0-9]+", n) for n in names)


def test_a12_export_script_runs_in_subprocess(tmp_path: Path) -> None:
    out = tmp_path / "o.json"
    for _ in range(2):
        subprocess.run(
            [sys.executable, "-m", "manuallabor.api.export_openapi", "--out", str(out)],
            check=True,
            cwd=REPO,
            capture_output=True,
        )
    assert out.read_text() == openapi_text()


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html>INDEX</html>")
    (d / "assets" / "x.js").write_text("console.log(1)")
    return d


async def test_a13_static(env: Env, dist: Path) -> None:
    async with env.client(static_dir=dist) as c:
        for url in ("/", "/verify", "/scope/deep/link"):
            r = await c.get(url)
            assert r.status_code == 200 and "INDEX" in r.text, url
        js = await c.get("/assets/x.js")
        assert js.status_code == 200 and "console.log" in js.text
        assert (await c.get("/assets/missing.js")).status_code == 404
        nope = await c.get("/api/nope")
        assert nope.status_code == 404 and nope.json()["code"] == "not_found"
        assert (await c.get("/api/project")).status_code == 200
        assert (await c.get("/../../etc/passwd")).status_code in (200, 404)
        assert "root:" not in (await c.get("/%2e%2e/%2e%2e/etc/passwd")).text


async def test_a13_dev_and_missing_dist(env: Env, dist: Path) -> None:
    async with env.client(static_dir=dist, dev=True) as c:
        assert (await c.get("/")).status_code == 404
        assert (await c.get("/api/project")).status_code == 200
    async with env.client(static_dir=None) as c:
        r = await c.get("/")
        assert r.status_code == 200 and "frontend not built" in r.text
        assert (await c.get("/verify")).status_code == 404
        assert (await c.get("/api/nope")).json()["code"] == "not_found"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait(url: str, timeout: float) -> httpx.Response | None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            return httpx.get(url, timeout=1.0)
        except httpx.HTTPError:
            time.sleep(0.1)
    return None


def test_v1_serve_subprocess(tmp_path: Path) -> None:
    """`labor serve --dev --mock` answers /api/project quickly; a second serve exits 3;
    SIGTERM releases the lock. Needs module 7's real state layer (A)."""
    from tests.api.conftest import build_project

    paths = build_project(tmp_path / "proj")
    port = _free_port()
    labor = str(Path(sys.executable).parent / "labor")
    cmd = [labor, "serve", str(paths.root), "--port", str(port), "--dev", "--mock"]
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        t0 = time.monotonic()
        r = _wait(f"http://127.0.0.1:{port}/api/project", 10.0)
        assert r is not None and r.status_code == 200, (
            proc.stderr.read() if proc.poll() else "no answer"
        )
        started_in = time.monotonic() - t0
        assert r.json()["mock"] is True
        t = time.monotonic()
        httpx.get(f"http://127.0.0.1:{port}/api/project", timeout=2.0)
        assert time.monotonic() - t < 2.0 and started_in < 10.0
        second = subprocess.run(
            [labor, "serve", str(paths.root), "--port", str(_free_port()), "--dev", "--mock"],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert second.returncode == 3, second.stderr
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
    assert proc.returncode == 0
    wal = paths.db.with_name("project.db-wal")
    assert not wal.exists() or wal.stat().st_size == 0
