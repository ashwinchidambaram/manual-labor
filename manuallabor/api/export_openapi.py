"""`python -m manuallabor.api.export_openapi [--out F] [--check]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from manuallabor.api.openapi import DEFAULT_OUT, export_openapi


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export the API's OpenAPI document.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 on drift")
    args = ap.parse_args(argv)
    ok = export_openapi(args.out, check=args.check)
    if not ok:
        print(f"openapi drift: {args.out}", file=sys.stderr)
        return 1
    print(f"openapi up to date: {args.out}" if args.check else f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
