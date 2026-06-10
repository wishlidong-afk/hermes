"""Walk-forward / PBO gate for routing-variant candidates.

Reads equity curves from building/reports/routing_gate/ and applies the same
13-fold walk-forward + PBO + DSR + MaxDD gate as flag_gate.py.

Usage:
    cd /path/to/hermes
    PYTHONPATH=src python3 scripts/routing_gate.py                   # all candidates
    PYTHONPATH=src python3 scripts/routing_gate.py combo mstr_btc    # specific candidates
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from hermes_escape_top.core.backtest.metrics import equity_metrics, compute_metrics
from hermes_escape_top.core.backtest.validation import walk_forward_splits, deflated_sharpe
from hermes_escape_top.scripts.calibrate_next3_v2 import (
    objective_from_metrics,
    rank_percentile,
    pbo_from_rank_percentiles,
)

DIR = Path("building/reports/routing_gate")
BASELINE = "baseline"
CANDIDATES = sys.argv[1:] or ["mstr_btc", "mstr_brkb", "defcon1_gld", "combo"]
MAXDD_TOLERANCE = 0.01


def load_equity(variant: str) -> pd.Series:
    path = DIR / f"{variant}_equity.json"
    data = json.loads(path.read_text())
    s = pd.Series({pd.Timestamp(k): float(v) for k, v in data.items()}).sort_index()
    return s


def fold_objective(equity: pd.Series, idx: np.ndarray) -> float:
    sl = equity.iloc[idx]
    if len(sl) < 3:
        return float("nan")
    return objective_from_metrics(equity_metrics(sl).to_dict())


def main() -> None:
    variants = [BASELINE] + CANDIDATES
    equities = {v: load_equity(v) for v in variants if (DIR / f"{v}_equity.json").exists()}
    missing = [v for v in variants if v not in equities]
    if missing:
        print(f"WARNING: missing equity files for: {missing} — skipping")
    variants = [v for v in variants if v in equities]
    if len(variants) < 2:
        raise SystemExit("Need at least baseline + 1 candidate to gate.")

    dates = list(equities[BASELINE].index)
    folds = walk_forward_splits([d.isoformat() for d in dates])

    full = {v: compute_metrics(equities[v]) for v in variants}
    oos_obj: Dict[str, List[float]] = {v: [] for v in variants}
    oos_rank: Dict[str, List[float]] = {v: [] for v in variants}

    for split in folds:
        test_idx = np.asarray(split.test_idx)
        objs = [fold_objective(equities[v], test_idx) for v in variants]
        for i, v in enumerate(variants):
            oos_obj[v].append(objs[i])
            oos_rank[v].append(rank_percentile(objs, i))

    lines: List[str] = []
    lines.append("# Routing Gate — Walk-Forward OOS / PBO\n")
    lines.append(f"Folds: {len(folds)}  ·  baseline = `{BASELINE}`\n")
    lines.append("| variant | full CAGR | full MaxDD | Sharpe | Calmar | median OOS obj | Δ vs base | PBO (OOS) | DSR | gate |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    base_med = float(np.nanmedian(oos_obj[BASELINE]))
    base_dd = abs(float(full[BASELINE].get("max_drawdown") or 0.0))

    for v in variants:
        m = full[v]
        cagr = float(m.get("cagr") or 0.0)
        dd = abs(float(m.get("max_drawdown") or 0.0))
        sharpe = float(m.get("sharpe") or 0.0)
        calmar = float(m.get("calmar") or 0.0)
        med = float(np.nanmedian(oos_obj[v]))
        pbo = pbo_from_rank_percentiles(oos_rank[v])
        rets = equities[v].pct_change().dropna().values
        dsr = deflated_sharpe(rets, n_trials=len(variants), skew=0.0, kurt=3.0)
        if v == BASELINE:
            gate = "—"
            delta = ""
        else:
            beats = med > base_med
            pbo_ok = pbo < 0.5
            dd_ok = dd <= base_dd + MAXDD_TOLERANCE
            gate = "✅ PASS" if (beats and pbo_ok and dd_ok) else "❌ FAIL"
            if not beats:
                gate += " (OOS≤base)"
            if not pbo_ok:
                gate += " (PBO≥.5)"
            if not dd_ok:
                gate += f" (MaxDD +{(dd - base_dd)*100:.1f}pp)"
            delta = f"{med - base_med:+.3f}"
        lines.append(
            f"| {v} | {cagr:.2%} | {-dd:.2%} | {sharpe:.3f} | {calmar:.3f} | {med:.3f} | {delta} | {pbo:.2f} | {dsr:.3f} | {gate} |"
        )

    report = "\n".join(lines) + "\n"
    out_path = DIR / "ROUTING_GATE_REPORT.md"
    out_path.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
