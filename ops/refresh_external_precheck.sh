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
MARKER="$RUNTIME/hermes_escape_top/RUNTIME_LOCK_SHA256"
[ -r "$MARKER" ] || { echo "Hermes runtime marker missing: $MARKER" >&2; exit 65; }
LOCK_SHA="$(tr -d '[:space:]' < "$MARKER")"
PY="$BASE/runtime/$LOCK_SHA/.venv/bin/python"
[ -x "$PY" ] || { echo "Hermes managed Python missing: $PY" >&2; exit 65; }
MODE="${HERMES_EXTERNAL_PRECHECK_MODE:-auto}"
if [ "$MODE" = "auto" ]; then
  HHMM="$(date +%H%M)"
  if [ "$HHMM" -ge 700 ]; then
    MODE="retry_needed"
  else
    MODE="all"
  fi
fi
if [ "$MODE" = "retry_needed" ]; then
  REFRESH_ARG="--retry-needed"
else
  REFRESH_ARG="--pre-daily-check"
fi
RUN_STAMP="$(date +%Y%m%dT%H%M%S%z)_${MODE}_$$"
IMMUTABLE_JSON="$LOG_DIR/external_precheck_${DATE_STAMP}_${RUN_STAMP}.json"
IMMUTABLE_MD="$LOG_DIR/external_precheck_${DATE_STAMP}_${RUN_STAMP}.md"

publish_copy() {
  source_path="$1"
  target_path="$2"
  temp_path="${target_path}.tmp.$$"
  rm -f "$temp_path"
  cp "$source_path" "$temp_path" || return 1
  mv "$temp_path" "$target_path"
}

{
  echo "=== hermes external precheck start $(date '+%F %T %Z') ==="
  cd "$RUNTIME" || exit 1
  echo "[external-precheck] mode=$MODE"
  "$PY" -m hermes_escape_top.scripts.refresh_external "$REFRESH_ARG" \
    --lock-timeout "${HERMES_EXTERNAL_PRECHECK_LOCK_TIMEOUT:-600}" >"$TMP_JSON"
} >>"$LOG" 2>&1
rc=$?

if [ "$rc" -eq 0 ]; then
  if [ -e "$IMMUTABLE_JSON" ] || ! mv "$TMP_JSON" "$IMMUTABLE_JSON"; then
    rc=1
  elif ! publish_copy "$IMMUTABLE_JSON" "$DATED_JSON" || ! publish_copy "$IMMUTABLE_JSON" "$OUT_JSON"; then
    rc=1
  fi
fi

if [ "$rc" -eq 0 ]; then
  "$PY" - "$IMMUTABLE_JSON" "$TMP_MD" >>"$LOG" 2>&1 <<'PY'
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
refresh_runs = refresh.get("runs") or []
refresh_runs_by_source = {
    item.get("source_id"): item for item in refresh_runs if isinstance(item, dict) and item.get("source_id")
}
precheck = payload.get("precheck") or {}
precheck_sources = precheck.get("sources") or {}
top_sources = payload.get("sources") or {}


def cell(value):
    if value is None:
        return ""
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


rows = []
source_names = sorted(set(top_sources) | set(refresh_sources) | set(precheck_sources) | set(refresh_runs_by_source))
for name in source_names:
    s = top_sources.get(name) or {}
    r = refresh_sources.get(name) or {}
    r_run = refresh_runs_by_source.get(name) or {}
    p = precheck_sources.get(name) or {}
    action = s.get("next_action") or r.get("action") or p.get("action") or ""
    status = s.get("status") or r.get("status") or r_run.get("status") or p.get("status") or ""
    freshness = s.get("freshness_status")
    if freshness and freshness != status:
        status = f"{status}/{freshness}" if status else freshness
    latest = (
        s.get("latest_promoted_as_of")
        or s.get("official_issue_as_of")
        or p.get("latest_date")
        or r.get("latest_date")
        or r.get("promoted_latest_date")
        or r_run.get("latest_promoted_as_of")
        or ""
    )
    detail = (
        s.get("latest_attempt_error_message")
        or s.get("error_message")
        or r.get("fallback_import_skip_reason")
        or r.get("error")
        or p.get("error")
        or r_run.get("error_message")
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
    if [ -e "$IMMUTABLE_MD" ] || ! mv "$TMP_MD" "$IMMUTABLE_MD"; then
      rc=1
    elif ! publish_copy "$IMMUTABLE_MD" "$DATED_MD" || ! publish_copy "$IMMUTABLE_MD" "$OUT_MD"; then
      rc=1
    fi
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
