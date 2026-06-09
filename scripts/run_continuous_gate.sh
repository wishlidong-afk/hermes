#!/usr/bin/env bash
# Walk-forward/PBO gate for sell_fraction_mode="continuous" vs the deployed
# baseline (current config = 3 flags on, QQQ routing). Each run in its own
# process (OOM if shared), then aggregate. ~76min.
set -u
cd "$(dirname "$0")/.."
VENV=/Users/liweishi/.hermes-v3/.venv/bin/python
export PYTHONPATH=src
LOG=building/reports/flag_sweep/continuous_gate.log
mkdir -p building/reports/flag_sweep
echo "continuous-gate start $(date)" | tee "$LOG"
for v in baseline continuous_sell_fraction; do
  echo ">>> [$v] start $(date)" | tee -a "$LOG"
  "$VENV" scripts/backtest_flag_sweep.py "$v" >> "$LOG" 2>&1
  echo ">>> [$v] exit=$? $(date)" | tee -a "$LOG"
done
git checkout -- src/hermes_escape_top/data/ 2>/dev/null || true
echo ">>> aggregating" | tee -a "$LOG"
"$VENV" scripts/flag_gate.py continuous_sell_fraction >> "$LOG" 2>&1
echo "continuous-gate DONE $(date)" | tee -a "$LOG"
