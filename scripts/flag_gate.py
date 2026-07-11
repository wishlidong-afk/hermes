"""Legacy walk-forward diagnostics for flag candidates.

Reads the per-variant daily equity curves produced by backtest_flag_sweep.py and,
for each walk-forward OOS fold, ranks every candidate's fold objective among the
set. This fixed-variant OOS rank profile is not formal PBO because there is no
per-fold IS selection. It is retained as a diagnostic only; authorization stays
frozen until the formal research gate replaces it.

Usage: PYTHONPATH=src python3 scripts/flag_gate.py
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

DIR = Path("building/reports/flag_sweep")
BASELINE = "baseline"
DEFAULT_CANDIDATES = ["scored_missing_weight", "hysteresis_only", "decision_stabilizer"]
MAXDD_TOLERANCE = 0.01  # allow ≤1pp worse MaxDD before failing the defense gate

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from backtest_flag_sweep import assess_artifact_freshness, build_config  # noqa: E402


def load_equity(variant: str) -> pd.Series:
    data = json.loads((DIR / f"{variant}_equity.json").read_text())
    s = pd.Series({pd.Timestamp(k): float(v) for k, v in data.items()}).sort_index()
    return s


def fold_objective(equity: pd.Series, idx: np.ndarray) -> float:
    sl = equity.iloc[idx]
    if len(sl) < 3:
        return float("nan")
    return objective_from_metrics(equity_metrics(sl).to_dict())


def artifact_freshness(variant: str) -> dict:
    path = DIR / f"{variant}.json"
    if not path.exists():
        return {
            "variant": variant,
            "status": "STALE",
            "mismatches": ["metrics_artifact"],
            "expected": {},
            "actual": {},
        }
    try:
        cached = json.loads(path.read_text())
    except Exception:
        return {
            "variant": variant,
            "status": "STALE",
            "mismatches": ["metrics_artifact_unreadable"],
            "expected": {},
            "actual": {},
        }
    return assess_artifact_freshness(variant, cached, build_config(variant))


def main(argv: List[str] | None = None) -> None:
    requested = list(sys.argv[1:] if argv is None else argv)
    candidates = requested or DEFAULT_CANDIDATES
    variants = [BASELINE] + candidates
    equities = {v: load_equity(v) for v in variants if (DIR / f"{v}_equity.json").exists()}
    variants = [v for v in variants if v in equities]
    if BASELINE not in variants:
        raise SystemExit("Missing baseline equity artifact.")
    evidence = {v: artifact_freshness(v) for v in variants}
    stale_variants = [v for v in variants if evidence[v]["status"] != "FRESH"]
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
    lines.append("# Legacy Flag-Gate Diagnostic — Authorization Frozen\n")
    lines.append(f"Folds: {len(folds)} · baseline = `{BASELINE}`\n")
    if stale_variants:
        details = "; ".join(
            f"{v}: {','.join(evidence[v]['mismatches'])}" for v in stale_variants
        )
        lines.append(f"> **EVIDENCE STATUS: STALE.** {details}\n")
    else:
        lines.append("> **EVIDENCE STATUS: FRESH.** Artifact provenance matches the current worktree.\n")
    lines.append(
        "> **AUTHORIZATION: FROZEN.** Fixed-variant OOS ranks and DSR are diagnostics only; "
        "formal per-fold IS selection and OOS PBO are required before any flag flip.\n"
    )
    lines.append(
        f"| variant | full CAGR | full MaxDD | Sharpe | Calmar | median OOS obj | Δ vs base | "
        f"{LEGACY_RATE_LABEL} | DSR (diagnostic) | legacy checks | authorization |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
    base_med = float(np.nanmedian(oos_obj[BASELINE]))
    base_dd = abs(float(full[BASELINE].get("max_drawdown") or 0.0))
    for v in variants:
        med = float(np.nanmedian(oos_obj[v]))
        bottom_half_rate = oos_bottom_half_rate(oos_rank[v])
        rets = equities[v].pct_change().dropna().values
        dsr = deflated_sharpe(rets, n_trials=len(variants), skew=0.0, kurt=3.0)
        dd = abs(float(full[v].get("max_drawdown") or 0.0))
        if v == BASELINE:
            legacy_checks = "—"
            authorization = "—"
        else:
            beats = med > base_med
            dd_ok = dd <= base_dd + MAXDD_TOLERANCE
            status = "FRESH" if not stale_variants else "STALE"
            assessment = assess_legacy_gate(
                beats_baseline=beats,
                bottom_half_rate=bottom_half_rate,
                drawdown_ok=dd_ok,
                evidence_status=status,
            )
            legacy_checks = assessment["legacy_checks"]
            authorization = f"⛔ {assessment['authorization']} ({assessment['reason']})"
        d = "" if v == BASELINE else f"{med-base_med:+.3f}"
        sharpe = float(full[v].get("sharpe") or 0.0)
        calmar = float(full[v].get("calmar") or 0.0)
        lines.append(
            f"| {v} | {full[v].get('cagr',0):.2%} | {-dd:.2%} | {sharpe:.3f} | {calmar:.3f} | "
            f"{med:.3f} | {d} | {bottom_half_rate:.2f} | {dsr:.3f} | {legacy_checks} | {authorization} |"
        )

    report = "\n".join(lines) + "\n"
    report_name = "GATE_REPORT.md" if not requested else "GATE_REPORT_" + "_".join(requested) + ".md"
    (DIR / report_name).write_text(report)
    print(report)


if __name__ == "__main__":
    main()
