#!/usr/bin/env bash
# Serve a throwaway copy of the cached e2e project (mutations never touch the cache).
# Env: E2E_PORT (default 8765), E2E_DEV (1 = API only for Vite's proxy, 0 = also serve frontend/dist).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="$ROOT/frontend/e2e/.cache"
PORT="${E2E_PORT:-8765}"
DEV_FLAG=()
[[ "${E2E_DEV:-1}" == "1" ]] && DEV_FLAG=(--dev)

# Two servers may start at once: build the cache under a mkdir lock.
mkdir -p "$ROOT/frontend/e2e"
LOCK="$ROOT/frontend/e2e/.cache.lock"
until mkdir "$LOCK" 2>/dev/null; do sleep 1; done
"$ROOT/scripts/e2e-project.sh" "$CACHE" >&2 || { rmdir "$LOCK"; exit 1; }
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ml-e2e-XXXXXX")"
cp -R "$CACHE/project" "$TMP/project"
rmdir "$LOCK"

cd "$ROOT"
uv run labor serve "$TMP/project" "${DEV_FLAG[@]}" --mock --port "$PORT" &
PID=$!
trap 'kill -TERM $PID 2>/dev/null || true; wait $PID 2>/dev/null || true; rm -rf "$TMP"' EXIT INT TERM
wait $PID
