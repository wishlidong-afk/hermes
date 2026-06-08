"""Run ONE flag-variant full backtest and write its metrics to JSON.

Each variant runs in its own process (running several full backtests in one
process OOM-kills). Usage:

    PYTHONPATH=src python3 scripts/backtest_flag_sweep.py <variant>

Variants: baseline, scored_missing_weight, partial_factor_eval,
decision_stabilizer, suspect_valve_guard, f8_tightened, all_on.

Results land in building/reports/flag_sweep/<variant>.json.
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

from hermes_escape_top.config import load_config
from hermes_escape_top.core.backtest.run_full import run_full_backtest

OUT_DIR = Path("building/reports/flag_sweep")

# Recommended F8 euphoria-tail tightening (the documented backtest-gated flip).
F8_NAAIM = {"score2_exposure": 90, "score2_pctl": 90, "score1_exposure": 80, "score1_pctl": 85}
F8_PCR = {"score2_pcr": 0.52, "score2_pctl": 8, "score1_pcr": 0.58, "score1_pctl": 12}


def build_config(variant: str) -> dict:
    cfg = copy.deepcopy(load_config())
    feats = cfg.setdefault("features", {})
    if variant == "baseline":
        pass
    elif variant == "scored_missing_weight":
        feats["use_scored_missing_weight"] = True
    elif variant == "partial_factor_eval":
        feats["use_partial_factor_eval"] = True
    elif variant == "decision_stabilizer":
        feats["use_decision_stabilizer"] = True
    elif variant == "hysteresis_only":
        feats["use_status_hysteresis"] = True
    elif variant == "confirmation_only":
        feats["use_close_confirmation"] = True
    elif variant == "suspect_valve_guard":
        feats["use_suspect_valve_guard"] = True
    elif variant == "f8_tightened":
        cfg["naaim"] = F8_NAAIM
        cfg["pcr"] = F8_PCR
    elif variant == "all_on":
        for f in (
            "use_scored_missing_weight",
            "use_partial_factor_eval",
            "use_decision_stabilizer",
            "use_suspect_valve_guard",
        ):
            feats[f] = True
        cfg["naaim"] = F8_NAAIM
        cfg["pcr"] = F8_PCR
    else:
        raise SystemExit(f"unknown variant: {variant}")
    return cfg


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: backtest_flag_sweep.py <variant>")
    variant = sys.argv[1]
    cfg = build_config(variant)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t = time.time()
    report = run_full_backtest(cfg=cfg)
    dt = time.time() - t
    sim = report.simulation if isinstance(report.simulation, dict) else {}
    metrics = sim.get("metrics", {})
    benchmarks = report.benchmarks if isinstance(getattr(report, "benchmarks", None), dict) else {}
    out = {
        "variant": variant,
        "manifest_id": report.data_manifest_id,
        "effective_start": report.effective_start,
        "effective_end": report.effective_end,
        "n_days": len(report.dates),
        "runtime_sec": round(dt, 1),
        "metrics": {
            "cagr": metrics.get("cagr"),
            "max_drawdown": metrics.get("max_drawdown"),
            "sharpe": metrics.get("sharpe"),
            "sortino": metrics.get("sortino"),
            "final_value": metrics.get("final_value"),
        },
        "benchmarks": benchmarks,
    }
    path = OUT_DIR / f"{variant}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    # Daily equity curve for fold-level walk-forward / PBO gating (separate file
    # to keep the metrics JSON small).
    equity = sim.get("equity_curve", {})
    if equity:
        (OUT_DIR / f"{variant}_equity.json").write_text(json.dumps(equity, default=str))
    print(f"[{variant}] done in {dt/60:.1f}min → {path}")
    print(json.dumps(out["metrics"], indent=2, default=str))


if __name__ == "__main__":
    main()
