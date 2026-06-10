#!/usr/bin/env bash
# Launch routing-variant backtests in parallel, then gate.
# Each variant runs in its own process to avoid OOM.
#
# Usage: cd /path/to/hermes && bash scripts/run_routing_gate.sh
# Gate:  PYTHONPATH=src python3 scripts/routing_gate.py

set -e
cd "$(dirname "$0")/.."
VENV=/Users/liweishi/.hermes-v3/.venv/bin/python
OUTDIR=building/reports/routing_gate
mkdir -p "$OUTDIR"

for VARIANT in baseline mstr_btc mstr_brkb defcon1_gld combo; do
    LOG="$OUTDIR/${VARIANT}.log"
    echo "Launching $VARIANT → $LOG"
    nohup bash -c "
        cd $(pwd)
        PYTHONPATH=src $VENV scripts/routing_backtest.py $VARIANT > $LOG 2>&1
        echo \"[$VARIANT] finished\" >> $LOG
    " </dev/null &
    disown
    sleep 2
done

echo ""
echo "All 5 variants launched. Monitor with:"
echo "  tail -f $OUTDIR/*.log"
echo ""
echo "When all logs end with 'finished', run the gate:"
echo "  cd $(pwd) && PYTHONPATH=src $VENV scripts/routing_gate.py"
