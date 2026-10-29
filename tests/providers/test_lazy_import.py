"""T3: importing the provider layer / CLI never imports litellm (or httpx)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=120
    )


def test_import_providers_and_cli_is_lazy() -> None:
    r = run(
        "import manuallabor.providers, manuallabor.cli, sys; "
        "assert 'litellm' not in sys.modules, 'litellm imported'; "
        "assert 'httpx' not in sys.modules, 'httpx imported'; print('ok')"
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"


def test_mock_only_flow_leaves_litellm_out() -> None:
    r = run(
        "import sys, tempfile, pathlib\n"
        "from manuallabor.contracts import ProjectConfig, TaskModels, ModelRef, Task, Message\n"
        "from manuallabor.providers import build_provider_set, ListSink\n"
        "ref = ModelRef(provider='mock', model='mock-1')\n"
        "cfg = ProjectConfig(name='x', models=TaskModels(cleanup=ref, grouping=ref, vision=ref,"
        " embeddings=ref, verifier=ref))\n"
        "cache = pathlib.Path(tempfile.mkdtemp())\n"
        "ps = build_provider_set(cfg, cache_dir=cache, sink=ListSink())\n"
        "ps.get(Task.cleanup).chat(Task.cleanup, [Message(role='user', content='hi')])\n"
        "assert 'litellm' not in sys.modules\n"
        "print('ok')"
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"


def test_labor_help_runs_without_litellm() -> None:
    r = run(
        "import sys\n"
        "from typer.testing import CliRunner\n"
        "from manuallabor.cli import app\n"
        "res = CliRunner().invoke(app, ['--help'])\n"
        "assert res.exit_code == 0, res.output\n"
        "assert 'litellm' not in sys.modules\n"
        "print('ok')"
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"
