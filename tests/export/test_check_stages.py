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


# -- K16 parses Markdown links instead of matching a regex (review fix) -------------------------


def _k16_zip(tmp: Path, body: str, files: tuple[str, ...]) -> Path:
    import zipfile

    zp = tmp / "k16.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("articles/a.md", "---\nid: a\n---\n\n# A\n\n" + body + "\n")
        for n in files:
            zf.writestr(n, b"x")
    return zp


def _k16(zp: Path) -> str | None:
    from types import SimpleNamespace

    from manuallabor.check import k16_figure_refs

    return k16_figure_refs(SimpleNamespace(export={"zip": zp}))  # type: ignore[arg-type]


def test_k16_a_caption_with_a_link_inside_resolves_to_the_real_target(tmp_path: Path) -> None:
    from manuallabor.export.render import alt_text, figure_line

    fid = "FIG-a-p001-01"
    alt = alt_text(fid, "see [1](images/other.png) and (rev 2)", None)
    body = figure_line(alt, f"images/a/{fid}.png")
    zp = _k16_zip(tmp_path, body, (f"images/a/{fid}.png", f"images/a/{fid}.json"))
    assert _k16(zp) == "1 figure references resolve to a file and a sidecar"


def test_k16_catches_a_mid_line_reference_and_a_missing_sidecar(tmp_path: Path) -> None:
    fid = "FIG-a-p001-02"
    body = f"Text then ![{fid} — c](images/a/{fid}.png) inline."
    with pytest.raises(AssertionError, match="not in the zip"):
        _k16(_k16_zip(tmp_path, body, ()))
    with pytest.raises(AssertionError, match="no sidecar"):
        _k16(_k16_zip(tmp_path, body, (f"images/a/{fid}.png",)))
    assert _k16(_k16_zip(tmp_path, body, (f"images/a/{fid}.png", f"images/a/{fid}.json")))


# -- the offline guard covers more entry points and spawned workers (review fix) ----------------


def _guarded(code: str, log: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "MANUALLABOR_OFFLINE": "1",
        "MANUALLABOR_OFFLINE_LOG": str(log),
        "OLLAMA_HOST": "127.0.0.1:9",
        **extra,
    }
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def test_the_guard_blocks_udp_sendto_and_the_raw_socket_type(tmp_path: Path) -> None:
    log = tmp_path / "v.log"
    r = _guarded(
        """
        import socket, _socket, sys
        from manuallabor.providers.offline import install_from_env
        assert install_from_env() is True
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            u.sendto(b"x", ("1.1.1.1", 53))
        except OSError as exc:
            print("sendto blocked:", exc)
        else:
            sys.exit("sendto to 1.1.1.1:53 went through")
        raw = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        try:
            raw.connect(("9.9.9.9", 443))
        except OSError as exc:
            print("raw connect blocked:", exc)
        else:
            sys.exit("_socket.socket.connect went through")
        """,
        log,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "sendto blocked: offline guard" in r.stdout
    assert "raw connect blocked: offline guard" in r.stdout
    seen = log.read_text().splitlines()
    assert "1.1.1.1:53" in seen and "9.9.9.9:443" in seen


def test_the_guard_is_installed_in_the_spawned_ocr_workers(tmp_path: Path) -> None:
    log = tmp_path / "v.log"
    r = _guarded(
        """
        from manuallabor.parse.render import OcrPool
        from manuallabor.providers.offline import guard_installed, install_from_env
        if __name__ == "__main__":
            assert install_from_env() is True
            pool = OcrPool(workers=1)
            try:
                print("child guard:", pool.executor().submit(guard_installed).result(timeout=60))
            finally:
                pool.close()
        """,
        log,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "child guard: True" in r.stdout


def test_the_ac8_negative_control_is_blocked_and_logged(tmp_path: Path) -> None:
    from tests.check.test_check import PROJECT_A

    script = PROJECT_A.parents[2] / "scripts" / "offline_control.py"
    log = tmp_path / "control.log"
    env = {**os.environ, "MANUALLABOR_OFFLINE": "1", "MANUALLABOR_OFFLINE_LOG": str(log)}
    r = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, env=env, timeout=60
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "negative control: 1.1.1.1:443 blocked and logged" in r.stdout
    assert "1.1.1.1:443" in log.read_text().splitlines()
    # without the guard the control fails (and never tries the network)
    env.pop("MANUALLABOR_OFFLINE")
    r = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, env=env, timeout=60
    )
    assert r.returncode == 1 and "not installed" in r.stdout + r.stderr
