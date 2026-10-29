"""R5, R6 through the real `labor serve --mock` (skipped while the API layer is absent)."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from manuallabor.project import ProjectPaths
from tests.conftest import labor_copy
from tests.jobs.test_resume import assert_resumed_equals
from tests.jobs.test_runner import db_job, job_lines, wait_for

pytest.importorskip("manuallabor.serve")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def http(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:  # type: ignore[type-arg]
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def start_serve(root: Path, port: int) -> subprocess.Popen[bytes]:
    p = subprocess.Popen(
        [sys.executable, "-m", "manuallabor", "serve", str(root), "--mock", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    wait_for(lambda: _up(port) or p.poll() is not None, 60)
    assert p.poll() is None, "serve exited"
    return p


def _up(port: int) -> bool:
    try:
        return http("GET", f"http://127.0.0.1:{port}/api/status")[0] == 200
    except OSError:
        return False


@pytest.fixture
def proj(labor_template: Path, tmp_path: Path) -> ProjectPaths:
    return ProjectPaths(labor_copy(labor_template, tmp_path / "proj"))


def test_r5_serve_killed_alone_the_job_is_adopted(proj: ProjectPaths, labor_scored: Path) -> None:
    port = free_port()
    serve = start_serve(proj.root, port)
    try:
        code, job = http("POST", f"http://127.0.0.1:{port}/api/jobs", {"to": "score2"})
        assert code == 202, job
        jid = job["id"]
        wait_for(lambda: any(o.get("node") == "clean" for o in job_lines(proj, jid)), 120)
        pid = db_job(proj, 1)["pid"]
        os.kill(serve.pid, signal.SIGKILL)  # only the serve process
        serve.wait()
    finally:
        if serve.poll() is None:
            serve.kill()
    port = free_port()
    serve = start_serve(proj.root, port)
    try:
        wait_for(
            lambda: (
                http("GET", f"http://127.0.0.1:{port}/api/jobs/{jid}")[1]["status"] != "running"
            ),
            120,
        )
        got = http("GET", f"http://127.0.0.1:{port}/api/jobs/{jid}")[1]
        assert got["status"] == "done", got
        assert got["pid"] == pid
    finally:
        serve.send_signal(signal.SIGTERM)
        serve.wait(timeout=30)
    assert_resumed_equals(proj, ProjectPaths(labor_scored))


def test_r6_serve_and_worker_killed_the_job_resumes(proj: ProjectPaths, labor_scored: Path) -> None:
    port = free_port()
    serve = start_serve(proj.root, port)
    try:
        code, job = http("POST", f"http://127.0.0.1:{port}/api/jobs", {"to": "score2"})
        assert code == 202, job
        jid = job["id"]
        wait_for(lambda: any(o.get("node") == "score" for o in job_lines(proj, jid)), 120)
        worker_pgid = os.getpgid(db_job(proj, 1)["pid"])
        os.killpg(worker_pgid, signal.SIGKILL)
        os.kill(serve.pid, signal.SIGKILL)
        serve.wait()
    finally:
        if serve.poll() is None:
            serve.kill()
    time.sleep(0.5)
    port = free_port()
    serve = start_serve(proj.root, port)
    try:
        wait_for(
            lambda: (
                http("GET", f"http://127.0.0.1:{port}/api/jobs/job-000002")[1].get("status")
                in ("done", "failed")
            ),
            180,
        )
        new = http("GET", f"http://127.0.0.1:{port}/api/jobs/job-000002")[1]
        old = http("GET", f"http://127.0.0.1:{port}/api/jobs/{jid}")[1]
        assert old["status"] == "interrupted"
        assert new["status"] == "done" and new["resumed_from"] == jid, new
    finally:
        serve.send_signal(signal.SIGTERM)
        serve.wait(timeout=30)
    assert_resumed_equals(proj, ProjectPaths(labor_scored))
