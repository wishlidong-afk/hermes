#!/usr/bin/env bash
# Run the full-window backtest for each flag variant in its OWN process
# (running several full backtests in one process OOM-kills). Sequential.
set -u
cd "$(dirname "$0")/.."
VENV=/Users/liweishi/.hermes-v3/.venv/bin/python
export PYTHONPATH=src
LOG_DIR=building/reports/flag_sweep
mkdir -p "$LOG_DIR"
VARIANTS=(baseline scored_missing_weight partial_factor_eval decision_stabilizer suspect_valve_guard f8_tightened all_on)

echo "flag-sweep start $(date)" | tee "$LOG_DIR/sweep.log"
for v in "${VARIANTS[@]}"; do
  echo ">>> [$v] start $(date)" | tee -a "$LOG_DIR/sweep.log"
  "$VENV" scripts/backtest_flag_sweep.py "$v" >> "$LOG_DIR/sweep.log" 2>&1
  rc=$?
  echo ">>> [$v] exit=$rc $(date)" | tee -a "$LOG_DIR/sweep.log"
done

# Discard any data-file churn from replay (manifest/state side effects); keep reports.
git checkout -- src/hermes_escape_top/data/ 2>/dev/null || true
echo "flag-sweep DONE $(date)" | tee -a "$LOG_DIR/sweep.log"
