#!/usr/bin/env bash
# Build (or reuse) the cached mock project the Playwright e2e suite serves.
# Usage: scripts/e2e-project.sh [cache_dir]   (default: frontend/e2e/.cache)
# The cache is keyed on tests/fixtures/CHECKSUMS.json + project.json; a matching .key skips the build.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="${1:-$ROOT/frontend/e2e/.cache}"
FIX="$ROOT/tests/fixtures"
KEY="$(cat "$FIX/CHECKSUMS.json" "$FIX/project-a/project.json" "$0" | shasum -a 256 | cut -d' ' -f1)"
if [[ -f "$CACHE/.key" && "$(cat "$CACHE/.key")" == "$KEY" && -d "$CACHE/project" ]]; then
  echo "e2e-project: cache hit ($CACHE)"
  exit 0
fi
START=$(date +%s)
rm -rf "$CACHE"
mkdir -p "$CACHE"
mkdir -p "$CACHE/project"
cp "$FIX/project-a/project.json" "$CACHE/project/project.json"
cd "$ROOT"
uv run labor ingest "$CACHE/project" "$FIX/clean.pdf" "$FIX/figures.pdf" "$FIX/scanned.pdf"
uv run labor run "$CACHE/project" --to score2 --mock
STATUS="$(uv run labor status "$CACHE/project" --json)"
python3 - "$STATUS" "$CACHE/project" <<'PY'
import json, sys
from pathlib import Path
st = json.loads(sys.argv[1]); root = Path(sys.argv[2])
def fail(msg):
    print(f"e2e-project: precondition failed: {msg}", file=sys.stderr); sys.exit(1)
docs = st["docs"]
if len(docs) < 2: fail(f"expected >= 2 docs, got {len(docs)}")
for d in docs:
    bad = [n["node"] for n in d["nodes"] if n["state"] != "fresh"]
    if bad: fail(f"{d['doc_id']}: nodes not fresh: {bad}")
parent = topics = False
for d in docs:
    g = json.loads((root / "docs" / d["doc_id"] / "groups.json").read_text())
    parent = parent or any(x.get("parent_id") for x in g["structure"])
    topics = topics or len([t for t in g["topics"] if not t["is_unassigned"]]) >= 2
if not parent: fail("no structure group with a parent")
if not topics: fail("no doc with >= 2 topics")
PY
echo "$KEY" > "$CACHE/.key"
echo "e2e-project: built in $(( $(date +%s) - START ))s"
