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
DATE_STAMP="$(date +%F)"
LOG="${HERMES_EXTERNAL_PRECHECK_LOG:-$LOG_DIR/external_precheck_${DATE_STAMP}.log}"
OUT_JSON="$LOG_DIR/external_precheck_latest.json"
DATED_JSON="$LOG_DIR/external_precheck_${DATE_STAMP}.json"
OUT_MD="$LOG_DIR/external_precheck_latest.md"
DATED_MD="$LOG_DIR/external_precheck_${DATE_STAMP}.md"
TMP_JSON="$LOG_DIR/.external_precheck_${DATE_STAMP}.$$.json"
TMP_MD="$LOG_DIR/.external_precheck_${DATE_STAMP}.$$.md"
PY=/usr/bin/python3

{
  echo "=== hermes external precheck start $(date '+%F %T %Z') ==="
  cd "$RUNTIME" || exit 1
  "$PY" -m hermes_escape_top.scripts.refresh_external --pre-daily-check >"$TMP_JSON"
} >>"$LOG" 2>&1
rc=$?

if [ "$rc" -eq 0 ]; then
  cp "$TMP_JSON" "$DATED_JSON"
  mv "$TMP_JSON" "$OUT_JSON"
  "$PY" - "$OUT_JSON" "$TMP_MD" >>"$LOG" 2>&1 <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
md_path = Path(sys.argv[2])
with open(path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
ready = bool(payload.get("ready"))
blocking = payload.get("blocking_sources") or []
warnings = payload.get("warning_sources") or []
nonblocking_errors = payload.get("nonblocking_refresh_error_sources") or []
blocking_errors = payload.get("blocking_refresh_error_sources") or []
refresh = payload.get("refresh") or {}
refresh_sources = refresh.get("sources") or {}
precheck = payload.get("precheck") or {}
precheck_sources = precheck.get("sources") or {}


def cell(value):
    if value is None:
        return ""
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


rows = []
source_names = sorted(set(refresh_sources) | set(precheck_sources))
for name in source_names:
    r = refresh_sources.get(name) or {}
    p = precheck_sources.get(name) or {}
    action = r.get("action") or p.get("action") or ""
    status = r.get("status") or p.get("status") or ""
    latest = p.get("latest_date") or r.get("latest_date") or r.get("promoted_latest_date") or ""
    detail = (
        r.get("fallback_import_skip_reason")
        or r.get("error")
        or p.get("error")
        or r.get("message")
        or ""
    )
    rows.append(f"| {cell(name)} | {cell(status)} | {cell(latest)} | {cell(action)} | {cell(detail)} |")

lines = [
    f"# External Precheck {payload.get('checked_at') or ''}".rstrip(),
    "",
    f"- ready: `{ready}`",
    f"- blocking_sources: `{blocking}`",
    f"- warning_sources: `{warnings}`",
    f"- nonblocking_refresh_error_sources: `{nonblocking_errors}`",
    f"- blocking_refresh_error_sources: `{blocking_errors}`",
    f"- refresh_ok: `{refresh.get('ok')}`",
    f"- refresh_ok_count: `{refresh.get('ok_count')}`",
    f"- refresh_error_count: `{refresh.get('error_count')}`",
    "",
    "| Source | Status | Latest | Action | Detail |",
    "|---|---:|---:|---|---|",
]
lines.extend(rows or ["| _none_ |  |  |  |  |"])
lines.append("")
md_path.write_text("\n".join(lines), encoding="utf-8")

print(f"[external-precheck] ready={ready} blocking={blocking} warnings={warnings}")
raise SystemExit(0 if ready else 3)
PY
  rc=$?
  if [ -f "$TMP_MD" ]; then
    cp "$TMP_MD" "$DATED_MD"
    mv "$TMP_MD" "$OUT_MD"
  else
    rm -f "$TMP_MD"
  fi
else
  rm -f "$TMP_JSON" "$TMP_MD"
fi

echo "=== external precheck exit $rc at $(date '+%F %T') ===" >>"$LOG"
if [ "$rc" -ne 0 ]; then
  /usr/bin/osascript -e "display notification \"exit $rc — see ${LOG/#$HOME/~}\" with title \"Hermes external data precheck FAILED\" sound name \"Basso\"" >/dev/null 2>&1 || true
fi
exit "$rc"
