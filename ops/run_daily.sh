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
RUNTIME="$BASE"
if [ -d "$BASE/current/hermes_escape_top" ]; then
  RUNTIME="$BASE/current"
fi
export HERMES_DATA_DIR="${HERMES_DATA_DIR:-$RUNTIME/hermes_escape_top}"
LOG_DIR="$HOME/.hermes/logs/daily"
mkdir -p "$LOG_DIR"
LOG="${HERMES_RUN_LOG:-$LOG_DIR/daily_$(date +%F).log}"

MARKER="$RUNTIME/hermes_escape_top/RUNTIME_LOCK_SHA256"
[ -r "$MARKER" ] || { echo "Hermes runtime marker missing: $MARKER" >&2; exit 65; }
LOCK_SHA="$(tr -d '[:space:]' < "$MARKER")"
PY="$BASE/runtime/$LOCK_SHA/.venv/bin/python"
[ -x "$PY" ] || { echo "Hermes managed Python missing: $PY" >&2; exit 65; }
DEPLOY_VERIFY=0
[ "${1:-}" = "--deploy-verify" ] && DEPLOY_VERIFY=1

{
  echo "=== hermes daily run start $(date '+%F %T %Z') ==="
  "$PY" -c 'import ssl, numpy, pandas, scipy; assert ssl.OPENSSL_VERSION.startswith("OpenSSL ")'
  if [ "${1:-}" = "--deploy-verify" ]; then
    HERMES_RUNTIME_ROOT="$RUNTIME" "$PY" "$RUNTIME/scripts/run_daily.py" --deploy-verify
  else
    HERMES_RUNTIME_ROOT="$RUNTIME" "$PY" "$RUNTIME/scripts/run_daily.py" --run-type scheduled "$@"
  fi
} >>"$LOG" 2>&1
rc=$?
echo "=== exit $rc at $(date '+%F %T') ===" >>"$LOG"

if [ "$rc" -ne 0 ] && [ "$DEPLOY_VERIFY" -eq 0 ]; then
  /usr/bin/osascript -e "display notification \"exit $rc — see ${LOG/#$HOME/~}\" with title \"Hermes daily run FAILED\" sound name \"Basso\"" || true
elif [ "$rc" -eq 0 ] && [ "$DEPLOY_VERIFY" -eq 0 ]; then
  # Success heartbeat: best-effort, never affects the run's exit code.
  gh api "gists/$HEARTBEAT_GIST" -X PATCH \
    -f "files[heartbeat.txt][content]=$(date '+%F %T %Z') daily run OK" \
    >/dev/null 2>>"$LOG" || echo "WARNING: heartbeat push failed" >>"$LOG"
fi
exit "$rc"
