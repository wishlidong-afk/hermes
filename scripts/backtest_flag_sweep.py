"""Run ONE flag-variant full backtest and write its metrics to JSON.

Each variant runs in its own process (running several full backtests in one
process OOM-kills). Usage:

    PYTHONPATH=src python3 scripts/backtest_flag_sweep.py <variant> [--reuse-if-fresh]

Variants: baseline, scored_missing_weight, partial_factor_eval,
decision_stabilizer, suspect_valve_guard, spine_only, mnav_b6,
f8_tightened, all_on.

Results land in building/reports/flag_sweep/<variant>.json.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.manifest import freeze_manifest
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.backtest.run_full import run_full_backtest

OUT_DIR = Path("building/reports/flag_sweep")
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKTEST_START = "2018-01-01"
BACKTEST_END = "2026-05-29"
ENABLE = ["costs"]
CACHE_SCHEMA = "flag-sweep-cache-v2"

# Recommended F8 euphoria-tail tightening (the documented backtest-gated flip).
F8_NAAIM = {"score2_exposure": 90, "score2_pctl": 90, "score1_exposure": 80, "score1_pctl": 85}
F8_PCR = {"score2_pcr": 0.52, "score2_pctl": 8, "score1_pcr": 0.58, "score1_pctl": 12}


def build_config(variant: str) -> dict:
    cfg = copy.deepcopy(load_config())
    feats = cfg.setdefault("features", {})
    if variant == "baseline":
        pass
    elif variant == "continuous_sell_fraction":
        cfg["sell_fraction_mode"] = "continuous"
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
    elif variant == "cnn_fgi":
        feats["data_cnn_fgi"] = True
    elif variant == "cot_nq":
        feats["data_cot_nq"] = True
    elif variant == "CM_EXCHANGE_INFLOW_PRESSURE":
        feats["data_onchain_mstr"] = True
        cfg["onchain_mstr"] = {"candidate": "CM_EXCHANGE_INFLOW_PRESSURE"}
    elif variant == "CM_EXCHANGE_NETFLOW_PRESSURE":
        feats["data_onchain_mstr"] = True
        cfg["onchain_mstr"] = {"candidate": "CM_EXCHANGE_NETFLOW_PRESSURE"}
    elif variant == "suspect_valve_guard":
        feats["use_suspect_valve_guard"] = True
    elif variant == "slo_spine":
        # T9+T10 combined run — proved NOT a no-op (confidence feeds sizing)
        feats["use_soft_data_max_age"] = True
        feats["use_full_confidence_spine"] = True
    elif variant == "slo_only":
        feats["use_soft_data_max_age"] = True
    elif variant == "spine_only":
        feats["use_full_confidence_spine"] = True
    elif variant == "mnav_b6":
        feats["data_mstr_mnav"] = True
        feats["use_b6_mnav_valuation"] = True
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


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_hash() -> str:
    """Hash production code that can affect flag-sweep replay behavior."""
    roots = [
        REPO_ROOT / "src" / "hermes_escape_top",
        REPO_ROOT / "scripts" / "backtest_flag_sweep.py",
        REPO_ROOT / "scripts" / "flag_gate.py",
        REPO_ROOT / "src" / "pyproject.toml",
    ]
    digest = hashlib.sha256()
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in f"/{rel}/" or "__pycache__" in path.parts:
                continue
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_file_sha256(path).encode("ascii"))
            digest.update(b"\0")
    return digest.hexdigest()


def _git_commit() -> str:
    try:
        import subprocess

        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _data_manifest_id(cfg: dict) -> str:
    cfg_for_manifest = copy.deepcopy(cfg)
    cfg_for_manifest.setdefault("runtime", {})["offline_replay_mode"] = True
    store = LocalStore(cfg_for_manifest)
    return freeze_manifest(store.history_dir).manifest_id


def _soft_history_hash(cfg: dict) -> str:
    base = LocalStore(cfg).history_dir.parent / "soft_history"
    digest = hashlib.sha256()
    if not base.exists():
        return "missing"
    for path in sorted(base.glob("*.csv")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_sha256(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def cache_key(variant: str, cfg: dict) -> str:
    payload = {
        "schema": CACHE_SCHEMA,
        "variant": variant,
        "git_commit": _git_commit(),
        "code_sha256": _code_hash(),
        "config_sha256": _sha256_text(_stable_json(cfg)),
        "data_manifest_id": _data_manifest_id(cfg),
        "soft_history_sha256": _soft_history_hash(cfg),
        "start": BACKTEST_START,
        "end": BACKTEST_END,
        "enable": ENABLE,
        "limit": None,
    }
    return _sha256_text(_stable_json(payload))


def _cache_is_fresh(variant: str, key: str) -> bool:
    metrics_path = OUT_DIR / f"{variant}.json"
    equity_path = OUT_DIR / f"{variant}_equity.json"
    if not metrics_path.exists() or not equity_path.exists():
        return False
    try:
        cached = json.loads(metrics_path.read_text())
    except Exception:
        return False
    return cached.get("cache_key") == key and cached.get("cache_schema") == CACHE_SCHEMA


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one flag-sweep backtest variant")
    parser.add_argument("variant")
    parser.add_argument("--reuse-if-fresh", action="store_true",
                        help="reuse existing metrics/equity files when the cache key matches")
    args = parser.parse_args()
    variant = args.variant
    cfg = build_config(variant)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = cache_key(variant, cfg)
    if args.reuse_if_fresh and _cache_is_fresh(variant, key):
        path = OUT_DIR / f"{variant}.json"
        cached = json.loads(path.read_text())
        runtime = cached.get("runtime_sec")
        print(f"[{variant}] cache hit → {path} (original runtime_sec={runtime})")
        print(json.dumps(cached.get("metrics", {}), indent=2, default=str))
        return

    t = time.time()
    report = run_full_backtest(start=BACKTEST_START, end=BACKTEST_END, cfg=cfg, enable=set(ENABLE))
    dt = time.time() - t
    sim = report.simulation if isinstance(report.simulation, dict) else {}
    metrics = sim.get("metrics", {})
    benchmarks = report.benchmarks if isinstance(getattr(report, "benchmarks", None), dict) else {}
    out = {
        "variant": variant,
        "cache_schema": CACHE_SCHEMA,
        "cache_key": key,
        "manifest_id": report.data_manifest_id,
        "git_commit": _git_commit(),
        "code_sha256": _code_hash(),
        "start": BACKTEST_START,
        "end": BACKTEST_END,
        "enable": ENABLE,
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
