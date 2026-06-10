#!/usr/bin/env bash
# Run baseline + cot_nq backtests in parallel, then gate.
#
# Prerequisites:
#   1. cot_nq.csv must exist (run: PYTHONPATH=src python3 -m hermes_escape_top.scripts.backfill_cot)
#   2. Each backtest takes ~40 min; total wall time ~40 min (parallel)
#
# Usage: cd /path/to/hermes && bash scripts/run_cot_gate.sh
# Gate:  PYTHONPATH=src python3 scripts/flag_gate.py cot_nq

set -e
cd "$(dirname "$0")/.."
VENV=/Users/liweishi/.hermes-v3/.venv/bin/python
OUTDIR=building/reports/flag_sweep
mkdir -p "$OUTDIR"

for VARIANT in baseline cot_nq; do
    LOG="$OUTDIR/${VARIANT}_cot_run.log"
    echo "Launching $VARIANT → $LOG"
    nohup bash -c "
        cd $(pwd)
        PYTHONPATH=src $VENV scripts/backtest_flag_sweep.py $VARIANT > $LOG 2>&1
        echo \"[$VARIANT] finished\" >> $LOG
    " </dev/null &
    disown
    sleep 2
done

echo ""
echo "Both variants launched. Monitor with:"
echo "  tail -f $OUTDIR/baseline_cot_run.log $OUTDIR/cot_nq_cot_run.log"
echo ""
echo "When both end with 'finished', run the gate:"
echo "  cd $(pwd) && PYTHONPATH=src $VENV scripts/flag_gate.py cot_nq"
