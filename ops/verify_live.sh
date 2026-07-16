#!/bin/bash
# Post-deploy END-TO-END gate: run the REAL daily entry (run_daily.sh -> run_daily.py
# -> python -m package) and assert the EFFECTS actually landed — not just that the
# package imports or unit tests pass. Catches the class of bug that unit tests +
# predeploy_smoke miss: a broken/stale real entry (the B incident: the daily ran
# 4-day-stale orchestration; manifest never re-froze, NEXT-5 never refreshed). Run
# after a deploy, or standalone. It must never create a second scheduled run,
# official receipt, or state commit. Exit non-zero on any failed assertion.
set -uo pipefail

if [ "${HERMES_VERIFY_TEST_MODE:-0}" = "1" ]; then
  BASE="${HERMES_VERIFY_BASE:?test mode requires HERMES_VERIFY_BASE}"
  RUN_DAILY="${HERMES_VERIFY_RUN_DAILY:?test mode requires HERMES_VERIFY_RUN_DAILY}"
  PYTHON="${HERMES_VERIFY_PYTHON:-/usr/bin/python3}"
else
  LIVE_ROOT="$HOME/.hermes/skills/investment/escape-top"
  BASE="$LIVE_ROOT"
  if [ -d "$LIVE_ROOT/current/hermes_escape_top" ]; then
    BASE="$LIVE_ROOT/current"
  fi
  RUN_DAILY="$HOME/.hermes/bin/run_daily.sh"
  MARKER="$BASE/hermes_escape_top/RUNTIME_LOCK_SHA256"
  [ -r "$MARKER" ] || { echo "FAIL: runtime marker missing: $MARKER"; exit 1; }
  LOCK_SHA="$(tr -d '[:space:]' < "$MARKER")"
  PYTHON="$LIVE_ROOT/runtime/$LOCK_SHA/.venv/bin/python"
  [ -x "$PYTHON" ] || { echo "FAIL: managed Python missing: $PYTHON"; exit 1; }
fi
PKG="$BASE/hermes_escape_top"

clone_item() {
  local source="$1"
  local target="$2"
  cp -Rc "$source" "$target" 2>/dev/null || cp -R "$source" "$target"
}

seed_verify_data() {
  local root="$1"
  local source target item name
  mkdir -p "$root/data/archive" || return 1
  for name in history soft_history; do
    source="$PKG/data/$name"
    target="$root/data/$name"
    [ ! -e "$source" ] || clone_item "$source" "$target" || return 1
  done
  for item in "$PKG/data/archive/"* "$PKG/data/archive/".[!.]*; do
    [ -e "$item" ] || continue
    name=$(basename "$item")
    case "$name" in
      audit_log.jsonl|.pipeline.lock) continue ;;
    esac
    clone_item "$item" "$root/data/archive/$name" || return 1
  done
  if [ -e "$PKG/data/sentiment.xls" ]; then
    clone_item "$PKG/data/sentiment.xls" "$root/data/sentiment.xls" || return 1
  fi
}

VERIFY_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hermes-deploy-verify.XXXXXX") \
  || { echo "FAIL: cannot create isolated verify data dir"; exit 1; }
trap 'rm -rf "$VERIFY_ROOT"' EXIT
seed_verify_data "$VERIFY_ROOT" \
  || { echo "FAIL: cannot seed isolated verify data"; exit 1; }

AUDIT="$VERIFY_ROOT/data/archive/audit_log.jsonl"
LOG="$VERIFY_ROOT/verify_daily.log"

echo "== verify_live: running the REAL daily entry in non-official mode =="
HERMES_DATA_DIR="$VERIFY_ROOT" HERMES_RUN_LOG="$LOG" \
  bash "$RUN_DAILY" --deploy-verify
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: run_daily.sh exited $rc"; exit 1; }

fail=0

# 1. A deploy check must append a manual preview, never a second official run.
"$PYTHON" - "$AUDIT" <<'PY' || fail=1
import datetime
import json
import sys

path = sys.argv[1]
lines = [line for line in open(path, encoding="utf-8") if line.strip()]
assert lines, "deploy verification did not append an isolated audit record"
payload = json.loads(lines[-1]).get("payload", {})
assert payload.get("run_type") == "manual_rerun", payload.get("run_type")
run_ts = datetime.datetime.fromisoformat(payload["run_ts"])
age = (datetime.datetime.now(datetime.timezone.utc) - run_ts).total_seconds()
assert 0 <= age < 600, f"manual preview audit is stale: {age:.0f}s"
print(f"  ok: non-official audit appended as_of={payload.get('as_of')} age={age:.0f}s")
PY

# 2. the maintenance steps actually executed (effects visible in this run's log) —
#    a stale/half engine would be missing these even on exit 0.
for step in "score_pipeline OK" "\[manifest\]" "\[NEXT5\]"; do
  if grep -qE "$step" "$LOG"; then
    echo "  ok: ran $step"
  else
    echo "  FAIL: real run is missing step: $step"; fail=1
  fi
done
if grep -qE "\[receipt\]|state committed" "$LOG"; then
  echo "  FAIL: deploy verification wrote official receipt/state"; fail=1
else
  echo "  ok: official receipt/state untouched"
fi

if [ "$fail" -eq 0 ]; then
  echo "== verify_live PASS =="; exit 0
else
  echo "== verify_live FAIL — the real entry did not produce the expected effects =="; exit 2
fi
