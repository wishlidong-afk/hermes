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

from hermes_escape_top.config import CONFIG_PATH, load_config
from hermes_escape_top.core.backtest.execution import execution_timing_sensitivity
from hermes_escape_top.core.data.manifest import freeze_manifest
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.backtest.run_full import _load_histories, run_full_backtest
from hermes_escape_top.core.backtest.simulator import DayDecision
from hermes_escape_top.core.routing.leg_proxy import leg_price_frame

OUT_DIR = Path("building/reports/flag_sweep")
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKTEST_START = "2018-01-01"
BACKTEST_END = "2026-07-10"
ENABLE = ["costs"]
CACHE_SCHEMA = "flag-sweep-cache-v4"
GATE_EQUITY_TIMING = "next_open"
CURRENT_BASELINE_CONFIG_PATH = (
    REPO_ROOT / "building" / "reports" / "current_baseline" / "CURRENT_BASELINE_CONFIG.json"
)
GATE_CODE_GIT_PATHS = (
    ":(glob)src/hermes_escape_top/**/*.py",
    ":(exclude,glob)src/hermes_escape_top/tests/**/*.py",
    "src/hermes_escape_top/config/config.json",
    "src/pyproject.toml",
    "scripts/backtest_flag_sweep.py",
    "scripts/flag_gate.py",
    "scripts/formal_gate.py",
    "scripts/execution_timing_sensitivity.py",
    "scripts/build_current_baseline.py",
)
FRESHNESS_FIELDS = (
    "variant",
    "cache_schema",
    "cache_key",
    "manifest_id",
    "git_commit",
    "code_sha256",
    "config_sha256",
    "soft_history_sha256",
    "start",
    "end",
    "enable",
    "equity_timing",
    "evidence_status",
)

# Recommended F8 euphoria-tail tightening (the documented backtest-gated flip).
F8_NAAIM = {"score2_exposure": 90, "score2_pctl": 90, "score1_exposure": 80, "score1_pctl": 85}
F8_PCR = {"score2_pcr": 0.52, "score2_pctl": 8, "score1_pcr": 0.58, "score1_pctl": 12}


def normalize_gate_config(config: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(config)
    feats = cfg.setdefault("features", {})
    feats["use_indicator_cache"] = True
    feats.setdefault("use_fred_vintage_pit", False)
    return cfg


def build_config(variant: str, *, config_path: Path | None = None) -> dict:
    selected = config_path
    if selected is None:
        selected = CURRENT_BASELINE_CONFIG_PATH if CURRENT_BASELINE_CONFIG_PATH.exists() else CONFIG_PATH
    cfg = normalize_gate_config(load_config(selected))
    feats = cfg["features"]
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
    elif variant == "fred_vintage_pit":
        feats["use_fred_vintage_pit"] = True
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
        REPO_ROOT / "scripts" / "formal_gate.py",
        REPO_ROOT / "scripts" / "execution_timing_sensitivity.py",
        REPO_ROOT / "scripts" / "build_current_baseline.py",
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

        # Evidence/report-only commits must not invalidate their own baseline.
        # This is the latest commit that touched gate-affecting code or repo config.
        commit = subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "HEAD", "--", *GATE_CODE_GIT_PATHS],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return commit or "unknown"
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


def _cache_identity(
    variant: str,
    cfg: dict,
    *,
    start: str = BACKTEST_START,
    end: str = BACKTEST_END,
    enable: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": CACHE_SCHEMA,
        "variant": variant,
        "git_commit": _git_commit(),
        "code_sha256": _code_hash(),
        "config_sha256": _sha256_text(_stable_json(cfg)),
        "data_manifest_id": _data_manifest_id(cfg),
        "soft_history_sha256": _soft_history_hash(cfg),
        "start": str(start),
        "end": str(end),
        "enable": list(ENABLE if enable is None else enable),
        "equity_timing": GATE_EQUITY_TIMING,
        "limit": None,
    }


def cache_evidence(
    variant: str,
    cfg: dict,
    *,
    start: str = BACKTEST_START,
    end: str = BACKTEST_END,
    enable: list[str] | None = None,
) -> dict[str, Any]:
    identity = _cache_identity(variant, cfg, start=start, end=end, enable=enable)
    return {
        "variant": variant,
        "evidence_status": "CURRENT_EXECUTION_EVIDENCE",
        "cache_schema": CACHE_SCHEMA,
        "cache_key": _sha256_text(_stable_json(identity)),
        "manifest_id": identity["data_manifest_id"],
        "git_commit": identity["git_commit"],
        "code_sha256": identity["code_sha256"],
        "config_sha256": identity["config_sha256"],
        "soft_history_sha256": identity["soft_history_sha256"],
        "start": identity["start"],
        "end": identity["end"],
        "enable": list(identity["enable"]),
        "equity_timing": identity["equity_timing"],
    }


def select_gate_equity(timing_artifact: dict[str, Any]) -> dict[str, Any]:
    scenarios = {
        str(row.get("scenario_id")): row
        for row in timing_artifact.get("scenarios", [])
        if isinstance(row, dict)
    }
    next_open = scenarios.get(GATE_EQUITY_TIMING)
    legacy = scenarios.get("legacy_close")
    if not next_open or not isinstance(next_open.get("equity_curve"), dict):
        raise ValueError("execution timing artifact has no next_open equity curve")
    if not legacy:
        raise ValueError("execution timing artifact has no legacy_close shadow")
    return {
        "equity_timing": GATE_EQUITY_TIMING,
        "metrics": dict(next_open.get("metrics", {})),
        "equity_curve": dict(next_open["equity_curve"]),
        "turnover": next_open.get("turnover"),
        "legacy_close_metrics": dict(legacy.get("metrics", {})),
        "legacy_close_equity_curve": dict(legacy.get("equity_curve", {})),
    }


def reprice_report_for_gate(report: Any, cfg: dict) -> dict[str, Any]:
    decisions = [
        DayDecision(str(row["date"]), {str(leg): float(weight) for leg, weight in row.get("route_leg_weights", {}).items()})
        for row in report.rows
    ]
    dates = [item.date for item in decisions]
    legs = sorted({leg for item in decisions for leg in item.target_weights})
    store = LocalStore(cfg)
    histories = _load_histories(store, cfg)
    for leg in legs:
        if leg not in histories:
            histories[leg] = store.load_history(leg)
    frames = {leg: leg_price_frame(leg, dates, histories) for leg in legs}
    return execution_timing_sensitivity(decisions, frames, cfg)


def cache_key(
    variant: str,
    cfg: dict,
    *,
    start: str = BACKTEST_START,
    end: str = BACKTEST_END,
    enable: list[str] | None = None,
) -> str:
    return str(cache_evidence(variant, cfg, start=start, end=end, enable=enable)["cache_key"])


def assess_artifact_freshness(
    variant: str,
    cached: dict[str, Any],
    cfg: dict,
    *,
    start: str = BACKTEST_START,
    end: str = BACKTEST_END,
) -> dict[str, Any]:
    expected = cache_evidence(variant, cfg, start=start, end=end)
    mismatches = [field for field in FRESHNESS_FIELDS if cached.get(field) != expected.get(field)]
    return {
        "variant": variant,
        "status": "FRESH" if not mismatches else "STALE",
        "mismatches": mismatches,
        "expected": expected,
        "actual": {field: cached.get(field) for field in FRESHNESS_FIELDS},
    }


def _cache_is_fresh(variant: str, expected: dict[str, Any]) -> bool:
    metrics_path = OUT_DIR / f"{variant}.json"
    equity_path = OUT_DIR / f"{variant}_equity.json"
    if not metrics_path.exists() or not equity_path.exists():
        return False
    try:
        cached = json.loads(metrics_path.read_text())
    except Exception:
        return False
    return all(cached.get(field) == expected.get(field) for field in FRESHNESS_FIELDS)


def current_gate_window() -> tuple[str, str]:
    path = OUT_DIR / "baseline.json"
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return BACKTEST_START, BACKTEST_END
    start = baseline.get("start")
    end = baseline.get("end")
    if (
        baseline.get("evidence_status") == "CURRENT_EXECUTION_EVIDENCE"
        and isinstance(start, str)
        and isinstance(end, str)
        and start
        and end
    ):
        return start, end
    return BACKTEST_START, BACKTEST_END


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one flag-sweep backtest variant")
    parser.add_argument("variant")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="explicit base config; defaults to the committed current-baseline config snapshot",
    )
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--reuse-if-fresh", action="store_true",
                        help="reuse existing metrics/equity files when the cache key matches")
    args = parser.parse_args()
    variant = args.variant
    baseline_start, baseline_end = current_gate_window()
    start = str(args.start or baseline_start)
    end = str(args.end or baseline_end)
    cfg = build_config(variant, config_path=args.config)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    evidence = cache_evidence(variant, cfg, start=start, end=end)
    if args.reuse_if_fresh and _cache_is_fresh(variant, evidence):
        path = OUT_DIR / f"{variant}.json"
        cached = json.loads(path.read_text())
        runtime = cached.get("runtime_sec")
        print(f"[{variant}] cache hit → {path} (original runtime_sec={runtime})")
        print(json.dumps(cached.get("metrics", {}), indent=2, default=str))
        return

    t = time.time()
    report = run_full_backtest(start=start, end=end, cfg=cfg, enable=set(ENABLE))
    timing = reprice_report_for_gate(report, cfg)
    selected = select_gate_equity(timing)
    dt = time.time() - t
    sim = report.simulation if isinstance(report.simulation, dict) else {}
    metrics = selected["metrics"]
    benchmarks = report.benchmarks if isinstance(getattr(report, "benchmarks", None), dict) else {}
    out = {
        **evidence,
        "effective_start": report.effective_start,
        "effective_end": report.effective_end,
        "n_days": len(report.dates),
        "runtime_sec": round(dt, 1),
        "equity_timing": selected["equity_timing"],
        "metrics": {
            "cagr": metrics.get("cagr"),
            "max_drawdown": metrics.get("max_drawdown"),
            "sharpe": metrics.get("sharpe"),
            "sortino": metrics.get("sortino"),
            "final_value": metrics.get("final_value"),
        },
        "legacy_close_metrics": selected["legacy_close_metrics"],
        "execution_open_quality": timing.get("open_quality", {}),
        "benchmarks": benchmarks,
    }
    path = OUT_DIR / f"{variant}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    # Daily equity curve for fold-level walk-forward / PBO gating (separate file
    # to keep the metrics JSON small).
    equity = selected["equity_curve"]
    if equity:
        (OUT_DIR / f"{variant}_equity.json").write_text(json.dumps(equity, default=str))
    legacy_equity = selected["legacy_close_equity_curve"]
    if legacy_equity:
        (OUT_DIR / f"{variant}_legacy_close_equity.json").write_text(json.dumps(legacy_equity, default=str))
    print(f"[{variant}] done in {dt/60:.1f}min → {path}")
    print(json.dumps(out["metrics"], indent=2, default=str))


if __name__ == "__main__":
    main()
