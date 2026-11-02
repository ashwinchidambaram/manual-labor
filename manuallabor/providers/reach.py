"""Is a configured model host answering? The only network call the jobs layer makes.

Lives under ``providers/`` because invariant 6 confines network imports to this package
(``tests/providers/test_offline.py``). It asks exactly the URL it is given, never a proxy
taken from the environment, so a check can only reach the configured host.
"""

from __future__ import annotations

__all__ = ["http_ok"]


def http_ok(url: str, timeout: float) -> bool:
    """True when the server answered 2xx. Any error (refused, timeout, offline guard) is False."""
    try:
        import httpx

        return httpx.get(url, timeout=timeout, trust_env=False).is_success
    except Exception:
        return False
