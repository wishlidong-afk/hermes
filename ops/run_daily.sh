#!/bin/bash
# Hermes daily live run wrapper — invoked by launchd (com.hermes.daily)
# or manually: bash ~/.hermes/bin/run_daily.sh
# Roadmap: docs/OPTIMIZATION_ROADMAP.md T1
set -u

# launchd provides a bare environment; be explicit.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="en_US.UTF-8"

# Cloud dead-man heartbeat target (secret gist; checked by a scheduled cloud
# routine so a machine that is off for days still produces an alert).
HEARTBEAT_GIST="3b2b29b5a45edb8964f2d0d119f619ba"

BASE="$HOME/.hermes/skills/investment/escape-top"
LOG_DIR="$HOME/.hermes/logs/daily"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_$(date +%F).log"

# System python3 verified to import numpy/pandas/scipy (3.9.6).
# The normal path is --live --commit-state. --deploy-verify traverses the same
# entry as a non-official manual preview without committing state or receipt.
PY=/usr/bin/python3

{
  echo "=== hermes daily run start $(date '+%F %T %Z') ==="
  "$PY" -c 'import numpy, pandas, scipy' || echo "WARNING: $PY lacks scientific deps"
  if [ "${1:-}" = "--deploy-verify" ]; then
    "$PY" "$BASE/scripts/run_daily.py" --deploy-verify
  else
    "$PY" "$BASE/scripts/run_daily.py" --run-type scheduled "$@"
  fi
} >>"$LOG" 2>&1
rc=$?
echo "=== exit $rc at $(date '+%F %T') ===" >>"$LOG"

if [ "$rc" -ne 0 ]; then
  /usr/bin/osascript -e "display notification \"exit $rc — see ${LOG/#$HOME/~}\" with title \"Hermes daily run FAILED\" sound name \"Basso\"" || true
else
  # Success heartbeat: best-effort, never affects the run's exit code.
  gh api "gists/$HEARTBEAT_GIST" -X PATCH \
    -f "files[heartbeat.txt][content]=$(date '+%F %T %Z') daily run OK" \
    >/dev/null 2>>"$LOG" || echo "WARNING: heartbeat push failed" >>"$LOG"
fi
exit "$rc"
