#!/bin/bash
# M4-2 Shadow parallel runner.
# Runs BOTH the production monolith AND the package engine each day,
# writes monolith to data/ (production unchanged) and package to data/shadow/.
# Diffs the status/sell_pct/hard_ids to build the M4-2 shadow acceptance log.
#
# After N days of clean shadow (hard_ids 100%, status diff within expected range),
# you flip run_daily.py (M4-3 human gate).
#
# Usage: bash scripts/run_daily_shadow_compare.sh [--as-of YYYY-MM-DD]

set -e
P="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$(dirname "$P")/../../../.hermes/hermes-agent/venv"
PYTHON="$VENV/bin/python3"
AS_OF="${2:-$(date +%Y-%m-%d)}"

if [ "$1" = "--as-of" ] && [ -n "$2" ]; then
    AS_OF="$2"
fi

echo "══════════════════════════════════════"
echo " M4-2 Shadow Parallel — $AS_OF"
echo "══════════════════════════════════════"

echo ""
echo "── Step 1: Production monolith run ──"
cd "$P"
$PYTHON scripts/run_daily.py 2>&1 | tail -5

echo ""
echo "── Step 2: Package engine shadow run ──"
$PYTHON scripts/run_daily_package.py --as-of "$AS_OF" --skip-refresh 2>&1 | grep -v "API connection\|Make sure API"

echo ""
echo "── Step 3: Shadow diff ──"
$PYTHON - <<PYEOF
import json, os
P = "$P"
as_of = "$AS_OF"

mono_path = os.path.join(P, "data", f"daily_score_precheck_{as_of}.json")
pkg_path  = os.path.join(P, "data", "shadow", f"daily_score_precheck_{as_of}.json")

if not os.path.exists(mono_path):
    print(f"  Monolith precheck not found: {mono_path}")
    exit(0)
if not os.path.exists(pkg_path):
    print(f"  Package shadow not found: {pkg_path}")
    exit(0)

mono = json.load(open(mono_path))
pkg  = json.load(open(pkg_path))
SYMS = ["MSTR", "FNGU", "SOXL"]

fields = ["status", "sell_pct", "hard_ids"]
matches, total = 0, 0
diffs = []
for sym in SYMS:
    mr = mono.get("results", {}).get(sym, {})
    pr = pkg.get("results", {}).get(sym, {})
    mht = mr.get("hard_trigger", {}) or {}
    pht = pr.get("hard_trigger", {}) or {}
    mv = {"status": mr.get("status"), "sell_pct": mr.get("sell_pct"),
          "hard_ids": sorted(mht.get("ids", []))}
    pv = {"status": pr.get("status"), "sell_pct": pr.get("sell_pct"),
          "hard_ids": sorted(pht.get("ids", []))}
    for f in fields:
        total += 1
        if mv[f] == pv[f]:
            matches += 1
        else:
            diffs.append(f"  {sym}.{f}: mono={mv[f]} pkg={pv[f]}")

rate = matches / total * 100 if total else 0
print(f"  Match rate: {rate:.1f}% ({matches}/{total})")
if diffs:
    print("  Divergences:")
    for d in diffs: print(d)
else:
    print("  ✅ All fields match.")

# Append to shadow log
log_path = os.path.join(P, "reports", "shadow", "M4_shadow_log.jsonl")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
import datetime
entry = {"date": as_of, "match_rate": round(rate, 1), "matches": matches,
         "total": total, "divergences": diffs,
         "logged_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
with open(log_path, "a") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
print(f"  Log appended: {log_path}")
PYEOF

echo ""
echo "══ Shadow run complete ══"
