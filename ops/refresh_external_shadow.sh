#!/bin/bash
# Refresh auxiliary/research sources after the decision pipeline has finished.
# This job records evidence only; it never participates in strategy readiness.
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

LOG_DIR="$HOME/.hermes/logs/external-shadow"
mkdir -p "$LOG_DIR"
DATE_STAMP="$(date +%F)"
LOG="${HERMES_EXTERNAL_SHADOW_LOG:-$LOG_DIR/external_shadow_${DATE_STAMP}.log}"
OUT_JSON="$LOG_DIR/external_shadow_latest.json"
TMP_JSON="$LOG_DIR/.external_shadow_${DATE_STAMP}.$$.json"
RUN_STAMP="$(date +%Y%m%dT%H%M%S%z)_$$"
IMMUTABLE_JSON="$LOG_DIR/external_shadow_${DATE_STAMP}_${RUN_STAMP}.json"
MARKER="$RUNTIME/hermes_escape_top/RUNTIME_LOCK_SHA256"
[ -r "$MARKER" ] || { echo "Hermes runtime marker missing: $MARKER" >&2; exit 65; }
LOCK_SHA="$(tr -d '[:space:]' < "$MARKER")"
PY="$BASE/runtime/$LOCK_SHA/.venv/bin/python"
[ -x "$PY" ] || { echo "Hermes managed Python missing: $PY" >&2; exit 65; }

publish_copy() {
  source_path="$1"
  target_path="$2"
  temp_path="${target_path}.tmp.$$"
  rm -f "$temp_path"
  cp "$source_path" "$temp_path" || return 1
  mv "$temp_path" "$target_path"
}

{
  echo "=== hermes external shadow start $(date '+%F %T %Z') ==="
  cd "$RUNTIME" || exit 1
  "$PY" -m hermes_escape_top.scripts.refresh_external \
    --all --lane shadow \
    --lock-timeout "${HERMES_EXTERNAL_SHADOW_LOCK_TIMEOUT:-0}" >"$TMP_JSON"
} >>"$LOG" 2>&1
rc=$?

if [ -s "$TMP_JSON" ]; then
  if [ -e "$IMMUTABLE_JSON" ] || ! mv "$TMP_JSON" "$IMMUTABLE_JSON"; then
    rc=1
  elif ! publish_copy "$IMMUTABLE_JSON" "$OUT_JSON"; then
    rc=1
  fi
else
  rm -f "$TMP_JSON"
  [ "$rc" -ne 0 ] || rc=1
fi

echo "=== external shadow exit $rc at $(date '+%F %T') ===" >>"$LOG"
exit "$rc"
