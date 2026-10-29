"""AC8 negative control: with the offline guard installed (MANUALLABOR_OFFLINE=1), a deliberate
connection to 1.1.1.1:443 must be refused and appear in $MANUALLABOR_OFFLINE_LOG. Proves the
"0 network violations" of the live run is a guard that bites, not a guard that is absent.

    MANUALLABOR_OFFLINE=1 MANUALLABOR_OFFLINE_LOG=<log> uv run python scripts/offline_control.py

Exit 0 and `negative control: 1.1.1.1:443 blocked and logged`, else exit 1. Never connects
when the guard is not installed."""

from __future__ import annotations

import socket
import sys

from manuallabor.providers.offline import install_from_env, violation_log

TARGET = ("1.1.1.1", 443)


def main() -> int:
    if not install_from_env():
        print("offline guard not installed: set MANUALLABOR_OFFLINE=1")
        return 1
    log = violation_log()
    try:
        socket.create_connection(TARGET, timeout=2).close()
    except OSError as exc:
        if "offline guard" not in str(exc):
            print(f"connection failed, but not by the guard: {exc}")
            return 1
    else:
        print("the guard let 1.1.1.1:443 through")
        return 1
    entry = f"{TARGET[0]}:{TARGET[1]}"
    if not log.is_file() or entry not in log.read_text(encoding="utf-8").splitlines():
        print(f"blocked, but {entry} is not in {log}")
        return 1
    print(f"negative control: {entry} blocked and logged ({log})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
