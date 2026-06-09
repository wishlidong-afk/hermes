"""New deployed baseline after the F5/F6 + F3 + F4 flag flip.

Uses the COMMITTED config (so it's not contaminated by uncommitted working-tree
experiments), but forces defcon3 MSTR routing back to the prior 'QQQ' so this
baseline isolates the flag effect (the MSTR->BTC-USD routing change is a separate,
un-backtested experiment). Writes metrics to building/reports/flag_sweep/.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from hermes_escape_top.core.backtest.run_full import run_full_backtest

OUT = Path("building/reports/flag_sweep/deployed_baseline.json")
COMMIT = "ae59d7d"


def main() -> None:
    raw = subprocess.check_output(["git", "show", f"{COMMIT}:src/hermes_escape_top/config/config.json"])
    cfg = json.loads(raw)
    # Isolate the flag effect: keep the prior deployed routing (QQQ), not the
    # in-flight BTC-USD experiment.
    cfg.setdefault("routing", {}).setdefault("defcon3", {})["MSTR"] = "QQQ"
    flags = {k: cfg["features"][k] for k in (
        "use_scored_missing_weight", "use_suspect_valve_guard", "use_partial_factor_eval")}
    print(f"deployed baseline: flags={flags} defcon3.MSTR={cfg['routing']['defcon3']['MSTR']}")
    t = time.time()
    r = run_full_backtest(cfg=cfg)
    dt = time.time() - t
    sim = r.simulation if isinstance(r.simulation, dict) else {}
    m = sim.get("metrics", {})
    out = {
        "label": "deployed_baseline (F5/F6+F3+F4 on, QQQ routing)",
        "manifest_id": r.data_manifest_id,
        "n_days": len(r.dates),
        "runtime_sec": round(dt, 1),
        "metrics": {k: m.get(k) for k in ("cagr", "max_drawdown", "sharpe", "sortino", "final_value")},
        "benchmarks": {k: v for k, v in (r.benchmarks or {}).items() if not k.endswith("_metrics")},
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"done in {dt/60:.1f}min -> {OUT}")
    print(json.dumps(out["metrics"], indent=2, default=str))


if __name__ == "__main__":
    main()
