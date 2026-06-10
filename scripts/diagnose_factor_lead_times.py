#!/usr/bin/env python3
"""Diagnose factor lead times against labeled historical tops.

For each factor in the score history, measures how many calendar days of
advance notice it gave before each labeled top.  Surfaces which factors are
genuinely leading vs. coincident vs. lagging.

Usage:
  python3 scripts/diagnose_factor_lead_times.py
  python3 scripts/diagnose_factor_lead_times.py --symbol MSTR
  python3 scripts/diagnose_factor_lead_times.py --lead-window 90 --top-threshold 2.0

Data source: ~/.hermes/skills/investment/escape-top/data/state.db (SQLite).
Falls back to any state.db found relative to this script.

Labeled tops: hardcoded approximate dates for MSTR / FNGU / SOXL based on
known historical cycle highs (2018-2024).  Edit LABELED_TOPS below to add
more or to adjust to your preferred top definitions.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# Add src/ to the path so this can be run from the repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hermes_escape_top.core.factors.lab import factor_lead_time_analysis

# ---------------------------------------------------------------------------
# Labeled tops (approximate dates of meaningful cycle highs for each symbol).
# These are conservative, observable-in-hindsight labels — not predictions.
# ---------------------------------------------------------------------------
LABELED_TOPS: Dict[str, List[str]] = {
    "MSTR": [
        "2018-01-08",   # BTC cycle top 1
        "2021-02-09",   # MSTR local high before correction
        "2021-11-10",   # BTC all-time high 2021
        "2024-03-14",   # BTC local ATH pre-halving 2024
        "2024-11-22",   # BTC/MSTR post-election blow-off
    ],
    "FNGU": [
        "2018-01-26",   # SPX/FANG top pre-VIXplosion
        "2021-02-12",   # FANG/QQQ local top
        "2021-11-22",   # FANG top (Nasdaq peaked late 2021)
        "2022-01-04",   # QQQ/Nasdaq absolute top Jan 2022
        "2024-07-10",   # FANG top pre-rotation
    ],
    "SOXL": [
        "2018-03-13",   # Semis local top Q1 2018
        "2021-01-04",   # SOX/SMH local top
        "2022-01-05",   # SOX absolute top
        "2024-07-11",   # SOX top pre-AI rotation unwind
    ],
}

# ---------------------------------------------------------------------------
# DB discovery
# ---------------------------------------------------------------------------
_CANDIDATE_DBS = [
    Path.home() / ".hermes" / "skills" / "investment" / "escape-top" / "data" / "state.db",
    REPO_ROOT / "data" / "state.db",
    Path.cwd() / "data" / "state.db",
]


def _find_db() -> Optional[Path]:
    for p in _CANDIDATE_DBS:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Load factor score panel from SQLite
# ---------------------------------------------------------------------------

def load_factor_panel(db: Path, symbol: str) -> pd.DataFrame:
    """Return a date × factor_id DataFrame of raw scores for the given symbol."""
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            """
            SELECT sr.as_of, fv.factor_id, fv.score
              FROM factor_values fv
              JOIN score_runs sr ON sr.id = fv.score_run_id
             WHERE fv.symbol = ?
               AND fv.factor_id IS NOT NULL
               AND fv.score IS NOT NULL
             ORDER BY sr.as_of
            """,
            (symbol,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["date", "factor_id", "score"])
    df["date"] = pd.to_datetime(df["date"])
    pivoted = df.pivot_table(index="date", columns="factor_id", values="score", aggfunc="last")
    return pivoted.sort_index()


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_analysis(
    db: Path,
    symbol: str,
    lead_window: int,
    top_threshold: float,
    min_fire_days: int,
) -> Dict[str, Any]:
    tops = LABELED_TOPS.get(symbol, [])
    if not tops:
        return {"error": f"no labeled tops for symbol {symbol}"}

    panel = load_factor_panel(db, symbol)
    if panel.empty:
        return {"error": f"no factor history in {db} for {symbol}"}

    results = []
    for factor_id in panel.columns:
        series = panel[factor_id].dropna()
        if len(series) < min_fire_days:
            continue
        analysis = factor_lead_time_analysis(
            factor_series=series,
            labeled_tops=tops,
            lead_window=lead_window,
            fire_threshold=top_threshold,
        )
        results.append({
            "factor_id": factor_id,
            "median_lead_days": analysis["median_lead_days"],
            "mean_lead_days": analysis["mean_lead_days"],
            "min_lead_days": analysis["min_lead_days"],
            "max_lead_days": analysis["max_lead_days"],
            "hit_rate": analysis["hit_rate"],
            "hits": analysis["hits"],
            "total_tops": analysis["total_tops"],
            "factor_fire_rate": analysis["factor_fire_rate"],
            "lead_times_days": analysis["lead_times_days"],
        })

    results.sort(key=lambda r: -(r["median_lead_days"] or -999))
    return {
        "symbol": symbol,
        "db": str(db),
        "labeled_tops": tops,
        "lead_window_days": lead_window,
        "fire_threshold": top_threshold,
        "n_factors": len(results),
        "factors": results,
    }


def _print_summary(out: Dict[str, Any]) -> None:
    if "error" in out:
        print(f"ERROR: {out['error']}")
        return
    print(f"\n=== Factor Lead-Time Analysis: {out['symbol']} ===")
    print(f"DB: {out['db']}")
    print(f"Labeled tops ({len(out['labeled_tops'])}): {', '.join(out['labeled_tops'])}")
    print(f"Lead window: {out['lead_window_days']} days  |  Fire threshold: {out['fire_threshold']}")
    print()
    print(f"{'Factor':<32} {'Median':>7} {'Mean':>7} {'Hit%':>6} {'FireRate':>9}")
    print("-" * 70)
    for r in out["factors"]:
        med = f"{r['median_lead_days']:.0f}d" if r["median_lead_days"] is not None else "—"
        mean = f"{r['mean_lead_days']:.0f}d" if r["mean_lead_days"] is not None else "—"
        hit = f"{r['hit_rate']*100:.0f}%"
        fr = f"{r['factor_fire_rate']*100:.0f}%"
        print(f"  {r['factor_id']:<30} {med:>7} {mean:>7} {hit:>6} {fr:>9}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Factor lead-time vs. labeled tops")
    parser.add_argument("--symbol", default=None, help="MSTR, FNGU, SOXL, or omit for all")
    parser.add_argument("--db", default=None, help="Path to state.db (auto-discovered if omitted)")
    parser.add_argument("--lead-window", type=int, default=60, help="Days to look back for factor fire (default: 60)")
    parser.add_argument("--top-threshold", type=float, default=0.0,
                        help="Min factor value to count as 'fired' (default: 0.0 = any positive)")
    parser.add_argument("--min-fire-days", type=int, default=30,
                        help="Min days a factor must have data to be included (default: 30)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of table")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else _find_db()
    if db_path is None or not db_path.exists():
        print("ERROR: state.db not found. Run run_daily_package.py at least once to create it.")
        return 1

    symbols = [args.symbol] if args.symbol else list(LABELED_TOPS.keys())
    all_results = {}
    for sym in symbols:
        out = run_analysis(db_path, sym, args.lead_window, args.top_threshold, args.min_fire_days)
        all_results[sym] = out
        if not args.json:
            _print_summary(out)

    if args.json:
        print(json.dumps(all_results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
