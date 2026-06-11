#!/usr/bin/env bash
# Walk-forward / PBO gate: re-run the gate candidates (with equity-curve dump)
# in their own processes, then aggregate. F3 excluded — it is a verified no-op
# on clean history (0 suspect bars after the bad-tick fix). F8 already rejected.
set -u
cd "$(dirname "$0")/.."
VENV=/Users/liweishi/.hermes-v3/.venv/bin/python
export PYTHONPATH=src
LOG=building/reports/flag_sweep/gate.log
mkdir -p building/reports/flag_sweep
echo "gate start $(date)" | tee "$LOG"
for v in baseline scored_missing_weight hysteresis_only decision_stabilizer; do
  echo ">>> [$v] start $(date)" | tee -a "$LOG"
  "$VENV" scripts/backtest_flag_sweep.py "$v" --reuse-if-fresh >> "$LOG" 2>&1
  echo ">>> [$v] exit=$? $(date)" | tee -a "$LOG"
done
git checkout -- src/hermes_escape_top/data/ 2>/dev/null || true
echo ">>> aggregating (flag_gate.py)" | tee -a "$LOG"
"$VENV" scripts/flag_gate.py >> "$LOG" 2>&1
echo "gate DONE $(date)" | tee -a "$LOG"
