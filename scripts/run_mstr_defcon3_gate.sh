#!/usr/bin/env bash
# MSTR DEFCON3 de-lever destination gate.
#
# MSTR→QQQ (current default) SWITCHES thesis (BTC → tech). This script tests
# three candidate thesis-consistent de-lever destinations for MSTR:
#
#   A. QQQ      — current default; mismatches thesis (tech, not BTC)
#   B. BTC-USD  — same-thesis de-lever (drops mNAV premium + single-name risk)
#   C. BRK.B    — quality de-risk; low correlation to BTC
#
# For each candidate, prints rolling 60d correlation vs MSTR (to screen and log).
# Decision criterion: prefer lowest MSTR correlation that still has acceptable
# liquidity for DEFCON3 execution (<0.85 threshold per routing config).
#
# Usage:
#   bash scripts/run_mstr_defcon3_gate.sh
#   bash scripts/run_mstr_defcon3_gate.sh --window 120 --since 2020-01-01
#
# Output: scripts/output/defcon3_gate_<YYYYMMDD>.json
# Requires: Python + the hermes package (run from repo root).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3}"
TODAY="$(date +%Y-%m-%d)"
WINDOW=60
SINCE="2018-01-01"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --window)   WINDOW="$2"; shift 2 ;;
    --since)    SINCE="$2";  shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

OUT_DIR="scripts/output"
mkdir -p "$OUT_DIR"
OUT_FILE="${OUT_DIR}/defcon3_gate_${TODAY}.json"

echo "=== MSTR DEFCON3 de-lever gate ==="
echo "  Window: ${WINDOW}d rolling | Since: ${SINCE} | Output: ${OUT_FILE}"
echo ""

$PYTHON - <<PYEOF
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path("src")))

import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed.  pip install yfinance")
    sys.exit(1)

SYMBOLS   = ["MSTR", "QQQ", "BTC-USD", "BRK-B"]
WINDOW    = int("$WINDOW")
SINCE     = "$SINCE"
CORR_THRESHOLD = 0.85  # from routing.defcon2.brkb_corr_threshold

print(f"Downloading price data ({SINCE} → today, symbols: {', '.join(SYMBOLS)})...")
raw = yf.download(SYMBOLS, start=SINCE, auto_adjust=True, progress=False)
if raw.empty:
    print("ERROR: no data from yfinance"); sys.exit(1)

closes = raw["Close"].dropna(how="all")
returns = closes.pct_change().dropna(how="all")

mstr_ret = returns["MSTR"].dropna()

results = {}
for dest in ["QQQ", "BTC-USD", "BRK-B"]:
    dest_ret = returns.get(dest)
    if dest_ret is None or dest_ret.dropna().empty:
        results[dest] = {"error": "no data"}
        continue
    common = mstr_ret.index.intersection(dest_ret.dropna().index)
    paired = pd.DataFrame({"MSTR": mstr_ret.loc[common], dest: dest_ret.loc[common]}).dropna()

    # Full-period correlation
    full_corr = float(paired.corr().iloc[0, 1])

    # Rolling correlation (trailing WINDOW trading days)
    roll = paired["MSTR"].rolling(WINDOW).corr(paired[dest]).dropna()
    current_corr = float(roll.iloc[-1]) if not roll.empty else float("nan")
    med_corr = float(roll.median()) if not roll.empty else float("nan")

    # Fraction of time correlation exceeds threshold (crowded-exit risk)
    high_corr_frac = float((roll > CORR_THRESHOLD).mean()) if not roll.empty else float("nan")

    # Max drawdown of destination (proxy for "how bad can it get in a DEFCON3 event")
    cum = (1 + paired[dest]).cumprod()
    peak = cum.cummax()
    dd = ((cum - peak) / peak)
    max_dd = float(dd.min())

    results[dest] = {
        "full_period_corr_vs_MSTR":   round(full_corr, 4),
        "current_rolling_corr":        round(current_corr, 4),
        "median_rolling_corr":         round(med_corr, 4),
        "pct_time_above_threshold":    round(high_corr_frac * 100, 1),
        "max_drawdown":                round(max_dd * 100, 1),
        "corr_threshold":              CORR_THRESHOLD,
        "passes_corr_gate":            current_corr < CORR_THRESHOLD,
    }

# Rank by: passes gate first, then lowest current_rolling_corr
ranked = sorted(
    [(k, v) for k, v in results.items() if "error" not in v],
    key=lambda x: (int(not x[1]["passes_corr_gate"]), x[1]["current_rolling_corr"])
)

print()
print(f"{'Destination':<12} {'FullCorr':>9} {'CurrCorr':>9} {'MedCorr':>9} {'MaxDD%':>8} {'GatePASS':>9}")
print("-" * 65)
for name, r in ranked:
    tag = "✓" if r["passes_corr_gate"] else "✗"
    print(f"  {name:<10} {r['full_period_corr_vs_MSTR']:>9.3f} {r['current_rolling_corr']:>9.3f} "
          f"{r['median_rolling_corr']:>9.3f} {r['max_drawdown']:>8.1f} {tag:>9}")

best = ranked[0][0] if ranked else "QQQ"
print()
print(f"RECOMMENDATION: MSTR DEFCON3 → {best}")
if best == "QQQ":
    print("  (Same as current default — no change needed.)")
else:
    print(f"  To apply: set routing.defcon3.MSTR = '{best}' in config.json")
    print("  IMPORTANT: run walk-forward + PBO gate before deploying to live.")

output = {
    "run_date": "$TODAY",
    "window_days": WINDOW,
    "since": SINCE,
    "corr_threshold": CORR_THRESHOLD,
    "results": results,
    "ranked": [r[0] for r in ranked],
    "recommendation": best,
}
Path("$OUT_FILE").write_text(json.dumps(output, indent=2))
print(f"\nFull results written to: $OUT_FILE")
PYEOF
