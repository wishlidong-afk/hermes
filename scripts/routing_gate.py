"""Legacy walk-forward diagnostics for routing-variant candidates.

Reads equity curves from building/reports/routing_gate/ and applies the same
13-fold fixed-variant OOS ranks, DSR, and MaxDD diagnostics. This script cannot
authorize routing changes until the formal IS-selection/OOS-PBO gate replaces it.

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
from hermes_escape_top.core.backtest.gate_policy import LEGACY_RATE_LABEL, assess_legacy_gate
from hermes_escape_top.core.backtest.validation import walk_forward_splits, deflated_sharpe
from hermes_escape_top.scripts.calibrate_next3_v2 import (
    objective_from_metrics,
    rank_percentile,
    pbo_from_rank_percentiles as oos_bottom_half_rate,
)

DIR = Path("building/reports/routing_gate")
BASELINE = "baseline"
DEFAULT_CANDIDATES = ["mstr_btc", "mstr_brkb", "defcon1_gld", "combo"]
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


def main(argv: List[str] | None = None) -> None:
    requested = list(sys.argv[1:] if argv is None else argv)
    candidates = requested or DEFAULT_CANDIDATES
    variants = [BASELINE] + candidates
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
    lines.append("# Legacy Routing-Gate Diagnostic — Authorization Frozen\n")
    lines.append(f"Folds: {len(folds)}  ·  baseline = `{BASELINE}`\n")
    lines.append("> **EVIDENCE STATUS: UNVERIFIED.** Routing equity artifacts do not carry v3 provenance metadata.\n")
    lines.append(
        "> **AUTHORIZATION: FROZEN.** Fixed-variant OOS ranks and DSR are diagnostics only; "
        "formal per-fold IS selection and OOS PBO are required before any routing change.\n"
    )
    lines.append(
        f"| variant | full CAGR | full MaxDD | Sharpe | Calmar | median OOS obj | Δ vs base | "
        f"{LEGACY_RATE_LABEL} | DSR (diagnostic) | legacy checks | authorization |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
    base_med = float(np.nanmedian(oos_obj[BASELINE]))
    base_dd = abs(float(full[BASELINE].get("max_drawdown") or 0.0))

    for v in variants:
        m = full[v]
        cagr = float(m.get("cagr") or 0.0)
        dd = abs(float(m.get("max_drawdown") or 0.0))
        sharpe = float(m.get("sharpe") or 0.0)
        calmar = float(m.get("calmar") or 0.0)
        med = float(np.nanmedian(oos_obj[v]))
        bottom_half_rate = oos_bottom_half_rate(oos_rank[v])
        rets = equities[v].pct_change().dropna().values
        dsr = deflated_sharpe(rets, n_trials=len(variants), skew=0.0, kurt=3.0)
        if v == BASELINE:
            legacy_checks = "—"
            authorization = "—"
            delta = ""
        else:
            beats = med > base_med
            dd_ok = dd <= base_dd + MAXDD_TOLERANCE
            assessment = assess_legacy_gate(
                beats_baseline=beats,
                bottom_half_rate=bottom_half_rate,
                drawdown_ok=dd_ok,
                evidence_status="UNVERIFIED",
            )
            legacy_checks = assessment["legacy_checks"]
            authorization = f"⛔ {assessment['authorization']} ({assessment['reason']})"
            delta = f"{med - base_med:+.3f}"
        lines.append(
            f"| {v} | {cagr:.2%} | {-dd:.2%} | {sharpe:.3f} | {calmar:.3f} | {med:.3f} | "
            f"{delta} | {bottom_half_rate:.2f} | {dsr:.3f} | {legacy_checks} | {authorization} |"
        )

    report = "\n".join(lines) + "\n"
    out_path = DIR / "ROUTING_GATE_REPORT.md"
    out_path.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
