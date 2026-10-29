#!/usr/bin/env bash
# SPEC section 11 acceptance run. Writes build/acceptance/<ac>-<step>.{cmd,out,rc,secs}, then
# renders docs/ACCEPTANCE.md from them (scripts/render_acceptance.py). A step that cannot run
# renders NOT VERIFIED, never PASS.
#
#   scripts/acceptance.sh [--live]
#
# --live also runs AC8 (needs Ollama and the small-tier models). Without it AC8 is NOT VERIFIED.
# Environment:
#   ACCEPT_SKIP="4 6"                   do not run those AC numbers (they render NOT VERIFIED)
#   ACCEPT_ONLY="3 5"                   run only those AC numbers
#   ACCEPT_KEEP=1                       keep earlier results in ACCEPT_OUT (re-run some ACs)
#   ACCEPT_PYTEST_FLAGS="--basetemp=X"  appended to every pytest call
#   ACCEPT_OUT=build/acceptance         result directory
#   ACCEPT_DOC=docs/ACCEPTANCE.md       rendered file
# Exit status: 1 if any required step failed, else 0. Never `set -e`: every step runs.
set -u
cd "$(dirname "$0")/.." || exit 2
ROOT="$(pwd)"
OUT="${ACCEPT_OUT:-build/acceptance}"
DOC="${ACCEPT_DOC:-docs/ACCEPTANCE.md}"
FLAGS="${ACCEPT_PYTEST_FLAGS:-}"
SKIP=" ${ACCEPT_SKIP:-} "
ONLY="${ACCEPT_ONLY:-}"
LIVE=0
[ "${1:-}" = "--live" ] && LIVE=1

[ "${ACCEPT_KEEP:-0}" = "1" ] || rm -rf "$OUT"
mkdir -p "$OUT"
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/date.txt"
echo "$LIVE" > "$OUT/live.txt"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/labor-acceptance.XXXXXX")"
START=$(date +%s)
FAILED=0

# step <ac> <k> <command...>: run, capture output, exit code and seconds.
step() {
  local id="$1-$2"
  shift 2
  case "$SKIP" in *" ${id%%-*} "*) echo "skip $id (ACCEPT_SKIP)"; return 0 ;; esac
  if [ -n "$ONLY" ]; then
    case " $ONLY " in *" ${id%%-*} "*) ;; *) return 0 ;; esac
  fi
  printf '%s\n' "$*" > "$OUT/$id.cmd"
  local t0
  t0=$(date +%s)
  echo "== $id: $*"
  ( eval "$*" ) > "$OUT/$id.out" 2>&1
  local rc=$?
  echo "$rc" > "$OUT/$id.rc"
  echo $(( $(date +%s) - t0 )) > "$OUT/$id.secs"
  echo "   rc=$rc ($(cat "$OUT/$id.secs") s)"
  [ "$rc" -ne 0 ] && FAILED=1
  return 0
}

# -- AC0: the whole machine is green -------------------------------------------------------------
step 0 1 "uv run pytest -q $FLAGS"
step 0 2 "uv run ruff check manuallabor tests"
step 0 3 "uv run mypy manuallabor"
step 0 4 "uv run labor schemas export --check"
step 0 5 "uv run labor openapi export --check"

# -- AC1: every fixture round-trips (six-fixture project, mock models) ------------------------
mkdir -p "$TMP/project-all/sources"
cp tests/fixtures/project-a/project.json "$TMP/project-all/project.json"
for f in clean twocol tables scanned figures; do cp "tests/fixtures/$f.pdf" "$TMP/project-all/sources/"; done
cp tests/fixtures/manual.docx "$TMP/project-all/sources/"
step 1 1 "uv run labor check --keep '$TMP/project-all'"
KEPT="$(sed -n 's/^kept //p' "$OUT/1-1.out" 2>/dev/null | tail -1)"

# -- AC2: scanned-fixture recall --------------------------------------------------------------
step 2 1 "uv run pytest tests/scoring -m acc2 -s -q $FLAGS"

# -- AC3: figure methods and caption-reference attachment ------------------------------------
step 3 1 "uv run pytest tests/figures tests/cleanup -m acc3 -s -q $FLAGS"

# -- AC4 / AC6: keyboard-only verify and scope toggle (Playwright) ---------------------------
step 4 1 "cd frontend && npm run e2e -- --grep '@AC4'"
step 6 1 "cd frontend && npm run e2e -- --grep '@AC6'"

# -- AC5: agent proposals carry their re-check results -----------------------------------------
step 5 1 "uv run pytest tests/agent -m acc5 -s -q $FLAGS"

# -- AC7: the export zip validates --------------------------------------------------------------
step 7 1 "uv run pytest tests/export -q $FLAGS"
if [ -n "$KEPT" ] && ls "$KEPT"/export/*.zip > /dev/null 2>&1; then
  ZIP="$(ls "$KEPT"/export/*.zip | head -1)"
  step 7 2 "uv run labor validate-export '$ZIP'"
  step 7 3 "shasum -a 256 '$ZIP'"
fi

# -- AC8: fully local, network disabled (only with --live) ------------------------------------
if [ "$LIVE" -eq 1 ]; then
  step 8 1 "ollama list"
  step 8 2 "MANUALLABOR_OFFLINE=1 MANUALLABOR_OFFLINE_LOG='$ROOT/$OUT/net.log' uv run labor check --live --keep '$TMP/project-all'"
  KEPT8="$(sed -n 's/^kept //p' "$OUT/8-2.out" 2>/dev/null | tail -1)"
  step 8 3 "if [ -s '$ROOT/$OUT/net.log' ]; then echo 'network violations:'; cat '$ROOT/$OUT/net.log'; exit 1; else echo '0 network violations'; fi"
  if [ -n "$KEPT8" ] && [ -f "$KEPT8/llm_calls.jsonl" ]; then
    step 8 4 "uv run python scripts/render_acceptance.py providers '$KEPT8/llm_calls.jsonl'"
  fi
  [ -n "$KEPT8" ] && rm -rf "$(dirname "$KEPT8")"
fi

echo $(( $(date +%s) - START )) > "$OUT/total_secs.txt"
uv run python scripts/render_acceptance.py render "$OUT" > "$DOC"
RC=$?
[ -n "$KEPT" ] && rm -rf "$(dirname "$KEPT")"
rm -rf "$TMP"
echo "wrote $DOC ($(head -3 "$DOC" | tr '\n' ' '))"
[ "$RC" -ne 0 ] && FAILED=1
exit "$FAILED"
