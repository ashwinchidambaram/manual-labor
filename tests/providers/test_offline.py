"""T4 (offline guard, subprocess + loopback stub + negative control) and T5 (static scan)."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


class Stub(BaseHTTPRequestHandler):
    seen: list[str] = []

    def log_message(self, *a: Any) -> None:
        pass

    def _send(self, obj: Any, status: int = 200) -> None:
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        Stub.seen.append(f"GET {self.path}")
        if self.path == "/api/tags":
            self._send({"models": [{"name": "llama3.2:1b", "digest": "abcdef123456" * 5}]})
        else:
            self._send({"error": "nope"}, 404)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        Stub.seen.append(f"POST {self.path}")
        if self.path == "/api/show":
            self._send({"model_info": {}, "capabilities": ["completion"]})
        elif self.path == "/api/chat":
            content = '{"n": 7}' if "format" in body else "ok"
            chars = sum(len(str(m.get("content", ""))) for m in body.get("messages", []))
            self._send(
                {
                    "model": "x",
                    "created_at": "2026-01-01T00:00:00Z",
                    "message": {"role": "assistant", "content": content},
                    "done": True,
                    "prompt_eval_count": max(5, chars // 3),  # a realistic count
                    "eval_count": 2,
                }
            )
        elif self.path == "/api/embed":
            self._send(
                {"model": "x", "embeddings": [[0.1, 0.2], [0.3, 0.4]], "prompt_eval_count": 2}
            )
        else:
            self._send({"error": "nope"}, 404)


def run_child(*args: str) -> tuple[dict[str, Any], list[str]]:
    Stub.seen = []
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        env = {
            **{k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")},
            "OLLAMA_HOST": f"127.0.0.1:{port}",
            "MANUALLABOR_STUB_PORT": str(port),
        }
        r = subprocess.run(
            # -I: isolated mode (no PYTHON* env vars, no user site, no cwd on sys.path), so
            # nothing but the installed package can leak into the guarded process
            [sys.executable, "-I", str(ROOT / "tests" / "providers" / "offline_child.py"), *args],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
            timeout=180,
        )
    finally:
        srv.shutdown()
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1]), list(Stub.seen)


def test_t4_only_ollama_host_is_contacted() -> None:
    out, seen = run_child()
    assert out["violations"] == [], out
    assert out["calls"] == 6
    assert out["probe_ok"] is True, out  # `labor probe` ran under the same guard
    assert seen, "the stub saw no request"
    assert {s.split(" ", 1)[1] for s in seen} <= {
        "/api/tags",
        "/api/show",
        "/api/chat",
        "/api/embed",
        "/api/version",  # `ollama --version` (run by `labor probe`) asks the server at OLLAMA_HOST
    }
    # cache hit + mock make no request: 3 chat-ish calls + 1 embed = 4 inference requests
    assert sum(1 for s in seen if s in ("POST /api/chat",)) == 3
    assert sum(1 for s in seen if s == "POST /api/embed") == 1


def test_t4_negative_control_guard_bites() -> None:
    out, _ = run_child("--negative")
    assert any("anthropic" in v for v in out["violations"]), out


NETWORK_MODULES = {"httpx", "requests", "urllib.request", "aiohttp", "socket"}


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            if node.module == "urllib":
                found |= {f"urllib.{a.name}" for a in node.names}
    return found


def test_t5_network_imports_are_confined() -> None:
    offenders = []
    for path in sorted((ROOT / "manuallabor").rglob("*.py")):
        rel = path.relative_to(ROOT / "manuallabor")
        if rel.parts[0] == "providers" or rel.parts[0].startswith("server"):
            continue
        bad = {
            m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m in NETWORK_MODULES
        }
        if bad:
            offenders.append(f"{rel}: {sorted(bad)}")
    assert not offenders, "network imports outside providers/: " + "; ".join(offenders)
