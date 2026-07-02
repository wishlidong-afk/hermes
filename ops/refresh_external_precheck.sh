#!/bin/bash
# Hermes external source precheck — runs before the official daily job.
# It refreshes/validates FRED/NAAIM/AAII source ledgers without scoring or
# writing official run state. launchd: com.hermes.external-precheck.
set -u

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="en_US.UTF-8"

BASE="$HOME/.hermes/skills/investment/escape-top"
RUNTIME="$BASE"
if [ -d "$BASE/current/hermes_escape_top" ]; then
  RUNTIME="$BASE/current"
fi
export HERMES_RUNTIME_ROOT="$RUNTIME"
export HERMES_DATA_DIR="${HERMES_DATA_DIR:-$RUNTIME/hermes_escape_top}"
export PYTHONPATH="$RUNTIME"

LOG_DIR="$HOME/.hermes/logs/external"
mkdir -p "$LOG_DIR"
mkdir -p "$HOME/.hermes/external_imports"
LOG="${HERMES_EXTERNAL_PRECHECK_LOG:-$LOG_DIR/external_precheck_$(date +%F).log}"
OUT_JSON="$LOG_DIR/external_precheck_latest.json"
TMP_JSON="$OUT_JSON.$$"
PY=/usr/bin/python3

{
  echo "=== hermes external precheck start $(date '+%F %T %Z') ==="
  cd "$RUNTIME" || exit 1
  "$PY" -m hermes_escape_top.scripts.refresh_external --pre-daily-check >"$TMP_JSON"
} >>"$LOG" 2>&1
rc=$?

if [ "$rc" -eq 0 ]; then
  mv "$TMP_JSON" "$OUT_JSON"
  "$PY" - "$OUT_JSON" >>"$LOG" 2>&1 <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
ready = bool(payload.get("ready"))
blocking = payload.get("blocking_sources") or []
warnings = payload.get("warning_sources") or []
print(f"[external-precheck] ready={ready} blocking={blocking} warnings={warnings}")
raise SystemExit(0 if ready else 3)
PY
  rc=$?
else
  rm -f "$TMP_JSON"
fi

echo "=== external precheck exit $rc at $(date '+%F %T') ===" >>"$LOG"
if [ "$rc" -ne 0 ]; then
  /usr/bin/osascript -e "display notification \"exit $rc — see ${LOG/#$HOME/~}\" with title \"Hermes external data precheck FAILED\" sound name \"Basso\"" >/dev/null 2>&1 || true
fi
exit "$rc"
