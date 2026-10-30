"""Request guard, upload cap, bind warning and explicit not-found (design 07 section 15; code
review F3, F13)."""

from __future__ import annotations

import http.client
import io
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from typer.testing import CliRunner

from manuallabor.api.app import create_app
from manuallabor.api.errors import ApiError
from manuallabor.api.guard import (
    DEFAULT_MAX_BODY_BYTES,
    RequestGuard,
    allowed_hosts_for,
    bind_warning,
)
from manuallabor.api.routers.sources import _save_upload
from manuallabor.state.errors import NotFound
from tests.api.conftest import Env

pytestmark = pytest.mark.anyio

LOOP = allowed_hosts_for("127.0.0.1")
PDF = [("files", ("manual.pdf", b"%PDF-1.4 tiny", "application/pdf"))]


def _client(env: Env, base: str = "http://127.0.0.1:8765", **kw: Any) -> httpx.AsyncClient:
    kw.setdefault("allowed_hosts", LOOP)
    raise_app = kw.pop("raise_app_exceptions", True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app(**kw), raise_app_exceptions=raise_app),
        base_url=base,
    )


@pytest.fixture
async def g(env: Env) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(env) as c:
        yield c


def _nothing_uploaded(env: Env) -> None:
    assert [k for k, _, _ in env.st.enqueued if k == "ingest_run"] == []
    up = env.paths.uploads
    assert not up.exists() or list(up.rglob("*")) == [], list(up.rglob("*"))


# ------------------------------------------------------------------------------- Host


@pytest.mark.parametrize(
    "host", ["127.0.0.1:8765", "localhost:5173", "LOCALHOST", "[::1]:8765", "127.0.0.1"]
)
async def test_loopback_host_names_pass(g: httpx.AsyncClient, host: str) -> None:
    r = await g.get("/api/project", headers={"host": host})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize(
    "host", ["attacker.example", "attacker.example:8765", "127.0.0.1.nip.io:8765", "10.0.0.9"]
)
async def test_foreign_host_is_421(g: httpx.AsyncClient, host: str) -> None:
    r = await g.get("/api/docs/doc/source", headers={"host": host})
    assert r.status_code == 421
    assert r.json()["code"] == "bad_host" and host.split(":")[0] in r.json()["detail"]


async def test_foreign_host_cannot_reach_static_or_unknown_routes(g: httpx.AsyncClient) -> None:
    for path in ("/", "/api/nope", "/api/export/download", "/api/decisions/export"):
        assert (await g.get(path, headers={"host": "evil.test"})).status_code == 421


async def test_missing_host_is_421() -> None:
    sent: list[dict[str, Any]] = []
    called = False

    async def app(scope: Any, receive: Any, send: Any) -> None:
        nonlocal called
        called = True

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    guard = RequestGuard(app, allowed_hosts=LOOP)
    scope = {"type": "http", "method": "GET", "path": "/api/project", "headers": []}
    await guard(scope, receive, send)
    assert not called and sent[0]["status"] == 421


async def test_non_loopback_bind_accepts_exactly_that_host(env: Env) -> None:
    async with _client(env, allowed_hosts=allowed_hosts_for("192.168.1.5")) as c:
        assert (
            await c.get("/api/project", headers={"host": "192.168.1.5:8765"})
        ).status_code == 200
        assert (await c.get("/api/project", headers={"host": "localhost:8765"})).status_code == 200
        assert (
            await c.get("/api/project", headers={"host": "192.168.1.6:8765"})
        ).status_code == 421
        assert (await c.get("/api/project", headers={"host": "mybox.local"})).status_code == 421


async def test_wildcard_bind_accepts_ip_literals_and_listed_names_only(env: Env) -> None:
    hosts = allowed_hosts_for("0.0.0.0", ["MyBox.local"])
    async with _client(env, allowed_hosts=hosts) as c:
        for ok in ("192.168.1.5:8765", "[fe80::1]:8765", "mybox.local:8765", "127.0.0.1"):
            assert (await c.get("/api/project", headers={"host": ok})).status_code == 200, ok
        for bad in ("attacker.example:8765", "other.local"):
            assert (await c.get("/api/project", headers={"host": bad})).status_code == 421, bad


async def test_without_allowed_hosts_the_host_check_is_off(env: Env) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app()), base_url="http://testserver"
    ) as c:
        assert (await c.get("/api/project")).status_code == 200


# ------------------------------------------------------------------------------- Origin


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "http://attacker.example"},
        {"origin": "null"},
        {"origin": "http://localhost:3000"},  # another local app: same-site, not same-origin
        {"origin": "http://127.0.0.1:8766"},  # same host, other port
        {"sec-fetch-site": "cross-site"},
        {"sec-fetch-site": "same-site"},
        {"referer": "http://attacker.example/page.html"},
    ],
)
async def test_cross_origin_writes_are_403(
    env: Env, g: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    r = await g.put("/api/ui/guide", json={"seen": True}, headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "cross_origin", r.text
    r = await g.post("/api/jobs", json={"to": "group"}, headers=headers)
    assert r.status_code == 403
    assert env.st.enqueued == []


@pytest.mark.parametrize(
    "headers",
    [
        {},  # curl, the CLI, Playwright's request fixture
        {"origin": "http://127.0.0.1:8765", "sec-fetch-site": "same-origin"},
        {"origin": "http://127.0.0.1:8765", "referer": "http://127.0.0.1:8765/verify"},
        {"sec-fetch-site": "none"},
    ],
)
async def test_same_origin_writes_pass(g: httpx.AsyncClient, headers: dict[str, str]) -> None:
    r = await g.put("/api/ui/guide", json={"seen": True}, headers=headers)
    assert r.status_code == 200, r.text


async def test_vite_proxy_shape_passes(g: httpx.AsyncClient) -> None:
    """Vite (changeOrigin off) forwards the browser's Host; Origin is the Vite origin."""
    h = {
        "host": "127.0.0.1:5173",
        "origin": "http://127.0.0.1:5173",
        "sec-fetch-site": "same-origin",
        "referer": "http://127.0.0.1:5173/scope",
    }
    assert (await g.put("/api/ui/guide", json={"seen": True}, headers=h)).status_code == 200
    assert (await g.post("/api/sources", files=PDF, headers=h)).status_code == 202


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "http://attacker.example"},
        {"origin": "null"},
        {"sec-fetch-site": "cross-site"},
        {"referer": "http://attacker.example/"},
    ],
)
async def test_cross_origin_multipart_upload_is_refused_before_anything_is_stored(
    env: Env, g: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    r = await g.post("/api/sources", files=PDF, headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "cross_origin"
    _nothing_uploaded(env)


async def test_same_origin_and_headerless_uploads_pass(env: Env, g: httpx.AsyncClient) -> None:
    own = {"origin": "http://127.0.0.1:8765", "sec-fetch-site": "same-origin"}
    assert (await g.post("/api/sources", files=PDF, headers=own)).status_code == 202
    assert (await g.post("/api/sources", files=PDF)).status_code == 202
    assert [k for k, _, _ in env.st.enqueued] == ["ingest_run", "ingest_run"]


async def test_reads_with_a_foreign_origin_pass_but_get_no_cors_header(
    g: httpx.AsyncClient,
) -> None:
    r = await g.get("/api/project", headers={"origin": "http://attacker.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


# ------------------------------------------------------------------------------- body cap


async def test_upload_over_the_cap_with_content_length_is_413(env: Env) -> None:
    async with _client(env, max_body_bytes=1000) as c:
        big = [("files", ("big.pdf", b"x" * 5000, "application/pdf"))]
        r = await c.post("/api/sources", files=big)
    assert r.status_code == 413 and r.json()["code"] == "too_large"
    assert "1000" in r.json()["detail"]
    _nothing_uploaded(env)


async def test_chunked_upload_over_the_cap_stops_reading_and_is_413(env: Env) -> None:
    boundary = "b0undary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="big.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    pulled = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal pulled
        yield head
        for _ in range(50):
            pulled += 1
            yield b"x" * 500
        yield f"\r\n--{boundary}--\r\n".encode()

    async with _client(env, max_body_bytes=2000) as c:
        r = await c.post(
            "/api/sources",
            content=body(),
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
    assert r.status_code == 413 and r.json()["code"] == "too_large"
    assert pulled < 10, f"kept reading after the cap ({pulled} chunks)"
    _nothing_uploaded(env)


async def test_upload_under_the_cap_passes(env: Env) -> None:
    async with _client(env, max_body_bytes=100_000) as c:
        assert (await c.post("/api/sources", files=PDF)).status_code == 202


def test_default_cap_is_generous() -> None:
    assert DEFAULT_MAX_BODY_BYTES == 200 * 1024 * 1024


class _Upload:
    def __init__(self, name: str, data: bytes) -> None:
        self.filename = name
        self.file = io.BytesIO(data)


def test_save_upload_stops_at_its_own_cap_and_leaves_no_temp_file(tmp_path: Path) -> None:
    uploads = tmp_path / ".uploads"
    with pytest.raises(ApiError) as e:
        _save_upload(uploads, _Upload("big.pdf", b"x" * (3 << 20)), limit=1 << 20)  # type: ignore[arg-type]
    assert e.value.status == 413 and e.value.code == "too_large"
    assert list(uploads.rglob("*")) == []
    ok = _save_upload(uploads, _Upload("ok.pdf", b"y" * 100), limit=1 << 20)  # type: ignore[arg-type]
    assert ok.read_bytes() == b"y" * 100


# ------------------------------------------------------------------------------- not found


def _app_with_raiser(env: Env, exc: Exception) -> Any:
    app = env.app()

    @app.get("/api/_raise_test")
    def _raise() -> None:
        raise exc

    # the SPA catch-all was registered first; move the test route in front of it
    app.router.routes.insert(0, app.router.routes.pop())
    return app


async def test_a_plain_key_error_is_a_500_not_a_404(env: Env) -> None:
    app = _app_with_raiser(env, KeyError("typo_in_code"))
    t = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=t, base_url="http://t") as c:
        r = await c.get("/api/_raise_test")
    assert r.status_code == 500 and r.json()["code"] == "internal_error"
    assert "typo_in_code" not in r.text  # internals stay in the server log
    # and it is re-raised, so uvicorn logs it with its traceback
    t2 = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=t2, base_url="http://t") as c:
        with pytest.raises(KeyError):
            await c.get("/api/_raise_test")


async def test_not_found_is_404(env: Env) -> None:
    app = _app_with_raiser(env, NotFound("flag-000042"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/_raise_test")
    assert r.status_code == 404
    assert r.json() == {"detail": "not found: flag-000042", "code": "not_found"}


async def test_service_not_found_paths_still_404(g: httpx.AsyncClient) -> None:
    assert (await g.get("/api/jobs/job-999999")).status_code == 404
    assert (await g.get("/api/verify/blocks/b-doc-p009-99")).status_code == 404
    assert (
        await g.post("/api/flags/flag-999999/resolve", json={"resolution": "x"})
    ).status_code in (
        404,
        422,
    )


# ------------------------------------------------------------------------------- serve


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2"])
def test_loopback_bind_has_no_warning(host: str) -> None:
    assert bind_warning(host, allowed_hosts_for(host)) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "mybox.local"])
def test_non_loopback_bind_warns_plainly(host: str) -> None:
    w = bind_warning(host, allowed_hosts_for(host))
    assert w is not None
    assert "no authentication" in w and "anyone" in w
    assert "read the manuals" in w and "run jobs" in w
    assert "--allow-host" in w


def test_cli_defaults_to_loopback_and_passes_the_guard_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuallabor import serve as serve_mod
    from manuallabor.cli import app

    seen: list[dict[str, Any]] = []

    def fake_serve(paths: Any, **kw: Any) -> int:
        seen.append(kw)
        return 0

    monkeypatch.setattr(serve_mod, "serve", fake_serve)
    (tmp_path / "p").mkdir()
    r = CliRunner().invoke(app, ["serve", str(tmp_path / "p")])
    assert r.exit_code == 0, r.output
    assert seen[-1]["host"] == "127.0.0.1"
    assert seen[-1]["allow_hosts"] == []
    assert seen[-1]["max_upload_bytes"] == DEFAULT_MAX_BODY_BYTES
    r = CliRunner().invoke(
        app,
        [
            "serve",
            str(tmp_path / "p"),
            "--host",
            "0.0.0.0",
            "--allow-host",
            "mybox.local",
            "--max-upload-mb",
            "5",
        ],
    )
    assert r.exit_code == 0, r.output
    assert seen[-1]["host"] == "0.0.0.0" and seen[-1]["allow_hosts"] == ["mybox.local"]
    assert seen[-1]["max_upload_bytes"] == 5 * 1024 * 1024


def test_serve_prints_the_warning_and_guards_the_app(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from manuallabor import serve as serve_mod

    built: list[Any] = []
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, *a, **k: built.append(self.config))
    code = serve_mod.serve(
        env.paths,
        host="0.0.0.0",
        port=8791,
        dev=True,
        open_services=lambda p, m, r: env.services,
        allow_hosts=["mybox.local"],
        max_upload_bytes=1234,
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "no authentication" in err and "mybox.local" in err
    app = built[0].app
    guard = [m for m in app.user_middleware if m.cls is RequestGuard]
    assert guard and "mybox.local" in guard[0].kwargs["allowed_hosts"]
    assert guard[0].kwargs["max_body_bytes"] == 1234


def test_serve_on_loopback_prints_no_warning(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from manuallabor import serve as serve_mod

    monkeypatch.setattr(uvicorn.Server, "run", lambda self, *a, **k: None)
    serve_mod.serve(env.paths, dev=True, open_services=lambda p, m, r: env.services)
    assert "no authentication" not in capsys.readouterr().err


# ------------------------------------------------------------------------------- real socket


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


@pytest.fixture
def live(env: Env) -> Iterator[int]:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(env.services, dev=True, allowed_hosts=LOOP, max_body_bytes=4096),
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    t0 = time.monotonic()
    while not server.started:
        assert time.monotonic() - t0 < 30, "uvicorn did not start"
        time.sleep(0.02)
    try:
        yield port
    finally:
        server.should_exit = True
        t.join(timeout=30)


def _raw(port: int, method: str, path: str, headers: dict[str, str], body: bytes = b"") -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in headers.items():
            conn.putheader(k, v)
        conn.endheaders(body or None)
        return conn.getresponse().status
    finally:
        conn.close()


def test_uvicorn_passes_the_host_header_through_to_the_guard(live: int) -> None:
    assert _raw(live, "GET", "/api/project", {"Host": f"127.0.0.1:{live}"}) == 200
    assert _raw(live, "GET", "/api/project", {"Host": "rebind.attacker.example"}) == 421
    form = {"Host": f"localhost:{live}", "Origin": "http://evil.example"}
    form["Content-Type"] = "multipart/form-data; boundary=x"
    form["Content-Length"] = "4"
    assert _raw(live, "POST", "/api/sources", form, b"--x-") == 403
    big = {"Host": f"127.0.0.1:{live}", "Content-Type": "application/json"}
    big["Content-Length"] = str(10_000)
    assert _raw(live, "PUT", "/api/ui/guide", big, b"{" + b" " * 9_998 + b"}") == 413


def test_vite_dev_proxy_keeps_the_browser_host() -> None:
    """Vite's string shorthand turns changeOrigin on: Host becomes 127.0.0.1:8765 while Origin
    stays http://127.0.0.1:5173, and every UI write through the dev server would be a 403."""
    import re

    cfg = (Path(__file__).resolve().parents[2] / "frontend" / "vite.config.ts").read_text()
    entry = re.search(r'"/api":\s*(\{[^}]*\}|"[^"]*")', cfg)
    assert entry is not None, "no /api proxy entry in vite.config.ts"
    assert re.search(r"changeOrigin:\s*false", entry.group(1)), entry.group(1)
