"""Phase II full-window backtest sensitivity for correlation-regime knobs.

This is a shadow-only calibration harness.  It replays cached historical
scoring rows, runs the unified pipeline once per day, then re-prices the
RiskEngine correlation-regime layer across a candidate grid.  No live config,
feature flag, account state, or signal journal is changed.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from hermes_escape_top.config import CONFIG_PATH, load_config
from hermes_escape_top.core.backtest.costs import apply_cost
from hermes_escape_top.core.backtest.metrics import equity_metrics
from hermes_escape_top.core.backtest.run_full import _load_histories, _price_panel
from hermes_escape_top.core.backtest.simulator import DayDecision
from hermes_escape_top.core.backtest.validation import deflated_sharpe, walk_forward_splits
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.pipeline import score_pipeline
from hermes_escape_top.core.portfolio.sizing_optimizer import optimize_targets
from hermes_escape_top.scripts.phase2_shadow_compare import (
    _load_store,
    _scorer_from_row,
    _slice_store,
    _verdict_from_row,
)
from hermes_escape_top.integration_config import default_integration_config, phase_ii_overrides


HERMES_ROOT = Path(__file__).resolve().parents[1]


def run_phase2_full_backtest_sensitivity(
    *,
    backtest_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    thresholds: Optional[List[float]] = None,
    penalties: Optional[List[float]] = None,
    limit: Optional[int] = None,
    exact_optimizer: bool = False,
    start: Optional[str] = None,
    end: Optional[str] = None,
    suffix: str = "",
) -> Dict[str, Any]:
    out_dir = out_dir or HERMES_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    backtest_path = backtest_path or out_dir / "Backtest_FULL_2018_2026.json"
    thresholds = thresholds or [92, 100, 110, 120, 130, 140, 150]
    penalties = penalties or [0.70, 0.80, 0.90]

    source = json.loads(backtest_path.read_text(encoding="utf-8"))
    rows = source.get("rows", [])
    if not rows:
        raise RuntimeError(f"No rows in {backtest_path}")
    if start or end:
        rows = _filter_rows_by_date(rows, start=start, end=end)
    if limit is not None:
        rows = rows[-max(1, int(limit)) :]
    if not rows:
        raise RuntimeError("No rows after date/limit filtering")

    base_cfg = load_config(CONFIG_PATH)
    pipeline_cfg = _pipeline_config()
    clean_store = _load_store(base_cfg, pipeline_cfg)
    price_histories = _load_histories(LocalStore(base_cfg), base_cfg)

    replay_rows, errors = _build_replay_cache(rows, clean_store, pipeline_cfg)
    price_panel = _build_shared_price_panel(replay_rows, rows, price_histories, pipeline_cfg)
    return_frame = _returns_from_price_panel(price_panel)
    scenarios = []
    for threshold in thresholds:
        for penalty in penalties:
            scenarios.append(
                _simulate_scenario(
                    replay_rows,
                    source_rows=rows,
                    price_panel=price_panel,
                    return_frame=return_frame,
                    pipeline_cfg=pipeline_cfg,
                    base_cfg=base_cfg,
                    threshold=float(threshold),
                    penalty=float(penalty),
                    scenario_count=len(thresholds) * len(penalties),
                    exact_optimizer=exact_optimizer,
                )
            )

    walk = _walk_forward_diagnostics(scenarios, [row["date"] for row in replay_rows])
    candidate = _pick_review_candidate(scenarios)
    baseline = _baseline_summary(source)
    public_scenarios = [_strip_daily(s) for s in scenarios]
    artifact = {
        "schema_version": "phase2-full-backtest-sensitivity-v1",
        "source_backtest": str(backtest_path),
        "rows_loaded": len(rows),
        "rows_evaluated": len(replay_rows),
        "date_filter": {"start": start, "end": end},
        "exact_optimizer": bool(exact_optimizer),
        "errors": errors,
        "base_threshold": 92,
        "base_penalty": 0.70,
        "baseline_old_backtest": baseline,
        "review_candidate": candidate,
        "walk_forward": walk,
        "scenarios": public_scenarios,
        "live_effect": "none",
        "notes": [
            "Shadow-only replay; no live config, feature flag, account state, or signal journal is changed.",
            "Uses cached historical A/B/C/D score rows, then routes residual sleeve capital through the cached capital-routing decision for that day.",
            "Default scenario sizing uses the deterministic R3/confidence/risk-gross upper-bound projection; pass --exact-optimizer for slow SLSQP spot checks.",
            "The candidate is a review target only; Phase III scaler replacement remains locked until human dry-run gates pass.",
        ],
    }

    safe_suffix = _safe_suffix(suffix)
    json_path = out_dir / f"PhaseII_Full_Backtest_Sensitivity{safe_suffix}.json"
    md_path = out_dir / f"PhaseII_Full_Backtest_Sensitivity{safe_suffix}.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_report(artifact, md_path)
    print(f"Phase II full backtest sensitivity artifact: {json_path}")
    print(f"Phase II full backtest sensitivity report: {md_path}")
    return artifact


def _filter_rows_by_date(rows: List[Dict[str, Any]], *, start: Optional[str], end: Optional[str]) -> List[Dict[str, Any]]:
    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    out = []
    for row in rows:
        day = pd.Timestamp(str(row.get("date")))
        if start_ts is not None and day < start_ts:
            continue
        if end_ts is not None and day > end_ts:
            continue
        out.append(row)
    return out


def _safe_suffix(suffix: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(suffix or "").strip())
    if not cleaned:
        return ""
    return cleaned if cleaned.startswith("_") else f"_{cleaned}"


def _pipeline_config() -> Dict[str, Any]:
    cfg = default_integration_config()
    _deep_update(cfg, phase_ii_overrides())
    return cfg


def _build_replay_cache(
    rows: List[Dict[str, Any]],
    clean_store: Dict[str, pd.DataFrame],
    pipeline_cfg: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    replay_rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    total = len(rows)
    for idx, row in enumerate(rows, start=1):
        as_of = str(row["date"])
        try:
            result = score_pipeline(
                as_of,
                _slice_store(clean_store, as_of),
                pipeline_cfg,
                scorer_fn=_scorer_from_row(row),
                verdict_fn=_verdict_from_row(row, pipeline_cfg),
            )
        except Exception as exc:
            errors.append({"date": as_of, "error": str(exc)})
            continue
        meta = result.risk_state.estimator_meta
        replay_rows.append(
            {
                "date": as_of,
                "result": result,
                "routing": row.get("routing", {}),
                "old_weights": row.get("route_leg_weights", {}),
                "pre_corr_gross": _as_float(meta.get("gross_before_corr_penalty"), result.risk_state.gross_scaler),
                "ratio_score": _as_float(meta.get("downside_corr_ratio_score"), 0.0),
            }
        )
        if idx == 1 or idx % 250 == 0 or idx == total:
            print(f"Replay cache {idx}/{total}: {as_of}")
    return replay_rows, errors


def _simulate_scenario(
    replay_rows: List[Dict[str, Any]],
    *,
    source_rows: List[Dict[str, Any]],
    price_panel: Dict[str, pd.Series],
    return_frame: pd.DataFrame,
    pipeline_cfg: Dict[str, Any],
    base_cfg: Dict[str, Any],
    threshold: float,
    penalty: float,
    scenario_count: int,
    exact_optimizer: bool,
) -> Dict[str, Any]:
    decisions: List[DayDecision] = []
    daily: List[Dict[str, Any]] = []
    hit_count = 0
    r3_violations = 0
    max_abs_weight_delta = 0.0
    binding_counts: Counter = Counter()
    gross_values: List[float] = []
    gross_deltas: List[float] = []

    source_by_date = {str(row["date"]): row for row in source_rows}
    for row in replay_rows:
        result = row["result"]
        scenario_gross, scenario_regime, scenario_binding = _scenario_gross(
            row["pre_corr_gross"],
            row["ratio_score"],
            threshold,
            penalty,
        )
        if scenario_regime == "EXTREME":
            hit_count += 1
        risk_state = replace(
            result.risk_state,
            gross_scaler=round(float(scenario_gross), 6),
            corr_regime=scenario_regime,
            binding=scenario_binding,
        )
        if exact_optimizer:
            sizing = optimize_targets(result.verdicts, risk_state, result.confidence, pipeline_cfg)
            sizing_targets = sizing.target_weights
            binding_constraints = sizing.binding_constraint
        else:
            sizing_targets, binding_constraints = _fast_project_targets(result, scenario_gross)
        weights = _route_shadow_weights(
            pipeline_cfg.get("symbols", []),
            pipeline_cfg.get("sleeve_caps", {}),
            sizing_targets,
            row.get("routing", {}),
        )
        decisions.append(DayDecision(row["date"], weights))

        old_weights = row.get("old_weights", {})
        max_symbol_delta = 0.0
        for sym in pipeline_cfg.get("symbols", []):
            target = float(sizing_targets.get(sym, 0.0) or 0.0)
            rule_weight = float(result.verdicts[sym].rule_target_weight)
            if target > rule_weight + 1e-6:
                r3_violations += 1
            old_target = float(source_by_date.get(row["date"], {}).get("sizing", {}).get(sym, {}).get("target_weight", 0.0) or 0.0)
            max_symbol_delta = max(max_symbol_delta, abs(target - old_target))
        max_abs_weight_delta = max(max_abs_weight_delta, max_symbol_delta)

        gross_values.append(float(scenario_gross))
        old_gross_values = [
            float(item.get("gross_scaler", 1.0) or 1.0)
            for item in source_by_date.get(row["date"], {}).get("sizing", {}).values()
            if isinstance(item, dict)
        ]
        old_gross = max(old_gross_values) if old_gross_values else 1.0
        gross_deltas.append(float(scenario_gross) - old_gross)
        for binding in binding_constraints.values():
            binding_counts[binding] += 1

        daily.append(
            {
                "date": row["date"],
                "gross_scaler": round(float(scenario_gross), 6),
                "corr_regime": scenario_regime,
                "ratio_score": round(float(row["ratio_score"]), 6),
                "target_weights": sizing_targets,
                "route_leg_weights": weights,
                "max_symbol_delta_vs_old": round(float(max_symbol_delta), 6),
            }
        )

    simulation = _simulate_fast_decisions(decisions, return_frame, base_cfg)
    metrics = simulation.get("metrics", {})
    equity = pd.Series(simulation.get("equity_curve", {}), dtype=float)
    returns = equity.pct_change().dropna()
    dsr = deflated_sharpe(
        returns,
        n_trials=max(1, int(scenario_count)),
        skew=float(returns.skew()) if not returns.empty else 0.0,
        kurt=float(returns.kurt() + 3) if not returns.empty else 3.0,
    )

    return {
        "threshold": round(float(threshold), 6),
        "penalty": round(float(penalty), 6),
        "hit_count": hit_count,
        "hit_share": round(hit_count / len(replay_rows), 6) if replay_rows else 0.0,
        "avg_gross": round(_mean(gross_values), 6),
        "min_gross": round(min(gross_values), 6) if gross_values else 0.0,
        "avg_gross_delta": round(_mean(gross_deltas), 6),
        "max_abs_weight_delta": round(max_abs_weight_delta, 6),
        "r3_violations": r3_violations,
        "binding_counts": dict(binding_counts),
        "simulation": {
            "final_value": metrics.get("final_value"),
            "cagr": metrics.get("cagr"),
            "max_drawdown": metrics.get("max_drawdown"),
            "max_drawdown_start": metrics.get("max_drawdown_start"),
            "max_drawdown_end": metrics.get("max_drawdown_end"),
            "sharpe": metrics.get("sharpe"),
            "sortino": metrics.get("sortino"),
            "turnover": simulation.get("turnover"),
            "deflated_sharpe": round(float(dsr), 6),
        },
        "daily_rows": daily,
        "_equity_curve": simulation.get("equity_curve", {}),
    }


def _build_shared_price_panel(
    replay_rows: List[Dict[str, Any]],
    source_rows: List[Dict[str, Any]],
    price_histories: Dict[str, pd.DataFrame],
    pipeline_cfg: Dict[str, Any],
) -> Dict[str, pd.Series]:
    dates = [row["date"] for row in replay_rows]
    legs = set(pipeline_cfg.get("symbols", []))
    legs.add("BOXX")
    for row in source_rows:
        legs.update(row.get("route_leg_weights", {}).keys())
        for route in row.get("routing", {}).values():
            if isinstance(route, dict):
                legs.update(route.get("weights", {}).keys())
    print(f"Price panel legs: {', '.join(sorted(legs))}")
    return _price_panel(sorted(legs), dates, price_histories)


def _returns_from_price_panel(price_panel: Dict[str, pd.Series]) -> pd.DataFrame:
    if not price_panel:
        return pd.DataFrame()
    frame = pd.DataFrame({leg: pd.to_numeric(series, errors="coerce") for leg, series in price_panel.items()})
    frame = frame.sort_index().ffill().bfill()
    return frame.pct_change().fillna(0.0)


def _simulate_fast_decisions(
    decisions: List[DayDecision],
    return_frame: pd.DataFrame,
    cfg: Dict[str, Any],
    *,
    initial_capital: float = 100000.0,
) -> Dict[str, Any]:
    ordered = sorted(decisions, key=lambda item: item.date)
    equity = float(initial_capital)
    previous_weights: Dict[str, float] = {}
    previous_date: Optional[str] = None
    equity_curve: Dict[str, float] = {}
    rows: List[Dict[str, Any]] = []
    total_turnover = 0.0

    for decision in ordered:
        day = decision.date
        if previous_date is not None and not return_frame.empty:
            day_returns = return_frame.loc[pd.Timestamp(day)] if pd.Timestamp(day) in return_frame.index else None
            if day_returns is not None:
                period_return = 0.0
                for leg, weight in previous_weights.items():
                    if leg in day_returns and weight > 0:
                        period_return += float(weight) * float(day_returns[leg])
                equity *= 1.0 + period_return
        weights = _normalize_weights(decision.target_weights)
        turnover = sum(abs(weights.get(leg, 0.0) - previous_weights.get(leg, 0.0)) for leg in set(weights) | set(previous_weights))
        cost = apply_cost(equity * turnover, None, cfg)
        equity -= cost
        total_turnover += turnover
        equity_curve[day] = round(equity, 6)
        rows.append(
            {
                "date": day,
                "equity": round(equity, 6),
                "turnover": round(turnover, 6),
                "cost": round(cost, 6),
                "weights": weights,
            }
        )
        previous_weights = weights
        previous_date = day

    equity_series = pd.Series(equity_curve, dtype=float)
    return {
        "equity_curve": equity_curve,
        "turnover": round(float(total_turnover), 6),
        "metrics": equity_metrics(equity_series).to_dict(),
        "rows": rows,
    }


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    cleaned = {leg: max(0.0, float(weight)) for leg, weight in weights.items()}
    gross = sum(cleaned.values())
    if gross > 1.0:
        cleaned = {leg: weight / gross for leg, weight in cleaned.items()}
    return {leg: round(float(weight), 8) for leg, weight in sorted(cleaned.items()) if weight > 1e-12}


def _fast_project_targets(result: Any, scenario_gross: float) -> Tuple[Dict[str, float], Dict[str, str]]:
    """Fast deterministic projection for sensitivity grids.

    The Phase II sizing shadow currently binds mainly at the R3/confidence/risk
    upper bound.  Replaying every grid cell through SLSQP is therefore
    computationally wasteful for calibration scanning; this projection keeps
    the invariant that no target can exceed the verdict rule weight.
    """
    conf = max(0.0, min(1.0, float(result.confidence.decision_confidence)))
    gross = max(0.0, min(1.0, float(scenario_gross)))
    targets: Dict[str, float] = {}
    bindings: Dict[str, str] = {}
    for sym, verdict in result.verdicts.items():
        rule = max(0.0, float(verdict.rule_target_weight))
        target = min(rule, rule * conf * gross)
        targets[sym] = round(float(target), 6)
        if target <= 1e-8:
            bindings[sym] = "ZERO"
        elif gross < 1.0 and abs(target - rule * conf * gross) < 1e-6:
            bindings[sym] = "RISK_GROSS"
        elif conf < 1.0 and abs(target - rule * conf) < 1e-6:
            bindings[sym] = "CONFIDENCE"
        elif abs(target - rule) < 1e-6:
            bindings[sym] = "R3_RULE"
        else:
            bindings[sym] = "NONE"
    return targets, bindings


def _scenario_gross(pre_corr_gross: float, ratio_score: float, threshold: float, penalty: float) -> Tuple[float, str, str]:
    pre = max(0.0, min(1.0, float(pre_corr_gross)))
    ratio = float(ratio_score)
    if ratio >= float(threshold):
        return max(0.0, min(1.0, pre * float(penalty))), "EXTREME", "EXTREME_CORR"
    if ratio >= 80.0:
        return pre, "ELEVATED", "VOL" if pre < 1.0 else "NONE"
    return pre, "NORMAL", "VOL" if pre < 1.0 else "NONE"


def _route_shadow_weights(
    symbols: List[str],
    sleeve_caps: Dict[str, float],
    target_weights: Dict[str, float],
    routing: Dict[str, Any],
) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for sym in symbols:
        cap = max(0.0, float(sleeve_caps.get(sym, 0.0) or 0.0))
        target = max(0.0, min(cap, float(target_weights.get(sym, 0.0) or 0.0)))
        if target > 1e-12:
            weights[sym] = weights.get(sym, 0.0) + target
        residual = max(0.0, cap - target)
        route = routing.get(sym, {}) if isinstance(routing, dict) else {}
        route_weights = route.get("weights", {}) if route.get("applies") else {}
        if residual > 1e-12 and route_weights:
            for leg, share in route_weights.items():
                weights[str(leg)] = weights.get(str(leg), 0.0) + residual * float(share)
        elif residual > 1e-12:
            weights["BOXX"] = weights.get("BOXX", 0.0) + residual
    gross = sum(weights.values())
    if gross < 1.0:
        weights["BOXX"] = weights.get("BOXX", 0.0) + (1.0 - gross)
    elif gross > 1.0:
        weights = {leg: weight / gross for leg, weight in weights.items()}
    return {leg: round(float(weight), 8) for leg, weight in sorted(weights.items()) if weight > 1e-12}


def _walk_forward_diagnostics(scenarios: List[Dict[str, Any]], dates: List[str]) -> Dict[str, Any]:
    folds = walk_forward_splits(dates)
    if not folds:
        return {"folds": [], "train_greedy_pbo": None, "fixed_candidate_pbo": None}

    scenario_scores: Dict[Tuple[float, float], Dict[str, List[float]]] = {}
    scenario_by_key: Dict[Tuple[float, float], Dict[str, Any]] = {}
    for scenario in scenarios:
        key = (float(scenario["threshold"]), float(scenario["penalty"]))
        scenario_by_key[key] = scenario
        equity = pd.Series(scenario.get("_equity_curve", {}), dtype=float)
        scenario_scores[key] = {"train": [], "test": []}
        for fold in folds:
            train_equity = equity.iloc[fold.train_idx]
            test_equity = equity.iloc[fold.test_idx]
            scenario_scores[key]["train"].append(_fold_sharpe(train_equity))
            scenario_scores[key]["test"].append(_fold_sharpe(test_equity))

    train_greedy_bad = 0
    fold_rows = []
    keys = sorted(scenario_scores)
    fixed_bad = {key: 0 for key in keys}
    fixed_rank_sum = {key: 0.0 for key in keys}
    for i, fold in enumerate(folds):
        ranked_train = sorted(keys, key=lambda k: scenario_scores[k]["train"][i], reverse=True)
        train_best = ranked_train[0]
        ranked_test = sorted(keys, key=lambda k: scenario_scores[k]["test"][i], reverse=True)
        oos_rank = ranked_test.index(train_best) + 1
        if oos_rank > len(keys) / 2:
            train_greedy_bad += 1
        for key in keys:
            rank = ranked_test.index(key) + 1
            fixed_rank_sum[key] += rank
            if rank > len(keys) / 2:
                fixed_bad[key] += 1
        fold_rows.append(
            {
                "train_start": fold.train_start,
                "train_end": fold.train_end,
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "train_best_threshold": train_best[0],
                "train_best_penalty": train_best[1],
                "train_best_oos_rank": oos_rank,
                "scenario_count": len(keys),
            }
        )
    for key in keys:
        scenario = scenario_by_key[key]
        scenario["fixed_oos_below_median_share"] = round(fixed_bad[key] / len(folds), 6)
        scenario["mean_oos_rank"] = round(fixed_rank_sum[key] / len(folds), 6)

    return {
        "folds": fold_rows,
        "train_greedy_pbo": round(train_greedy_bad / len(folds), 6),
        "note": "PBO is the share of folds where the train-best scenario lands below median OOS rank.",
    }


def _fold_sharpe(equity: pd.Series) -> float:
    if equity is None or equity.empty or len(equity) < 3:
        return 0.0
    metrics = equity_metrics(equity).to_dict()
    return float(metrics.get("sharpe") or 0.0)


def _pick_review_candidate(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    feasible = [
        s for s in scenarios
        if s.get("r3_violations", 1) == 0
        and 0.25 <= float(s.get("hit_share", 0.0)) <= 0.55
        and 0.75 <= float(s.get("avg_gross", 0.0)) <= 0.90
    ]
    if not feasible:
        feasible = [s for s in scenarios if s.get("r3_violations", 1) == 0] or scenarios
    chosen = sorted(
        feasible,
        key=lambda s: (
            _score_candidate(s),
            float(s.get("fixed_oos_below_median_share", 1.0)),
            float(s.get("mean_oos_rank", 99.0)),
            abs(float(s.get("hit_share", 0.0)) - 0.40),
            -float(s.get("simulation", {}).get("sharpe") or 0.0),
        ),
    )[0]
    return _strip_daily(chosen)


def _score_candidate(scenario: Dict[str, Any]) -> float:
    sim = scenario.get("simulation", {})
    cagr = float(sim.get("cagr") or 0.0)
    max_dd = abs(float(sim.get("max_drawdown") or 0.0))
    avg_gross = float(scenario.get("avg_gross") or 0.0)
    fixed_pbo = float(scenario.get("fixed_oos_below_median_share", 0.0) or 0.0)
    return (
        abs(avg_gross - 0.84)
        + max(0.0, max_dd - 0.30)
        + max(0.0, 0.10 - cagr)
        + max(0.0, fixed_pbo - 0.50)
    )


def _baseline_summary(source: Dict[str, Any]) -> Dict[str, Any]:
    sim = source.get("simulation", {})
    metrics = sim.get("metrics", {})
    return {
        "final_value": metrics.get("final_value"),
        "cagr": metrics.get("cagr"),
        "max_drawdown": metrics.get("max_drawdown"),
        "sharpe": metrics.get("sharpe"),
        "sortino": metrics.get("sortino"),
        "turnover": sim.get("turnover"),
    }


def _write_report(artifact: Dict[str, Any], path: Path) -> None:
    baseline = artifact.get("baseline_old_backtest", {})
    candidate = artifact.get("review_candidate", {})
    walk = artifact.get("walk_forward", {})
    lines = [
        "# Phase II Full Backtest Sensitivity",
        "",
        f"Source: `{artifact['source_backtest']}`",
        f"Rows evaluated: {artifact['rows_evaluated']} / loaded {artifact['rows_loaded']}",
        f"Live effect: `{artifact['live_effect']}`",
        f"Exact optimizer: `{artifact.get('exact_optimizer')}`",
        f"Date filter: `{artifact.get('date_filter')}`",
        "",
        "## Baseline Old Backtest",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Final value | {_fmt_money(baseline.get('final_value'))} |",
        f"| CAGR | {_fmt_pct(baseline.get('cagr'))} |",
        f"| MaxDD | {_fmt_pct(baseline.get('max_drawdown'))} |",
        f"| Sharpe | {_fmt(baseline.get('sharpe'))} |",
        f"| Sortino | {_fmt(baseline.get('sortino'))} |",
        f"| Turnover | {_fmt(baseline.get('turnover'))} |",
        "",
        "## Review Candidate",
        "",
        "| Field | Value |",
        "|---|---:|",
        f"| Threshold | {_fmt(candidate.get('threshold'))} |",
        f"| Penalty | {_fmt(candidate.get('penalty'))} |",
        f"| Hit share | {_fmt_pct(candidate.get('hit_share'))} |",
        f"| Avg gross | {_fmt(candidate.get('avg_gross'))} |",
        f"| Min gross | {_fmt(candidate.get('min_gross'))} |",
        f"| Final value | {_fmt_money(candidate.get('simulation', {}).get('final_value'))} |",
        f"| CAGR | {_fmt_pct(candidate.get('simulation', {}).get('cagr'))} |",
        f"| MaxDD | {_fmt_pct(candidate.get('simulation', {}).get('max_drawdown'))} |",
        f"| Sharpe | {_fmt(candidate.get('simulation', {}).get('sharpe'))} |",
        f"| DSR | {_fmt(candidate.get('simulation', {}).get('deflated_sharpe'))} |",
        f"| Turnover | {_fmt(candidate.get('simulation', {}).get('turnover'))} |",
        f"| Fixed OOS below-median share | {_fmt(candidate.get('fixed_oos_below_median_share'))} |",
        f"| Mean OOS rank | {_fmt(candidate.get('mean_oos_rank'))} |",
        f"| R3 violations | {candidate.get('r3_violations')} |",
        "",
        "## Walk Forward / PBO",
        "",
        f"- Train-greedy PBO: `{_fmt(walk.get('train_greedy_pbo'))}`",
        f"- Note: {walk.get('note', 'n/a')}",
        "",
        "## Scenario Grid",
        "",
        "| Threshold | Penalty | Hit Share | Avg Gross | Final | CAGR | MaxDD | Sharpe | DSR | Fixed PBO | Mean Rank | Turnover | R3 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in artifact.get("scenarios", []):
        sim = row.get("simulation", {})
        lines.append(
            f"| {_fmt(row.get('threshold'))} | {_fmt(row.get('penalty'))} | "
            f"{_fmt_pct(row.get('hit_share'))} | {_fmt(row.get('avg_gross'))} | "
            f"{_fmt_money(sim.get('final_value'))} | {_fmt_pct(sim.get('cagr'))} | "
            f"{_fmt_pct(sim.get('max_drawdown'))} | {_fmt(sim.get('sharpe'))} | "
            f"{_fmt(sim.get('deflated_sharpe'))} | {_fmt(row.get('fixed_oos_below_median_share'))} | "
            f"{_fmt(row.get('mean_oos_rank'))} | {_fmt(sim.get('turnover'))} | "
            f"{row.get('r3_violations')} |"
        )

    fold_rows = walk.get("folds", [])
    if fold_rows:
        lines.extend(
            [
                "",
                "## Train-Greedy Fold Checks",
                "",
                "| Train | Test | Train-Best | OOS Rank | Scenarios |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for fold in fold_rows:
            lines.append(
                f"| {fold['train_start']}→{fold['train_end']} | "
                f"{fold['test_start']}→{fold['test_end']} | "
                f"{_fmt(fold['train_best_threshold'])}/{_fmt(fold['train_best_penalty'])} | "
                f"{fold['train_best_oos_rank']} | {fold['scenario_count']} |"
            )
    lines.extend(["", "## Notes", ""])
    for note in artifact.get("notes", []):
        lines.append(f"- {note}")
    if artifact.get("errors"):
        lines.extend(["", "## Errors", ""])
        for err in artifact["errors"][:50]:
            lines.append(f"- {err['date']}: {err['error']}")
        if len(artifact["errors"]) > 50:
            lines.append(f"- ... {len(artifact['errors']) - 50} more")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _strip_daily(scenario: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in scenario.items() if k not in {"daily_rows", "_equity_curve"}}


def _deep_update(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def _as_float(value: Any, fallback: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return out if pd.notna(out) else fallback


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _parse_float_list(raw: str) -> List[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--thresholds", default=None, help="Comma-separated thresholds, e.g. 92,110,120")
    parser.add_argument("--penalties", default=None, help="Comma-separated penalties, e.g. 0.7,0.8")
    parser.add_argument("--exact-optimizer", action="store_true", help="Use slow exact SLSQP optimizer for each scenario/day")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--suffix", default="")
    args = parser.parse_args()
    run_phase2_full_backtest_sensitivity(
        backtest_path=Path(args.backtest) if args.backtest else None,
        limit=args.limit,
        thresholds=_parse_float_list(args.thresholds) if args.thresholds else None,
        penalties=_parse_float_list(args.penalties) if args.penalties else None,
        exact_optimizer=bool(args.exact_optimizer),
        start=args.start,
        end=args.end,
        suffix=args.suffix,
    )
