"""E23 (`labor check` stages K10-K16 on project-a), the mock half of E25 (offline guard) and
E27 (live, skipped unless MANUALLABOR_LIVE=1)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.check.test_check import PROJECT_A, tree_hash

LABOR = [sys.executable, "-m", "manuallabor"]


def test_e23_and_e25_labor_check_runs_the_export_stages_offline(
    requires_docling: None, tmp_path: Path
) -> None:
    before_tree = tree_hash(PROJECT_A)
    log = tmp_path / "net.log"
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    env = {
        **os.environ,
        "MANUALLABOR_OFFLINE": "1",
        "MANUALLABOR_OFFLINE_LOG": str(log),
        "TMPDIR": str(tmp_root),  # labor check's temporary copy lands here
    }
    r = subprocess.run(
        [*LABOR, "check", str(PROJECT_A)], capture_output=True, text=True, timeout=900, env=env
    )
    assert r.returncode == 0, r.stdout + r.stderr[-2000:]
    rows = {ln.split("  ")[0].strip(): ln for ln in r.stdout.splitlines() if ln[:1] == "K"}
    for k in ("K10", "K11", "K12", "K13", "K14", "K15", "K16"):
        line = next(v for key, v in rows.items() if key.startswith(k))
        assert " PASS " in line, line
    assert "refused" in next(v for key, v in rows.items() if key.startswith("K10"))
    assert "faith_violations(auto)" in r.stdout and "| 0 |" in r.stdout
    assert tree_hash(PROJECT_A) == before_tree
    assert not list(tmp_root.glob("labor-check-*"))  # the temporary copy was removed
    assert not (PROJECT_A / "export").exists()
    assert not log.exists() or log.read_text() == ""  # E25: no network attempt at all


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def test_e25_the_guard_blocks_logs_and_allows_the_local_server(tmp_path: Path) -> None:
    stub = socket.socket()
    stub.bind(("127.0.0.1", 0))
    stub.listen(4)
    port = stub.getsockname()[1]
    log = tmp_path / "violations.log"
    code = textwrap.dedent(
        """
        import os, socket, sys
        from manuallabor.providers.offline import install_from_env
        assert install_from_env() is True
        ok = socket.create_connection(("127.0.0.1", int(os.environ["STUB_PORT"])), timeout=2)
        ok.close()
        a, b = socket.socketpair()  # AF_UNIX: always allowed
        a.close(); b.close()
        try:
            socket.create_connection(("1.1.1.1", 443), timeout=1)
        except OSError as exc:
            print("blocked:", exc)
        else:
            sys.exit("the guard let 1.1.1.1:443 through")
        try:
            socket.getaddrinfo("example.com", 443)
        except OSError:
            pass
        s = socket.socket()
        try:
            s.connect(("8.8.8.8", 53))
        except OSError:
            pass
        print("done")
        """
    )
    env = {
        **os.environ,
        "MANUALLABOR_OFFLINE": "1",
        "MANUALLABOR_OFFLINE_LOG": str(log),
        "OLLAMA_HOST": f"127.0.0.1:{port}",
        "STUB_PORT": str(port),
    }
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    stub.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "blocked:" in r.stdout and "done" in r.stdout
    seen = log.read_text().splitlines()
    assert "1.1.1.1:443" in seen and "8.8.8.8:53" in seen and "example.com:443" in seen
    assert not any(str(port) in ln for ln in seen)  # the local server is never a violation


def test_e25_without_the_variable_nothing_is_patched() -> None:
    env = {k: v for k, v in os.environ.items() if k != "MANUALLABOR_OFFLINE"}
    code = (
        "import socket;from manuallabor.providers.offline import install_from_env;"
        "orig=socket.socket.connect;print(install_from_env(), socket.socket.connect is orig)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.stdout.strip() == "False True", r.stdout + r.stderr


@pytest.mark.live
def test_e27_live_check_with_local_models_makes_no_network_calls(tmp_path: Path) -> None:
    if os.environ.get("MANUALLABOR_LIVE") != "1":
        pytest.skip("live: set MANUALLABOR_LIVE=1 (needs Ollama with the small-tier models)")
    log = tmp_path / "net.log"
    env = {**os.environ, "MANUALLABOR_OFFLINE": "1", "MANUALLABOR_OFFLINE_LOG": str(log)}
    r = subprocess.run(
        [*LABOR, "check", "--live", str(PROJECT_A)],
        capture_output=True,
        text=True,
        timeout=3000,
        env=env,
    )
    if "SKIP live" in r.stdout:
        pytest.skip(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr[-2000:]
    assert not log.exists() or log.read_text() == ""
