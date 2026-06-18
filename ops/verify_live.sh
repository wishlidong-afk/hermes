#!/bin/bash
# Post-deploy END-TO-END gate: run the REAL daily entry (run_daily.sh -> run_daily.py
# -> python -m package) and assert the EFFECTS actually landed — not just that the
# package imports or unit tests pass. Catches the class of bug that unit tests +
# predeploy_smoke miss: a broken/stale real entry (the B incident: the daily ran
# 4-day-stale orchestration; manifest never re-froze, NEXT-5 never refreshed). Run
# after a deploy, or standalone. Exit non-zero on any failed assertion.
set -uo pipefail

BASE="$HOME/.hermes/skills/investment/escape-top"
PKG="$BASE/hermes_escape_top"
RECEIPT="$PKG/data/archive/run_receipt.json"
LOG="$HOME/.hermes/logs/daily/daily_$(date +%F).log"

echo "== verify_live: running the REAL daily entry (run_daily.sh) =="
MARK=$(wc -l < "$LOG" 2>/dev/null || echo 0)
bash "$HOME/.hermes/bin/run_daily.sh"; rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: run_daily.sh exited $rc"; exit 1; }

fail=0

# 1. the run receipt is fresh (written just now) and self-checked green.
#    receipt.ok already asserts the key effects: as_of == latest bar, manifest == OK.
/usr/bin/python3 - "$RECEIPT" <<'PY' || fail=1
import json, sys, datetime
r = json.load(open(sys.argv[1]))
age = (datetime.datetime.now().astimezone()
       - datetime.datetime.fromisoformat(r["run_at"])).total_seconds()
assert age < 600, f"receipt stale: {age:.0f}s old (real entry didn't write it?)"
assert r.get("ok") is True, f"receipt self-check FAILED: {r.get('checks')}"
print(f"  ok: receipt fresh ({age:.0f}s) as_of={r['as_of']} checks_ok={r['ok']}")
PY

# 2. the maintenance steps actually executed (effects visible in this run's log) —
#    a stale/half engine would be missing these even on exit 0.
for step in "score_pipeline OK" "\[manifest\]" "\[NEXT5\]" "\[receipt\]"; do
  if tail -n +$((MARK + 1)) "$LOG" | grep -qE "$step"; then
    echo "  ok: ran $step"
  else
    echo "  FAIL: real run is missing step: $step"; fail=1
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "== verify_live PASS =="; exit 0
else
  echo "== verify_live FAIL — the real entry did not produce the expected effects =="; exit 2
fi
