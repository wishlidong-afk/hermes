"""Run ONE capital-efficiency variant full backtest → JSON (one process each).

Running several full backtests in one process OOM-kills, so each variant is a
separate invocation. Usage:

    PYTHONPATH=src python3 scripts/capeff_backtest.py <variant> [limit]

Variants: baseline, t3_ma200, t3_shorter, cont_frac, gov, volcaps,
          gov_volcaps, mstr_btc, mstr_brkb, capeff_all
`limit` (optional) caps the number of replay days for a quick smoke.

Results land in building/reports/capeff/<variant>.json.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path

from hermes_escape_top.config import load_config
from hermes_escape_top.core.backtest.run_full import run_full_backtest

OUT_DIR = Path("building/reports/capeff")


def build_config(variant: str) -> dict:
    cfg = copy.deepcopy(load_config())
    sizing = cfg.setdefault("sizing", {})
    reentry = cfg.setdefault("reentry", {})
    if variant == "baseline":
        pass
    elif variant == "t3_ma200":
        reentry["t3_gate_mode"] = "ma200_reclaim"
    elif variant == "t3_shorter":
        reentry["t3_gate_mode"] = "shorter_high"
    elif variant == "cont_frac":
        cfg["sell_fraction_mode"] = "continuous"
    elif variant == "gov":
        sizing["vol_gross_floor"] = 0.5
    elif variant == "volcaps":
        sizing["vol_weighted_caps"] = True
    elif variant == "gov_volcaps":
        sizing["vol_gross_floor"] = 0.5
        sizing["vol_weighted_caps"] = True
    elif variant == "mstr_btc":
        cfg["routing"]["defcon3"]["MSTR"] = "BTC-USD"
    elif variant == "mstr_brkb":
        cfg["routing"]["defcon3"]["MSTR"] = "BRK.B"
    elif variant == "capeff_all":
        reentry["t3_gate_mode"] = "ma200_reclaim"
        cfg["sell_fraction_mode"] = "continuous"
        sizing["vol_gross_floor"] = 0.5
        sizing["vol_weighted_caps"] = True
        cfg["routing"]["defcon3"]["MSTR"] = "BTC-USD"
    else:
        raise SystemExit(f"unknown variant: {variant}")
    return cfg


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: capeff_backtest.py <variant> [limit]")
    variant = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    cfg = build_config(variant)
    # Read histories from an immutable snapshot (set by the launcher) so the live
    # `serve`/refresh processes rewriting repo CSVs can't race the backtest reads.
    snap = os.environ.get("CAPEFF_SNAPSHOT")
    if snap:
        p = cfg.setdefault("paths", {})
        p["history_dir"] = f"{snap}/history"
        p["legacy_history_dir"] = f"{snap}/history"
        p["soft_history_dir"] = f"{snap}/soft_history"
        p["archive_dir"] = f"{snap}/archive"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t = time.time()
    report = run_full_backtest(cfg=cfg, limit=limit)
    dt = time.time() - t
    sim = report.simulation if isinstance(report.simulation, dict) else {}
    metrics = sim.get("metrics", {})
    out = {
        "variant": variant,
        "limit": limit,
        "effective_start": report.effective_start,
        "effective_end": report.effective_end,
        "n_days": len(report.dates),
        "runtime_sec": round(dt, 1),
        "metrics": {
            k: metrics.get(k)
            for k in ("cagr", "max_drawdown", "calmar", "sharpe", "sortino",
                      "sortino_ratio", "turnover", "insurance_ratio", "final_value")
        },
        "benchmarks": report.benchmarks if isinstance(getattr(report, "benchmarks", None), dict) else {},
    }
    suffix = f"_smoke{limit}" if limit else ""
    path = OUT_DIR / f"{variant}{suffix}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"[{variant}] done in {dt/60:.1f}min → {path}")
    print(json.dumps(out["metrics"], indent=2, default=str))


if __name__ == "__main__":
    main()
