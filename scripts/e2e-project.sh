#!/usr/bin/env bash
# Build (or reuse) the cached mock project the Playwright e2e suite serves.
# Usage: scripts/e2e-project.sh [cache_dir]   (default: frontend/e2e/.cache)
# The cache is keyed on the fixtures, this script, manuallabor/**/*.py and the ALGO_VERSION constants; a matching
# .key skips the build but the cheap precondition checks still run on every hit.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="${1:-$ROOT/frontend/e2e/.cache}"
FIX="$ROOT/tests/fixtures"
# The key covers the fixtures, this script, every Python source (the pipeline that builds the project) and the
# *ALGO_VERSION constants explicitly, so any algorithm change rebuilds the project.
SRC_HASH="$(cd "$ROOT" && find manuallabor -name '*.py' -type f | LC_ALL=C sort | xargs cat | shasum -a 256 | cut -d' ' -f1)"
ALGO="$(cd "$ROOT" && grep -rhE '^[A-Z_]*ALGO_VERSION' manuallabor --include='*.py' | LC_ALL=C sort)"
KEY="$( { cat "$FIX/CHECKSUMS.json" "$FIX/project-a/project.json" "$0"; echo "$SRC_HASH"; echo "$ALGO"; } | shasum -a 256 | cut -d' ' -f1)"

# Cheap preconditions on a project (cached or freshly built): every node fresh, a parent group, >= 2 topics.
check_project() {
  local status
  status="$(cd "$ROOT" && uv run labor status "$CACHE/project" --json)" || return 1
  python3 - "$status" "$CACHE/project" <<'PY'
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
}

if [[ -f "$CACHE/.key" && "$(cat "$CACHE/.key")" == "$KEY" && -d "$CACHE/project" ]]; then
  if check_project; then
    echo "e2e-project: cache hit ($CACHE), preconditions hold"
    exit 0
  fi
  echo "e2e-project: cache hit but preconditions failed; rebuilding" >&2
fi
START=$(date +%s)
rm -rf "$CACHE"
mkdir -p "$CACHE"
mkdir -p "$CACHE/project"
cp "$FIX/project-a/project.json" "$CACHE/project/project.json"
cd "$ROOT"
uv run labor ingest "$CACHE/project" "$FIX/clean.pdf" "$FIX/figures.pdf" "$FIX/scanned.pdf"
uv run labor run "$CACHE/project" --to score2 --mock
check_project
echo "$KEY" > "$CACHE/.key"
echo "e2e-project: built in $(( $(date +%s) - START ))s"
