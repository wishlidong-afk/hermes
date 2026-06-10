#!/usr/bin/env bash
# CNN-isolated backtest: baseline (current config) vs cnn_fgi (current + CNN on),
# each in its own process. Re-runs baseline so the comparison is clean against the
# current deployed flags (use_scored_missing_weight / use_suspect_valve_guard on).
set -u
cd "$(dirname "$0")/.."
VENV=/Users/liweishi/.hermes-v3/.venv/bin/python
export PYTHONPATH=src
LOG=building/reports/flag_sweep/cnn.log
mkdir -p building/reports/flag_sweep
echo "cnn run start $(date)" | tee "$LOG"
for v in baseline cnn_fgi; do
  echo ">>> [$v] start $(date)" | tee -a "$LOG"
  "$VENV" scripts/backtest_flag_sweep.py "$v" >> "$LOG" 2>&1
  echo ">>> [$v] exit=$? $(date)" | tee -a "$LOG"
done
git checkout -- src/hermes_escape_top/data/ 2>/dev/null || true
echo "cnn run DONE $(date)" | tee -a "$LOG"
