"""Walk-forward / PBO gate for the flag candidates.

Reads the per-variant daily equity curves produced by backtest_flag_sweep.py and,
for each walk-forward OOS fold, ranks every candidate's fold objective among the
set (reusing calibrate_next3_v2's objective + rank + PBO primitives). A candidate
"passes" if it beats baseline on the median OOS objective AND its PBO < 0.5 (i.e.
it ranks in the better half on a majority of OOS folds) AND its full-window MaxDD
is not materially worse than baseline (this is a drawdown-defense system).

Usage: PYTHONPATH=src python3 scripts/flag_gate.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from hermes_escape_top.core.backtest.metrics import equity_metrics
from hermes_escape_top.core.backtest.validation import walk_forward_splits, deflated_sharpe
from hermes_escape_top.scripts.calibrate_next3_v2 import (
    objective_from_metrics,
    rank_percentile,
    pbo_from_rank_percentiles,
)

DIR = Path("building/reports/flag_sweep")
BASELINE = "baseline"
CANDIDATES = ["scored_missing_weight", "hysteresis_only", "decision_stabilizer"]
MAXDD_TOLERANCE = 0.01  # allow ≤1pp worse MaxDD before failing the defense gate


def load_equity(variant: str) -> pd.Series:
    data = json.loads((DIR / f"{variant}_equity.json").read_text())
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
    variants = [v for v in variants if v in equities]
    dates = list(equities[BASELINE].index)
    folds = walk_forward_splits([d.isoformat() for d in dates])

    full = {v: equity_metrics(equities[v]).to_dict() for v in variants}
    oos_obj: Dict[str, List[float]] = {v: [] for v in variants}
    oos_rank: Dict[str, List[float]] = {v: [] for v in variants}

    for split in folds:
        test_idx = np.asarray(split.test_idx)
        objs = [fold_objective(equities[v], test_idx) for v in variants]
        for i, v in enumerate(variants):
            oos_obj[v].append(objs[i])
            oos_rank[v].append(rank_percentile(objs, i))

    lines: List[str] = []
    lines.append("# Flag Gate — Walk-Forward OOS / PBO\n")
    lines.append(f"Folds: {len(folds)} · baseline = `{BASELINE}`\n")
    lines.append("| variant | full CAGR | full MaxDD | median OOS obj | Δ vs base | PBO (OOS) | DSR | gate |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
    base_med = float(np.nanmedian(oos_obj[BASELINE]))
    base_dd = abs(float(full[BASELINE].get("max_drawdown") or 0.0))
    for v in variants:
        med = float(np.nanmedian(oos_obj[v]))
        pbo = pbo_from_rank_percentiles(oos_rank[v])
        rets = equities[v].pct_change().dropna().values
        dsr = deflated_sharpe(rets, n_trials=len(variants), skew=0.0, kurt=3.0)
        dd = abs(float(full[v].get("max_drawdown") or 0.0))
        if v == BASELINE:
            gate = "—"
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
                gate += f" (MaxDD +{(dd-base_dd)*100:.1f}pp)"
        d = "" if v == BASELINE else f"{med-base_med:+.3f}"
        lines.append(
            f"| {v} | {full[v].get('cagr',0):.2%} | {-dd:.2%} | {med:.3f} | {d} | {pbo:.2f} | {dsr:.3f} | {gate} |"
        )

    report = "\n".join(lines) + "\n"
    (DIR / "GATE_REPORT.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
