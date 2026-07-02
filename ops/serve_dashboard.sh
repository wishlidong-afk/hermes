#!/bin/bash
# Hermes 8766 dashboard — launchd entry (com.hermes.dashboard).
# Serves from the LIVE package (~/.hermes), not the repo: launchd agents have
# no TCC grant for ~/Documents, and the operator dashboard should track
# deploys, not repo WIP. Code updates reach it via scripts/deploy_to_live.sh.
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
BASE="$HOME/.hermes/skills/investment/escape-top"
RUNTIME="$BASE"
if [ -d "$BASE/current/hermes_escape_top" ]; then
  RUNTIME="$BASE/current"
fi
export HERMES_RUNTIME_ROOT="$RUNTIME"
export PYTHONPATH="$RUNTIME"
export HERMES_DATA_DIR="$RUNTIME/hermes_escape_top"
# Enables the fail-secure write-endpoint auth (golive/refresh/confirm). The
# token is provided to the browser out-of-band via localStorage — never
# injected into page HTML, or a DNS-rebinding read would defeat the guard.
TOKEN_FILE="$HOME/.hermes/hermes_confirm_token.txt"
[ -f "$TOKEN_FILE" ] && export HERMES_CONFIRM_TOKEN="$(cat "$TOKEN_FILE")"
cd "$RUNTIME" || exit 1
exec /usr/bin/python3 -u -m hermes_escape_top.cli serve --as-of latest --host 127.0.0.1 --port 8766
