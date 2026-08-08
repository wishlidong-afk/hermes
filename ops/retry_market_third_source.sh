#!/bin/bash
# Delayed evidence-only retry for market-admission third-source arbitration.
set -euo pipefail

BASE="$HOME/.hermes/skills/investment/escape-top"
RUNTIME="$BASE"
if [ -d "$BASE/current/hermes_escape_top" ]; then
  RUNTIME="$BASE/current"
fi
export HERMES_RUNTIME_ROOT="$RUNTIME"
export HERMES_DATA_DIR="${HERMES_DATA_DIR:-$RUNTIME/hermes_escape_top}"
export PYTHONPATH="$RUNTIME"

MARKER="$RUNTIME/hermes_escape_top/RUNTIME_LOCK_SHA256"
[ -r "$MARKER" ] || { echo "Hermes runtime marker missing: $MARKER" >&2; exit 65; }
LOCK_SHA="$(tr -d '[:space:]' < "$MARKER")"
PY="$BASE/runtime/$LOCK_SHA/.venv/bin/python"
[ -x "$PY" ] || { echo "Hermes managed Python missing: $PY" >&2; exit 65; }

cd "$RUNTIME"
exec "$PY" -m hermes_escape_top.scripts.retry_market_third_source \
  --lock-timeout "${HERMES_MARKET_THIRD_SOURCE_LOCK_TIMEOUT:-600}"
