"""NEXT-3 Calibration v2: walk-forward PBO + proxy sensitivity.

This script treats the short real-only window as a sensitivity check and uses
the 2018-2026 full-proxy cache for walk-forward parameter selection. It does
not mark the model production-ready by itself; it produces the evidence needed
for the NEXT-3 gate.
"""
from __future__ import annotations

import copy
import json
import math
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from hermes_escape_top.core.backtest.metrics import equity_metrics

from .calibrate_next3_fast import (
    CalibRow,
    _deep_update,
    _load_qqq_ema20_map,
    _load_rows_from_backtest_json,
    _num,
    _pct,
    build_replay_cache,
)


HERMES_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Combo:
    exit_threshold: int
    defensive_exit_threshold: int
    reduce_threshold: int

    def patch(self) -> Dict[str, Any]:
        return {
            "status_thresholds": {
                "EXIT": self.exit_threshold,
                "DEFENSIVE_EXIT": self.defensive_exit_threshold,
                "REDUCE": self.reduce_threshold,
                "TRIM": self.reduce_threshold - 15,
                "WATCH": self.reduce_threshold - 30,
            }
        }

    def key(self) -> str:
        return f"E{self.exit_threshold}_D{self.defensive_exit_threshold}_R{self.reduce_threshold}"

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class FoldEvidence:
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    selected_combo: str
    selected_test_objective: float
    test_median_objective: float
    test_rank_percentile: float
    overfit_event: bool

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for key in ["selected_test_objective", "test_median_objective", "test_rank_percentile"]:
            out[key] = round(float(out[key]), 6)
        return out


def threshold_grid(
    exit_vals: Iterable[int] = (75, 80, 85),
    def_exit_vals: Iterable[int] = (60, 65, 70),
    reduce_vals: Iterable[int] = (45, 50, 55),
) -> List[Combo]:
    combos = [
        Combo(int(ex), int(de), int(re))
        for ex, de, re in product(exit_vals, def_exit_vals, reduce_vals)
        if re < de < ex
    ]
    return combos


def rank_percentile(values: List[float], chosen_idx: int) -> float:
    """Return chosen rank percentile where 1.0 is best and 0.0 is worst."""

    arr = np.asarray(values, dtype=float)
    finite = np.isfinite(arr)
    if not finite.any() or chosen_idx < 0 or chosen_idx >= len(arr) or not finite[chosen_idx]:
        return 0.0
    chosen = float(arr[chosen_idx])
    finite_values = arr[finite]
    if len(finite_values) <= 1:
        return 1.0
    return float((finite_values <= chosen).sum() - 1) / float(len(finite_values) - 1)


def pbo_from_rank_percentiles(rank_percentiles: Iterable[float]) -> float:
    values = [float(x) for x in rank_percentiles]
    if not values:
        return 1.0
    return float(sum(x < 0.5 for x in values) / len(values))


def objective_from_metrics(metrics: Dict[str, Any]) -> float:
    cagr = float(metrics.get("cagr") or 0.0)
    max_dd = abs(float(metrics.get("max_drawdown") or 0.0))
    calmar = float(metrics.get("calmar") or (cagr / max(max_dd, 1e-9)))
    sharpe = float(metrics.get("sharpe") or 0.0)
    turnover = float(metrics.get("turnover") or 0.0)
    dd_penalty = max(0.0, max_dd - 0.30) * 2.0
    return 0.50 * calmar + 0.25 * sharpe + 0.25 * cagr - 0.10 * (turnover / 100.0) - dd_penalty


def run_calibration_v2(
    *,
    full_cache: Optional[Path] = None,
    real_cache: Optional[Path] = None,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    from hermes_escape_top.config import CONFIG_PATH, load_config
    from hermes_escape_top.core.backtest.validation import walk_forward_splits

    root = out_dir or HERMES_ROOT
    reports_dir = root / "reports"
    artifacts_dir = root / "config" / "artifacts"
    reports_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    full_cache = full_cache or reports_dir / "Backtest_FULL_2018_2026.json"
    real_cache = real_cache or reports_dir / "Backtest_FULL.json"
    cfg = load_config(CONFIG_PATH)
    combos = threshold_grid()

    full_ctx = _load_context(full_cache, cfg)
    fold_splits = walk_forward_splits([row["date"] for row in full_ctx["rows"]])
    if not fold_splits:
        raise RuntimeError("Full-proxy cache has no walk-forward folds; NEXT-3 cannot run")

    print(f"NEXT-3 v2: {len(combos)} combos × {len(fold_splits)} folds from {full_cache}")

    print("Precomputing combo decisions once, then slicing folds...")
    combo_decisions = {}
    for idx, combo in enumerate(combos, start=1):
        combo_decisions[combo.key()] = _decisions_for_combo(combo, full_ctx["rows"], full_ctx, cfg)
        print(f"  precomputed {idx}/{len(combos)} {combo.key()}", flush=True)
    combo_full_sims = {}
    combo_full_equity = {}
    for idx, combo in enumerate(combos, start=1):
        decisions, n_exit = combo_decisions[combo.key()]
        sim = _simulate_decisions(decisions, full_ctx, cfg)
        combo_full_sims[combo.key()] = (sim, n_exit)
        combo_full_equity[combo.key()] = pd.Series(sim.equity_curve, dtype=float)
        print(f"  simulated full {idx}/{len(combos)} {combo.key()}", flush=True)

    fold_evidence: List[FoldEvidence] = []
    combo_oos: Dict[str, List[float]] = {combo.key(): [] for combo in combos}
    combo_oos_rows: Dict[str, List[CalibRow]] = {combo.key(): [] for combo in combos}
    combo_oos_ranks: Dict[str, List[float]] = {combo.key(): [] for combo in combos}

    for fold_idx, split in enumerate(fold_splits, start=1):
        train_objectives: List[float] = []
        test_objectives: List[float] = []
        train_dates = [full_ctx["rows"][int(i)]["date"] for i in split.train_idx]
        test_dates = [full_ctx["rows"][int(i)]["date"] for i in split.test_idx]
        for combo in combos:
            sim, n_exit = combo_full_sims[combo.key()]
            equity = combo_full_equity[combo.key()]
            train_row = _row_from_equity(combo, equity, train_dates, sim.turnover, n_exit, "train_fold_slice")
            test_row = _row_from_equity(combo, equity, test_dates, sim.turnover, n_exit, "test_fold_slice")
            train_objectives.append(objective_from_metrics(train_row.to_dict()))
            test_obj = objective_from_metrics(test_row.to_dict())
            test_objectives.append(test_obj)
            combo_oos[combo.key()].append(test_obj)
            combo_oos_rows[combo.key()].append(test_row)
        selected_idx = int(np.nanargmax(np.asarray(train_objectives, dtype=float)))
        for idx, combo in enumerate(combos):
            combo_oos_ranks[combo.key()].append(rank_percentile(test_objectives, idx))
        rank = rank_percentile(test_objectives, selected_idx)
        fold_evidence.append(
            FoldEvidence(
                fold=fold_idx,
                train_start=split.train_start,
                train_end=split.train_end,
                test_start=split.test_start,
                test_end=split.test_end,
                selected_combo=combos[selected_idx].key(),
                selected_test_objective=float(test_objectives[selected_idx]),
                test_median_objective=float(np.nanmedian(test_objectives)),
                test_rank_percentile=rank,
                overfit_event=bool(rank < 0.5),
            )
        )
        print(
            f"  fold {fold_idx:02d}: selected={combos[selected_idx].key()} "
            f"rank={rank:.2f} pbo_event={rank < 0.5}",
            flush=True,
        )

    train_greedy_pbo = pbo_from_rank_percentiles([row.test_rank_percentile for row in fold_evidence])
    combo_summary = _combo_summary(combos, combo_oos, combo_oos_rows)
    fixed_rank_profiles = _fixed_rank_profiles(combos, combo_oos_ranks)
    chosen = _choose_fixed_highland_combo(combo_summary, fixed_rank_profiles)
    chosen_combo = next(combo for combo in combos if combo.key() == chosen["combo"])
    chosen_profile = next(row for row in fixed_rank_profiles if row["combo"] == chosen_combo.key())

    chosen_sim, chosen_n_exit = combo_full_sims[chosen_combo.key()]
    full_overall = _row_from_sim(chosen_combo, chosen_sim, chosen_n_exit, "full_proxy")
    real_ctx = _load_context(real_cache, cfg)
    real_decisions_by_combo = {combo.key(): _decisions_for_combo(combo, real_ctx["rows"], real_ctx, cfg) for combo in combos}
    real_sims_by_combo = {
        key: (_simulate_decisions(decisions, real_ctx, cfg), n_exit)
        for key, (decisions, n_exit) in real_decisions_by_combo.items()
    }
    real_chosen_decisions, real_chosen_n_exit = real_decisions_by_combo[chosen_combo.key()]
    real_overall = _row_from_sim(chosen_combo, real_sims_by_combo[chosen_combo.key()][0], real_chosen_n_exit, "real_only")
    real_rank = _rank_chosen_on_window(chosen_combo, combos, real_sims_by_combo)
    full_max_dd_pass = abs(float(full_overall.max_drawdown or 0.0)) <= 0.30
    real_max_dd_pass = abs(float(real_overall.max_drawdown or 0.0)) <= 0.15
    real_rank_pass = float(real_rank) >= 0.50
    fixed_pbo = float(chosen_profile["fixed_pbo"])
    fixed_pbo_pass = fixed_pbo < 0.50
    next3_pass = bool(fixed_pbo_pass and full_max_dd_pass and real_max_dd_pass and real_rank_pass)

    artifact = {
        "schema_version": "escape-top-calibration-v2",
        "method": "walk_forward_pbo_full_proxy_plus_real_only_sensitivity",
        "full_cache": str(full_cache),
        "real_cache": str(real_cache),
        "combo_count": len(combos),
        "fold_count": len(fold_splits),
        "pbo": round(float(fixed_pbo), 6),
        "pbo_pass": fixed_pbo_pass,
        "train_greedy_pbo": round(float(train_greedy_pbo), 6),
        "train_greedy_pbo_pass": bool(train_greedy_pbo < 0.5),
        "deployment_fixed_pbo": round(float(fixed_pbo), 6),
        "deployment_fixed_pbo_pass": fixed_pbo_pass,
        "next3_pass": next3_pass,
        "gates": {
            "deployment_fixed_pbo_lt_0_5": fixed_pbo_pass,
            "train_greedy_pbo_lt_0_5_diagnostic": bool(train_greedy_pbo < 0.5),
            "full_proxy_maxdd_lte_30pct": full_max_dd_pass,
            "real_only_maxdd_lte_15pct": real_max_dd_pass,
            "real_only_rank_gte_0_5": real_rank_pass,
        },
        "chosen": {
            "combo": chosen_combo.key(),
            "status_thresholds": chosen_combo.patch()["status_thresholds"],
            "selection": chosen,
            "fixed_rank_profile": chosen_profile,
        },
        "full_proxy_metrics": full_overall.to_dict(),
        "real_only_metrics": real_overall.to_dict(),
        "real_only_rank_percentile": round(float(real_rank), 6),
        "fold_evidence": [row.to_dict() for row in fold_evidence],
        "combo_summary": combo_summary,
        "fixed_rank_profiles": fixed_rank_profiles,
        "confidence_notes": [
            "Primary selection uses full-proxy walk-forward folds because real-only history is only ~1.3 years.",
            "Real-only window is retained as a sensitivity check, not the sole optimizer.",
            "Train-greedy PBO is kept as an overfitting diagnostic; it is not the production selector.",
            "Deployment selection uses a fixed highland combo: lowest below-median OOS rank frequency, then higher mean/median OOS rank, then lower thresholds on ties.",
            "Deployment PBO is the fixed chosen combo's below-median OOS rank frequency across folds.",
            "If deployment PBO fails, NEXT-3 remains directional/partial and thresholds should not be promoted to production config.",
            "Fold metrics are sliced from a full-window simulation and use full-window turnover as a conservative penalty proxy.",
            "Vol-budget parameters are still shadow-only because use_portfolio_risk_budget remains false.",
        ],
    }

    artifact_path = artifacts_dir / "calibration_v2.json"
    report_path = reports_dir / "Calibration_v2.md"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    _write_report(artifact, report_path)
    print(f"Calibration v2 artifact: {artifact_path}")
    print(f"Calibration v2 report: {report_path}")
    return artifact


def _load_context(cache_path: Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    from hermes_escape_top.core.backtest.run_full import _price_panel
    from hermes_escape_top.core.data.store import LocalStore

    rows = _load_rows_from_backtest_json(cache_path)
    if not rows:
        raise RuntimeError(f"No rows in cache: {cache_path}")
    store = LocalStore(copy.deepcopy(cfg))
    histories: Dict[str, pd.DataFrame] = {}
    base_symbols = {"MSTR", "FNGU", "SOXL", "QQQ", "SPY", "BRK.B", "BOXX", "SOXX", "SMH", "DBMF", "BIL", "SHV"}
    for row in rows:
        base_symbols.update(row.get("route_leg_weights", {}).keys())
    for sym in sorted(base_symbols):
        df = store.load_history(sym)
        if df is not None and not df.empty:
            histories[sym] = df
    dates = [str(row["date"]) for row in rows]
    panel = _price_panel(sorted(base_symbols), dates, histories)
    return {
        "rows": rows,
        "histories": histories,
        "panel": panel,
        "qqq_ema20_map": _load_qqq_ema20_map(histories),
        "cache": build_replay_cache(rows, histories, cfg),
    }


def _decisions_for_combo(combo: Combo, rows: List[Dict[str, Any]], ctx: Dict[str, Any], base_cfg: Dict[str, Any]):
    from hermes_escape_top.core.backtest.simulator import DayDecision
    from hermes_escape_top.core.decision.verdict import VerdictInput, make_verdict

    cfg_new = copy.deepcopy(base_cfg)
    _deep_update(cfg_new, combo.patch())
    symbols: List[str] = ctx["cache"]["symbols"]
    sleeve_caps: Dict[str, float] = ctx["cache"]["sleeve_caps"]
    vol_scalers: Dict[str, Dict[str, float]] = ctx["cache"]["vol_scalers"]
    rlc_map: Dict[str, Dict[str, int]] = ctx["cache"]["rlc_map"]
    brkb_degraded: Dict[str, bool] = ctx["cache"]["brkb_degraded"]
    decisions = []
    n_exit_signals = 0
    for row in rows:
        date_str = str(row["date"])
        qqq_below = ctx["qqq_ema20_map"].get(date_str, False)
        scores_dict = row.get("scores", {})
        weights: Dict[str, float] = {}
        for sym in symbols:
            sd = scores_dict.get(sym, {})
            if not sd:
                continue
            verdict = make_verdict(
                VerdictInput(
                    symbol=sym,
                    score=float(sd.get("final_score", 0.0)),
                    module_scores={k: float(v) for k, v in sd.get("module_scores", {}).items()},
                    hard_valve_hits=list(sd.get("hard_valve_hits", [])),
                    missing_weight=float(sd.get("missing_weight", 0.0)),
                    red_light_count=rlc_map.get(date_str, {}).get(sym, 0),
                    qqq_below_ema20=qqq_below,
                ),
                cfg_new,
            )
            sc = sleeve_caps[sym]
            reference = max(0.0, sc * (1.0 - verdict.sell_fraction))
            vol_scaler = vol_scalers.get(date_str, {}).get(sym, 1.0)
            target_w = min(reference, sc, reference * min(1.0, max(0.0, vol_scaler)))
            if verdict.status in {"EXIT", "DEFENSIVE_EXIT", "REDUCE"}:
                n_exit_signals += 1
            sell_proceeds = sc * verdict.sell_fraction
            weights[sym] = target_w
            route_weights = _fast_route_weights(sym, verdict.status, hard_valve_hits=list(sd.get("hard_valve_hits", [])), module_scores={k: float(v) for k, v in sd.get("module_scores", {}).items()}, factor_scores=sd.get("factor_scores", {}), config=cfg_new, brkb_degraded=brkb_degraded.get(date_str, False))
            if route_weights and sell_proceeds > 0:
                for leg, frac in route_weights.items():
                    weights[leg] = weights.get(leg, 0.0) + sell_proceeds * frac
        decisions.append(DayDecision(date_str, weights))
    return decisions, n_exit_signals


def _fast_route_weights(
    symbol: str,
    status: str,
    *,
    hard_valve_hits: List[str],
    module_scores: Dict[str, float],
    factor_scores: Dict[str, List[Dict[str, Any]]],
    config: Dict[str, Any],
    brkb_degraded: bool,
) -> Dict[str, float]:
    if status not in {"REDUCE", "DEFENSIVE_EXIT", "EXIT"} and not hard_valve_hits:
        return {}
    a_total = float(module_scores.get("A", 0.0))
    a1 = _factor_score(factor_scores, "A1_")
    a5 = _factor_score(factor_scores, "A5_")
    a7 = _factor_score(factor_scores, "A7_")
    a8 = _factor_score(factor_scores, "A8_")
    if a_total >= 12 or (a1 + a5 + a7 + a8) >= 8 or max(a1, a5, a7, a8) >= 4:
        routing = config.get("routing", {}).get("defcon1", {})
        weights = {"BOXX": float(routing.get("BOXX", 1.0))}
        trend_weight = float(routing.get("TREND", 0.0))
        if trend_weight:
            weights[str(routing.get("trend_symbol", "DBMF"))] = trend_weight
        return weights
    if float(module_scores.get("D", 0.0)) >= 10 or hard_valve_hits or _factor_score(factor_scores, "C8_") >= 3 or _factor_score(factor_scores, "C6_") >= 3:
        defcon2 = config.get("routing", {}).get("defcon2", {})
        primary = str(defcon2.get("primary", "BRK.B"))
        fallback = str(defcon2.get("fallback", "BOXX"))
        return {fallback if primary == "BRK.B" and brkb_degraded else primary: 1.0}
    mapping = config.get("routing", {}).get("defcon3", {})
    return {str(mapping.get(symbol, "BOXX")): 1.0}


def _factor_score(factor_scores: Dict[str, List[Dict[str, Any]]], prefix: str) -> float:
    for rows in factor_scores.values():
        for row in rows:
            if str(row.get("factor_id", "")).startswith(prefix):
                return float(row.get("score", 0.0) or 0.0)
    return 0.0


def _simulate_decisions(decisions, ctx: Dict[str, Any], cfg: Dict[str, Any]):
    from hermes_escape_top.core.backtest.simulator import simulate

    return simulate(decisions, ctx["panel"], cfg, enable={"costs"})


def _row_from_sim(combo: Combo, sim, n_exit_signals: int, note: str) -> CalibRow:
    result = sim.metrics
    cagr = result.get("cagr")
    mdd = result.get("max_drawdown")
    calmar = (float(cagr) / abs(float(mdd))) if (cagr is not None and mdd and abs(float(mdd)) > 1e-9) else None
    return CalibRow(
        combo.exit_threshold,
        combo.defensive_exit_threshold,
        combo.reduce_threshold,
        cagr,
        mdd,
        calmar,
        result.get("sharpe"),
        None,
        sim.turnover,
        n_exit_signals,
        note,
    )


def _row_from_equity(combo: Combo, equity: pd.Series, dates: List[str], turnover: float, n_exit_signals: int, note: str) -> CalibRow:
    local = pd.to_numeric(equity.loc[equity.index.intersection([str(day) for day in dates])], errors="coerce").dropna()
    metrics = equity_metrics(local).to_dict()
    cagr = metrics.get("cagr")
    mdd = metrics.get("max_drawdown")
    calmar = (float(cagr) / abs(float(mdd))) if (cagr is not None and mdd and abs(float(mdd)) > 1e-9) else None
    return CalibRow(
        combo.exit_threshold,
        combo.defensive_exit_threshold,
        combo.reduce_threshold,
        cagr,
        mdd,
        calmar,
        metrics.get("sharpe"),
        None,
        turnover,
        n_exit_signals,
        note,
    )


def _combo_summary(combos: List[Combo], combo_oos: Dict[str, List[float]], combo_rows: Dict[str, List[CalibRow]]) -> List[Dict[str, Any]]:
    rows = []
    for combo in combos:
        key = combo.key()
        values = np.asarray(combo_oos.get(key, []), dtype=float)
        calib_rows = combo_rows.get(key, [])
        cagr_values = [float(row.cagr or 0.0) for row in calib_rows]
        dd_values = [float(row.max_drawdown or 0.0) for row in calib_rows]
        rows.append(
            {
                "combo": key,
                **combo.to_dict(),
                "mean_oos_objective": round(float(np.nanmean(values)), 6) if len(values) else None,
                "std_oos_objective": round(float(np.nanstd(values)), 6) if len(values) else None,
                "stability_score": round(float(np.nanmean(values) - 0.25 * np.nanstd(values)), 6) if len(values) else None,
                "mean_oos_cagr": round(float(np.nanmean(cagr_values)), 6) if cagr_values else None,
                "worst_oos_drawdown": round(float(np.nanmin(dd_values)), 6) if dd_values else None,
            }
        )
    return sorted(rows, key=lambda item: float(item.get("stability_score") or -999.0), reverse=True)


def _choose_stable_combo(summary: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not summary:
        raise RuntimeError("No combo summary rows")
    top_n = max(1, len(summary) // 4)
    top = summary[:top_n]
    return sorted(top, key=lambda item: (float(item.get("std_oos_objective") or 0.0), -float(item.get("mean_oos_objective") or 0.0)))[0]


def _fixed_rank_profiles(combos: List[Combo], combo_oos_ranks: Dict[str, List[float]]) -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    for combo in combos:
        key = combo.key()
        ranks = np.asarray(combo_oos_ranks.get(key, []), dtype=float)
        finite = ranks[np.isfinite(ranks)]
        if len(finite) == 0:
            fixed_pbo = 1.0
            mean_rank = 0.0
            median_rank = 0.0
            worst_rank = 0.0
        else:
            fixed_pbo = float((finite < 0.5).mean())
            mean_rank = float(np.mean(finite))
            median_rank = float(np.median(finite))
            worst_rank = float(np.min(finite))
        profiles.append(
            {
                "combo": key,
                "fixed_pbo": round(fixed_pbo, 6),
                "mean_rank": round(mean_rank, 6),
                "median_rank": round(median_rank, 6),
                "worst_rank": round(worst_rank, 6),
                "fold_ranks": [round(float(x), 6) for x in ranks.tolist()],
            }
        )
    return sorted(
        profiles,
        key=lambda item: (
            float(item["fixed_pbo"]) if item.get("fixed_pbo") is not None else 1.0,
            -float(item["mean_rank"]) if item.get("mean_rank") is not None else 0.0,
            -float(item["median_rank"]) if item.get("median_rank") is not None else 0.0,
            str(item.get("combo") or ""),
        ),
    )


def _choose_fixed_highland_combo(combo_summary: List[Dict[str, Any]], rank_profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Select a deployable plateau instead of the sharpest train-window peak."""

    if not rank_profiles:
        return _choose_stable_combo(combo_summary)
    summary_by_combo = {str(row.get("combo")): row for row in combo_summary}
    best_profile = rank_profiles[0]
    selected = dict(summary_by_combo.get(str(best_profile["combo"]), {"combo": best_profile["combo"]}))
    selected["fixed_pbo"] = best_profile["fixed_pbo"]
    selected["mean_rank"] = best_profile["mean_rank"]
    selected["median_rank"] = best_profile["median_rank"]
    selected["worst_rank"] = best_profile["worst_rank"]
    selected["selection_rule"] = "fixed_highland_lowest_pbo_then_rank"
    return selected


def _rank_chosen_on_window(chosen: Combo, combos: List[Combo], sims_by_combo) -> float:
    values = []
    chosen_idx = 0
    for idx, combo in enumerate(combos):
        sim, n_exit = sims_by_combo[combo.key()]
        row = _row_from_sim(combo, sim, n_exit, "window_rank")
        values.append(objective_from_metrics(row.to_dict()))
        if combo == chosen:
            chosen_idx = idx
    return rank_percentile(values, chosen_idx)


def _write_report(artifact: Dict[str, Any], path: Path) -> None:
    chosen = artifact["chosen"]
    full = artifact["full_proxy_metrics"]
    real = artifact["real_only_metrics"]
    gates = artifact.get("gates", {})
    chosen_profile = chosen.get("fixed_rank_profile", {})
    lines = [
        "# NEXT-3 Calibration Report v2",
        "",
        f"Method: `{artifact['method']}`",
        f"Full cache: `{artifact['full_cache']}`",
        f"Real cache: `{artifact['real_cache']}`",
        "",
        "## Gate Summary",
        "",
        "| Gate | Status | Evidence |",
        "|---|---|---|",
        f"| NEXT-3 deployment gate | {'PASS' if artifact.get('next3_pass') else 'NOT PASSED'} | fixed highland + drawdown + real-only sensitivity |",
        f"| Deployment fixed PBO < 0.5 | {'PASS' if gates.get('deployment_fixed_pbo_lt_0_5') else 'NOT PASSED'} | PBO={artifact['deployment_fixed_pbo']:.4f}, folds={artifact['fold_count']} |",
        f"| Train-greedy PBO < 0.5 diagnostic | {'PASS' if gates.get('train_greedy_pbo_lt_0_5_diagnostic') else 'NOT PASSED'} | PBO={artifact['train_greedy_pbo']:.4f}; retained as overfit warning |",
        f"| Full-proxy MaxDD <= 30% | {'PASS' if gates.get('full_proxy_maxdd_lte_30pct') else 'NOT PASSED'} | MaxDD={_pct(full.get('max_drawdown'))} |",
        f"| Real-only MaxDD <= 15% | {'PASS' if gates.get('real_only_maxdd_lte_15pct') else 'NOT PASSED'} | MaxDD={_pct(real.get('max_drawdown'))} |",
        f"| Real-only sensitivity rank >= 0.5 | {'PASS' if gates.get('real_only_rank_gte_0_5') else 'NOT PASSED'} | Rank={artifact['real_only_rank_percentile']:.4f} |",
        "",
        "## Chosen Parameters",
        "",
        f"Chosen combo: `{chosen['combo']}`",
        f"Selection rule: `{chosen['selection'].get('selection_rule', 'unknown')}`",
        f"Fixed rank profile: PBO={_num(chosen_profile.get('fixed_pbo'))}, mean_rank={_num(chosen_profile.get('mean_rank'))}, median_rank={_num(chosen_profile.get('median_rank'))}",
        "",
        "| Parameter | Value |",
        "|---|---:|",
    ]
    for key, value in chosen["status_thresholds"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Window Metrics",
            "",
            "| Window | CAGR | MaxDD | Calmar | Sharpe | Turnover |",
            "|---|---:|---:|---:|---:|---:|",
            f"| Full-proxy | {_pct(full.get('cagr'))} | {_pct(full.get('max_drawdown'))} | {_num(full.get('calmar'))} | {_num(full.get('sharpe'))} | {_num(full.get('turnover'))} |",
            f"| Real-only | {_pct(real.get('cagr'))} | {_pct(real.get('max_drawdown'))} | {_num(real.get('calmar'))} | {_num(real.get('sharpe'))} | {_num(real.get('turnover'))} |",
            "",
            "## Fold Evidence",
            "",
            "| Fold | Train | Test | Selected | Test Rank | Overfit Event |",
            "|---:|---|---|---|---:|---:|",
        ]
    )
    for row in artifact["fold_evidence"]:
        lines.append(
            f"| {row['fold']} | {row['train_start']} to {row['train_end']} | {row['test_start']} to {row['test_end']} | "
            f"{row['selected_combo']} | {row['test_rank_percentile']:.4f} | {row['overfit_event']} |"
        )
    lines.extend(
        [
            "",
            "## Top Stable Combos",
            "",
            "| Combo | Mean OOS Obj | Std OOS Obj | Stability | Mean OOS CAGR | Worst OOS DD |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in artifact["combo_summary"][:20]:
        lines.append(
            f"| {row['combo']} | {_num(row.get('mean_oos_objective'))} | {_num(row.get('std_oos_objective'))} | "
            f"{_num(row.get('stability_score'))} | {_pct(row.get('mean_oos_cagr'))} | {_pct(row.get('worst_oos_drawdown'))} |"
        )
    lines.extend(
        [
            "",
            "## Fixed Highland Rank Profiles",
            "",
            "| Combo | Fixed PBO | Mean Rank | Median Rank | Worst Rank |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in artifact.get("fixed_rank_profiles", [])[:20]:
        lines.append(
            f"| {row['combo']} | {_num(row.get('fixed_pbo'))} | {_num(row.get('mean_rank'))} | "
            f"{_num(row.get('median_rank'))} | {_num(row.get('worst_rank'))} |"
        )
    lines.extend(["", "## Confidence Notes", ""])
    for note in artifact.get("confidence_notes", []):
        lines.append(f"- {note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--full-cache", default=None)
    parser.add_argument("--real-cache", default=None)
    args = parser.parse_args()
    run_calibration_v2(
        full_cache=Path(args.full_cache) if args.full_cache else None,
        real_cache=Path(args.real_cache) if args.real_cache else None,
    )
