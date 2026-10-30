"""Request guard for the local API (design 07 section 15; code review F3).

One pure ASGI middleware, in front of every route:
1. Host allow-list (stops DNS rebinding): 421 `bad_host`.
2. Same-origin writes: on POST/PUT/PATCH/DELETE and websocket handshakes, `Origin`,
   `Sec-Fetch-Site` and `Referer`, each when present, must say same-origin: 403 `cross_origin`.
3. Body cap: 413 `too_large`, before the app reads anything when `Content-Length` says so,
   otherwise at the first chunk past the cap.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("manuallabor.api")

LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SAME_ORIGIN_FETCH_SITES = frozenset({"same-origin", "none"})
DEFAULT_MAX_BODY_BYTES = 200 * 1024 * 1024
# allow-list marker: a wildcard bind also accepts any IP-literal Host (see allowed_hosts_for)
ANY_IP_LITERAL = "*ip*"


def _strip_brackets(host: str) -> str:
    h = host.strip().lower()
    return h[1:-1] if h.startswith("[") and h.endswith("]") else h


def _is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def is_loopback(host: str) -> bool:
    h = _strip_brackets(host)
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def allowed_hosts_for(bind_host: str, extra: Iterable[str] = ()) -> frozenset[str]:
    """Host names `labor serve --host <bind_host> [--allow-host <extra>...]` answers to."""
    names = set(LOOPBACK_NAMES)
    h = _strip_brackets(bind_host)
    if h in WILDCARD_HOSTS:
        names.add(ANY_IP_LITERAL)
    else:
        names.add(h)
    names.update(_strip_brackets(e) for e in extra if e.strip())
    return frozenset(names)


def host_name(header: str) -> str:
    """The name part of a `Host` header: lower-cased, port and IPv6 brackets removed."""
    h = header.strip().lower()
    if h.startswith("["):
        end = h.find("]")
        return h[1:end] if end != -1 else h
    name, sep, port = h.rpartition(":")
    if sep and port.isdigit() and ":" not in name:
        return name
    return h


def host_allowed(header: str | None, allowed: frozenset[str]) -> bool:
    if not header:
        return False
    name = host_name(header)
    if name in allowed:
        return True
    return ANY_IP_LITERAL in allowed and _is_ip(name)


def bind_warning(host: str, allowed: frozenset[str]) -> str | None:
    """The plain warning `labor serve` prints for a non-loopback bind (None for loopback)."""
    if is_loopback(host):
        return None
    names = sorted(n for n in allowed if n != ANY_IP_LITERAL)
    if ANY_IP_LITERAL in allowed:
        names.append("any IP address of this machine")
    return (
        f"labor serve: WARNING: listening on {host}, not only on this machine. The server has no "
        "authentication: anyone who can reach this address on your network can read the manuals "
        "in this project, download its exports and decision log, and run jobs (including ones "
        "that use API-key models).\n"
        f"labor serve: requests must name one of these hosts: {', '.join(names)}. Add a DNS name "
        "with --allow-host NAME. To keep the server private, leave --host at 127.0.0.1."
    )


def _netloc(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return parts.netloc.lower()


def cross_origin_reason(headers: Headers) -> str | None:
    """Why a write is not same-origin, or None. Headers that are absent do not count."""
    own = (headers.get("host") or "").strip().lower()
    origin = headers.get("origin")
    if origin is not None and _netloc(origin) != own:
        return f"Origin {origin!r} is not this server ({own})"
    site = headers.get("sec-fetch-site")
    if site is not None and site.strip().lower() not in SAME_ORIGIN_FETCH_SITES:
        return f"Sec-Fetch-Site is {site!r}"
    referer = headers.get("referer")
    if referer is not None and _netloc(referer) != own:
        return f"Referer {referer!r} is not this server ({own})"
    return None


class _BodyTooLarge(Exception):
    pass


async def _send_json(send: Send, status: int, code: str, detail: str) -> None:
    body = json.dumps({"detail": detail, "code": code}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestGuard:
    """See the module docstring. `allowed_hosts=None` disables only the Host check (tests)."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: Iterable[str] | None = None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self.app = app
        self.allowed = None if allowed_hosts is None else frozenset(allowed_hosts)
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        method = scope.get("method", "GET") if scope["type"] == "http" else "WEBSOCKET"
        path = scope.get("path", "")
        rejection = self._check(scope["type"], method, headers)
        if rejection is not None:
            status, code, detail = rejection
            log.warning("rejected %s %s: %s", method, path, detail)
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await _send_json(send, status, code, detail)
            return
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await self._capped(scope, receive, send, headers, method, path)

    def _check(self, kind: str, method: str, headers: Headers) -> tuple[int, str, str] | None:
        host = headers.get("host")
        if self.allowed is not None and not host_allowed(host, self.allowed):
            return 421, "bad_host", f"this server does not answer to host {host!r}"
        if kind == "websocket" or method in UNSAFE_METHODS:
            reason = cross_origin_reason(headers)
            if reason is not None:
                return 403, "cross_origin", f"cross-origin write refused: {reason}"
        return None

    async def _capped(
        self, scope: Scope, receive: Receive, send: Send, headers: Headers, method: str, path: str
    ) -> None:
        limit = self.max_body_bytes
        detail = f"request body is larger than the server's limit of {limit} bytes"
        declared = headers.get("content-length")
        if declared is not None and declared.strip().isdigit() and int(declared) > limit:
            log.warning("rejected %s %s: Content-Length %s over %d", method, path, declared, limit)
            await _send_json(send, 413, "too_large", detail)
            return
        state: dict[str, Any] = {"seen": 0, "over": False, "app_started": False, "sent": False}

        async def counting_receive() -> Message:
            msg = await receive()
            if msg["type"] == "http.request":
                state["seen"] += len(msg.get("body", b""))
                if state["seen"] > limit:
                    state["over"] = True
                    raise _BodyTooLarge
            return msg

        async def guarded_send(msg: Message) -> None:
            if state["over"] and not state["app_started"]:
                # the app's own answer to a body it could not finish reading is replaced
                if not state["sent"]:
                    state["sent"] = True
                    await _send_json(send, 413, "too_large", detail)
                return
            if msg["type"] == "http.response.start":
                state["app_started"] = True
            await send(msg)

        with contextlib.suppress(_BodyTooLarge):  # raised by counting_receive, answered below
            await self.app(scope, counting_receive, guarded_send)
        if state["over"]:
            log.warning("rejected %s %s: body over %d bytes", method, path, limit)
            if not state["app_started"] and not state["sent"]:
                state["sent"] = True
                await _send_json(send, 413, "too_large", detail)
