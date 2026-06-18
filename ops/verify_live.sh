#!/bin/bash
# Post-deploy END-TO-END gate: run the REAL daily entry (run_daily.sh -> run_daily.py
# -> python -m package) and assert the EFFECTS actually landed — not just that the
# package imports or unit tests pass. Catches the class of bug that unit tests +
# predeploy_smoke miss: a broken/stale real entry (the B incident: the daily ran
# 4-day-stale orchestration; manifest never re-froze, NEXT-5 never refreshed). Run
# after a deploy, or standalone. It must never create a second scheduled run,
# official receipt, or state commit. Exit non-zero on any failed assertion.
set -uo pipefail

BASE="$HOME/.hermes/skills/investment/escape-top"
PKG="$BASE/hermes_escape_top"
AUDIT="$PKG/data/archive/audit_log.jsonl"
LOG="$HOME/.hermes/logs/daily/daily_$(date +%F).log"

echo "== verify_live: running the REAL daily entry in non-official mode =="
MARK=$(wc -l < "$LOG" 2>/dev/null || echo 0)
BEFORE_AUDIT=$(wc -l < "$AUDIT" 2>/dev/null || echo 0)
bash "$HOME/.hermes/bin/run_daily.sh" --deploy-verify; rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: run_daily.sh exited $rc"; exit 1; }

fail=0

# 1. A deploy check must append a manual preview, never a second official run.
/usr/bin/python3 - "$AUDIT" "$BEFORE_AUDIT" <<'PY' || fail=1
import datetime
import json
import sys

path, before = sys.argv[1], int(sys.argv[2])
lines = [line for line in open(path, encoding="utf-8") if line.strip()]
assert len(lines) > before, "deploy verification did not append an audit record"
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
  if tail -n +$((MARK + 1)) "$LOG" | grep -qE "$step"; then
    echo "  ok: ran $step"
  else
    echo "  FAIL: real run is missing step: $step"; fail=1
  fi
done
if tail -n +$((MARK + 1)) "$LOG" | grep -qE "\[receipt\]|state committed"; then
  echo "  FAIL: deploy verification wrote official receipt/state"; fail=1
else
  echo "  ok: official receipt/state untouched"
fi

if [ "$fail" -eq 0 ]; then
  echo "== verify_live PASS =="; exit 0
else
  echo "== verify_live FAIL — the real entry did not produce the expected effects =="; exit 2
fi
