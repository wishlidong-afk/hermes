"""Phase III WARN sensitivity grid.

This read-only helper evaluates correlation-regime threshold/penalty choices
against the Phase III old-vs-new dry-run gates and the P7 WARN forward-return
diagnostics.  It does not change live config, feature flags, account state, or
signal journal files.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hermes_escape_top.config import CONFIG_PATH, load_config
from hermes_escape_top.scripts.phase2_full_backtest_sensitivity import (
    HERMES_ROOT,
    _build_replay_cache,
    _fast_project_targets,
    _filter_rows_by_date,
    _fmt,
    _fmt_pct,
    _pipeline_config,
    _route_shadow_weights,
    _safe_suffix,
    _scenario_gross,
)
from hermes_escape_top.scripts.phase2_shadow_compare import _load_store
from hermes_escape_top.scripts.phase3_dry_run_compare import (
    _dict_deltas,
    _gate_row,
    _max_abs_delta,
    _normalize_route_weights,
    _old_targets,
    _turnover,
)
from hermes_escape_top.scripts.phase3_warn_review import (
    _build_price_frame,
    _categorize_reasons,
    _forward_weighted_return,
    _series_stats,
)


DEFAULT_THRESHOLDS = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
DEFAULT_PENALTIES = [0.70, 0.80, 0.90, 1.00]
DEFAULT_LOOKAHEADS = [1, 5, 10]
DEFAULT_DAYS = 252


def run_phase3_warn_sensitivity(
    *,
    backtest_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    days: Optional[int] = DEFAULT_DAYS,
    thresholds: Optional[List[float]] = None,
    penalties: Optional[List[float]] = None,
    lookaheads: Optional[List[int]] = None,
    suffix: str = "",
) -> Dict[str, Any]:
    out_dir = out_dir or HERMES_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    backtest_path = backtest_path or out_dir / "Backtest_FULL_2018_2026.json"
    thresholds = thresholds or DEFAULT_THRESHOLDS
    penalties = penalties or DEFAULT_PENALTIES
    lookaheads = sorted({int(x) for x in (lookaheads or DEFAULT_LOOKAHEADS) if int(x) > 0})

    source = json.loads(backtest_path.read_text(encoding="utf-8"))
    rows = source.get("rows", [])
    if not rows:
        raise RuntimeError(f"No rows in {backtest_path}")
    if start or end:
        rows = _filter_rows_by_date(rows, start=start, end=end)
    if days is not None:
        rows = rows[-max(1, int(days)) :]
    if not rows:
        raise RuntimeError("No rows after date/day filtering")

    base_cfg = load_config(CONFIG_PATH)
    pipeline_cfg = _pipeline_config()
    clean_store = _load_store(base_cfg, pipeline_cfg)
    replay_rows, errors = _build_replay_cache(rows, clean_store, pipeline_cfg)
    source_by_date = {str(row["date"]): row for row in rows}

    scenario_daily: Dict[Tuple[float, float], List[Dict[str, Any]]] = {}
    all_daily_rows: List[Dict[str, Any]] = []
    for threshold in thresholds:
        for penalty in penalties:
            key = (float(threshold), float(penalty))
            daily = _scenario_daily_rows(
                replay_rows,
                source_by_date=source_by_date,
                pipeline_cfg=pipeline_cfg,
                threshold=float(threshold),
                penalty=float(penalty),
            )
            scenario_daily[key] = daily
            all_daily_rows.extend(daily)

    price_frame = _build_price_frame(_rows_for_price_frame(all_daily_rows))
    scenarios = [
        _summarize_scenario(
            threshold=threshold,
            penalty=penalty,
            daily_rows=daily,
            price_frame=price_frame,
            lookaheads=lookaheads,
        )
        for (threshold, penalty), daily in sorted(scenario_daily.items())
    ]
    picks = _pick_review_candidates(scenarios)
    artifact = {
        "schema_version": "phase3-warn-sensitivity-v1",
        "source_backtest": str(backtest_path),
        "rows_loaded": len(rows),
        "rows_evaluated": len(replay_rows),
        "date_filter": {"start": start, "end": end, "days": days},
        "thresholds": [float(x) for x in thresholds],
        "penalties": [float(x) for x in penalties],
        "lookaheads": lookaheads,
        "errors": errors,
        "scenario_count": len(scenarios),
        "review_candidates": picks,
        "scenarios": scenarios,
        "live_effect": "none",
        "notes": [
            "Read-only sensitivity grid; no live config, feature flag, account state, signal journal, or order routing is changed.",
            "The score is a human-review ordering aid, not an optimizer and not a live approval.",
            "Scenarios should be checked against full-window backtest sensitivity before any scaler migration.",
        ],
    }
    safe_suffix = _safe_suffix(suffix)
    json_path = out_dir / f"PhaseIII_WARN_Sensitivity{safe_suffix}.json"
    md_path = out_dir / f"PhaseIII_WARN_Sensitivity{safe_suffix}.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_report(artifact, md_path)
    print(f"Phase III WARN sensitivity artifact: {json_path}")
    print(f"Phase III WARN sensitivity report: {md_path}")
    return artifact


def _scenario_daily_rows(
    replay_rows: List[Dict[str, Any]],
    *,
    source_by_date: Dict[str, Dict[str, Any]],
    pipeline_cfg: Dict[str, Any],
    threshold: float,
    penalty: float,
) -> List[Dict[str, Any]]:
    daily: List[Dict[str, Any]] = []
    previous_old_route: Dict[str, float] = {}
    previous_new_route: Dict[str, float] = {}
    for row in replay_rows:
        date = str(row["date"])
        result = row["result"]
        source_row = source_by_date.get(date, {})
        old_targets = _old_targets(source_row, pipeline_cfg.get("symbols", []))
        old_route = _normalize_route_weights(source_row.get("route_leg_weights", row.get("old_weights", {})))
        scenario_gross, corr_regime, risk_binding = _scenario_gross(
            row["pre_corr_gross"],
            row["ratio_score"],
            threshold,
            penalty,
        )
        new_targets, binding_constraints = _fast_project_targets(result, scenario_gross)
        new_route = _route_shadow_weights(
            pipeline_cfg.get("symbols", []),
            pipeline_cfg.get("sleeve_caps", {}),
            new_targets,
            row.get("routing", {}),
        )
        symbol_deltas = _dict_deltas(old_targets, new_targets, pipeline_cfg.get("symbols", []))
        leg_keys = sorted(set(old_route) | set(new_route))
        leg_deltas = _dict_deltas(old_route, new_route, leg_keys)
        old_turnover = _turnover(previous_old_route, old_route)
        new_turnover = _turnover(previous_new_route, new_route)
        turnover_delta = new_turnover - old_turnover
        route_gross = sum(float(v) for v in new_route.values())
        rule_weights = {
            sym: round(float(result.verdicts[sym].rule_target_weight), 6)
            for sym in pipeline_cfg.get("symbols", [])
            if sym in result.verdicts
        }
        daily_r3 = [
            sym
            for sym, target in new_targets.items()
            if sym in rule_weights and float(target) > float(rule_weights[sym]) + 1e-6
        ]
        gate = _gate_row(
            r3_violations=len(daily_r3),
            route_gross=route_gross,
            max_symbol_delta=_max_abs_delta(symbol_deltas),
            max_leg_delta=_max_abs_delta(leg_deltas),
            turnover_delta=turnover_delta,
            risk_binding=risk_binding,
            corr_regime=corr_regime,
            scenario_gross=scenario_gross,
        )
        daily.append(
            {
                "date": date,
                "gate": gate,
                "risk": {
                    "scenario_gross": round(float(scenario_gross), 6),
                    "corr_regime": corr_regime,
                    "risk_binding": risk_binding,
                    "ratio_score": round(float(row["ratio_score"]), 6),
                    "pre_corr_gross": round(float(row["pre_corr_gross"]), 6),
                },
                "old_targets": old_targets,
                "new_targets": {k: round(float(v), 6) for k, v in sorted(new_targets.items())},
                "rule_weights": rule_weights,
                "target_deltas": symbol_deltas,
                "old_route_leg_weights": old_route,
                "new_route_leg_weights": new_route,
                "route_leg_deltas": leg_deltas,
                "turnover": {
                    "old": round(float(old_turnover), 6),
                    "new": round(float(new_turnover), 6),
                    "delta": round(float(turnover_delta), 6),
                },
                "binding_constraints": dict(sorted(binding_constraints.items())),
                "r3_symbols": daily_r3,
            }
        )
        previous_old_route = old_route
        previous_new_route = new_route
    return daily


def _rows_for_price_frame(daily_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge duplicate scenario dates before building the shared price panel."""
    by_date: Dict[str, Dict[str, Any]] = {}
    for row in daily_rows:
        date = str(row["date"])
        item = by_date.setdefault(date, {"date": date, "old_route_leg_weights": {}, "new_route_leg_weights": {}})
        item["old_route_leg_weights"].update(row.get("old_route_leg_weights", {}))
        item["new_route_leg_weights"].update(row.get("new_route_leg_weights", {}))
    return [by_date[date] for date in sorted(by_date)]


def _summarize_scenario(
    *,
    threshold: float,
    penalty: float,
    daily_rows: List[Dict[str, Any]],
    price_frame: Any,
    lookaheads: List[int],
) -> Dict[str, Any]:
    gate_counts: Counter = Counter()
    binding_counts: Counter = Counter()
    corr_counts: Counter = Counter()
    reason_counts: Counter = Counter()
    r3_violations = 0
    max_abs_symbol_delta = 0.0
    max_abs_route_delta = 0.0
    max_abs_turnover_delta = 0.0
    abs_turnover_deltas: List[float] = []
    old_turnovers: List[float] = []
    new_turnovers: List[float] = []
    warn_forward_values: Dict[int, List[float]] = {h: [] for h in lookaheads}
    all_forward_values: Dict[int, List[float]] = {h: [] for h in lookaheads}

    for row in daily_rows:
        status = row.get("gate", {}).get("status", "UNKNOWN")
        gate_counts[status] += 1
        risk = row.get("risk", {})
        binding_counts[str(risk.get("risk_binding"))] += 1
        corr_counts[str(risk.get("corr_regime"))] += 1
        r3_violations += len(row.get("r3_symbols", []))
        max_abs_symbol_delta = max(max_abs_symbol_delta, _max_abs_delta(row.get("target_deltas", {})))
        max_abs_route_delta = max(max_abs_route_delta, _max_abs_delta(row.get("route_leg_deltas", {})))
        turnover_delta = float(row.get("turnover", {}).get("delta", 0.0) or 0.0)
        max_abs_turnover_delta = max(max_abs_turnover_delta, abs(turnover_delta))
        abs_turnover_deltas.append(abs(turnover_delta))
        old_turnovers.append(float(row.get("turnover", {}).get("old", 0.0) or 0.0))
        new_turnovers.append(float(row.get("turnover", {}).get("new", 0.0) or 0.0))
        if status == "WARN":
            reason_counts.update(_categorize_reasons(row.get("gate", {}).get("reasons", [])))
        for horizon in lookaheads:
            old_ret = _forward_weighted_return(row.get("old_route_leg_weights", {}), price_frame, str(row["date"]), horizon)
            new_ret = _forward_weighted_return(row.get("new_route_leg_weights", {}), price_frame, str(row["date"]), horizon)
            if old_ret is None or new_ret is None:
                continue
            delta = float(new_ret - old_ret)
            all_forward_values[horizon].append(delta)
            if status == "WARN":
                warn_forward_values[horizon].append(delta)

    summary = {
        "threshold": round(float(threshold), 6),
        "penalty": round(float(penalty), 6),
        "rows_evaluated": len(daily_rows),
        "gate_counts": dict(gate_counts),
        "binding_counts": dict(binding_counts),
        "corr_regime_counts": dict(corr_counts),
        "reason_category_counts": dict(reason_counts),
        "warn_share": round(float(gate_counts.get("WARN", 0)) / max(1, len(daily_rows)), 6),
        "extreme_corr_share": round(float(binding_counts.get("EXTREME_CORR", 0)) / max(1, len(daily_rows)), 6),
        "r3_violations": int(r3_violations),
        "max_abs_symbol_delta": round(float(max_abs_symbol_delta), 6),
        "max_abs_route_leg_delta": round(float(max_abs_route_delta), 6),
        "avg_abs_turnover_delta": round(_mean(abs_turnover_deltas), 6),
        "max_abs_turnover_delta": round(float(max_abs_turnover_delta), 6),
        "avg_old_turnover": round(_mean(old_turnovers), 6),
        "avg_new_turnover": round(_mean(new_turnovers), 6),
        "warn_forward_stats": {str(h): _series_stats(warn_forward_values[h]) for h in lookaheads},
        "all_forward_stats": {str(h): _series_stats(all_forward_values[h]) for h in lookaheads},
    }
    summary["review_score"] = _scenario_review_score(summary)
    summary["readiness"] = _scenario_readiness(summary)
    return summary


def _scenario_review_score(summary: Dict[str, Any]) -> float:
    """Human-review ordering score. Lower is better; not a live optimizer."""
    if int(summary.get("r3_violations", 0) or 0) > 0 or int(summary.get("gate_counts", {}).get("BLOCK", 0) or 0) > 0:
        return 999.0
    warn_10d = _safe_float(summary.get("warn_forward_stats", {}).get("10", {}).get("mean"), 0.0)
    negative_drag = abs(min(0.0, warn_10d))
    warn_share = _safe_float(summary.get("warn_share"), 0.0)
    extreme_share = _safe_float(summary.get("extreme_corr_share"), 0.0)
    max_turnover = _safe_float(summary.get("max_abs_turnover_delta"), 0.0)
    too_little_defense = max(0.0, 0.20 - extreme_share)
    too_many_warns = max(0.0, warn_share - 0.55)
    turnover_pressure = max(0.0, max_turnover - 0.30)
    no_penalty_pressure = 0.30 if _safe_float(summary.get("penalty"), 0.0) >= 0.999 else 0.0
    return round(negative_drag * 100.0 + too_little_defense * 2.0 + too_many_warns + turnover_pressure + no_penalty_pressure, 6)


def _scenario_readiness(summary: Dict[str, Any]) -> str:
    if int(summary.get("r3_violations", 0) or 0) > 0 or int(summary.get("gate_counts", {}).get("BLOCK", 0) or 0) > 0:
        return "BLOCKED"
    if _safe_float(summary.get("max_abs_turnover_delta"), 0.0) >= 0.30:
        return "REVIEW_REQUIRED"
    if _safe_float(summary.get("penalty"), 0.0) >= 0.999:
        return "NO_PENALTY_REVIEW"
    if _safe_float(summary.get("extreme_corr_share"), 0.0) < 0.20:
        return "TOO_RELAXED_REVIEW"
    return "REVIEW_READY"


def _pick_review_candidates(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    feasible = [
        s for s in scenarios
        if int(s.get("r3_violations", 0) or 0) == 0 and int(s.get("gate_counts", {}).get("BLOCK", 0) or 0) == 0
    ]
    balanced = [
        s for s in feasible
        if 0.20 <= _safe_float(s.get("extreme_corr_share"), 0.0) <= 0.55
        and _safe_float(s.get("penalty"), 0.0) < 0.999
    ] or feasible
    current = _find_scenario(scenarios, 110.0, 0.70)
    return {
        "current_110_070": _strip_grid_row(current) if current else None,
        "balanced_lowest_score": _strip_grid_row(min(balanced, key=lambda s: float(s.get("review_score", 999.0)))) if balanced else None,
        "lowest_warn_10d_drag_with_penalty": _strip_grid_row(max([s for s in feasible if _safe_float(s.get("penalty"), 0.0) < 0.999] or feasible, key=lambda s: _safe_float(s.get("warn_forward_stats", {}).get("10", {}).get("mean"), -99.0))) if feasible else None,
        "lowest_warn_10d_drag": _strip_grid_row(max(feasible, key=lambda s: _safe_float(s.get("warn_forward_stats", {}).get("10", {}).get("mean"), -99.0))) if feasible else None,
        "lowest_warn_share": _strip_grid_row(min(feasible, key=lambda s: _safe_float(s.get("warn_share"), 99.0))) if feasible else None,
    }


def _write_report(artifact: Dict[str, Any], path: Path) -> None:
    picks = artifact.get("review_candidates", {})
    lines = [
        "# Phase III WARN Sensitivity",
        "",
        f"Source: `{artifact['source_backtest']}`",
        f"Rows evaluated: {artifact['rows_evaluated']} / loaded {artifact['rows_loaded']}",
        f"Scenario count: {artifact['scenario_count']}",
        f"Thresholds: `{artifact.get('thresholds')}`",
        f"Penalties: `{artifact.get('penalties')}`",
        f"Live effect: `{artifact.get('live_effect')}`",
        "",
        "## Review Candidates",
        "",
        "| Pick | Threshold | Penalty | Score | WARN Share | Extreme Share | WARN 10d Δ | Max Turnover Δ | Readiness |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, row in picks.items():
        lines.append(_candidate_line(name, row))
    lines.extend(
        [
            "",
            "## Scenario Grid",
            "",
            "| Threshold | Penalty | Score | Readiness | WARN | EXTREME_CORR | WARN 1d Δ | WARN 5d Δ | WARN 10d Δ | Max Turnover Δ | R3 | BLOCK |",
            "|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(artifact.get("scenarios", []), key=lambda item: (float(item.get("review_score", 999.0)), float(item.get("threshold", 0.0)), float(item.get("penalty", 0.0)))):
        warn_stats = row.get("warn_forward_stats", {})
        gate_counts = row.get("gate_counts", {})
        lines.append(
            f"| {_fmt(row.get('threshold'))} | {_fmt(row.get('penalty'))} | {_fmt(row.get('review_score'))} | "
            f"{row.get('readiness')} | {_fmt_pct(row.get('warn_share'))} | {_fmt_pct(row.get('extreme_corr_share'))} | "
            f"{_fmt_pct(warn_stats.get('1', {}).get('mean'))} | {_fmt_pct(warn_stats.get('5', {}).get('mean'))} | "
            f"{_fmt_pct(warn_stats.get('10', {}).get('mean'))} | {_fmt(row.get('max_abs_turnover_delta'))} | "
            f"{row.get('r3_violations')} | {gate_counts.get('BLOCK', 0)} |"
        )
    lines.extend(["", "## Notes", ""])
    for note in artifact.get("notes", []):
        lines.append(f"- {note}")
    if artifact.get("errors"):
        lines.extend(["", "## Replay Errors", ""])
        for err in artifact["errors"][:50]:
            lines.append(f"- {err['date']}: {err['error']}")
        if len(artifact["errors"]) > 50:
            lines.append(f"- ... {len(artifact['errors']) - 50} more")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _candidate_line(name: str, row: Optional[Dict[str, Any]]) -> str:
    if not row:
        return f"| {name} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
    return (
        f"| {name} | {_fmt(row.get('threshold'))} | {_fmt(row.get('penalty'))} | {_fmt(row.get('review_score'))} | "
        f"{_fmt_pct(row.get('warn_share'))} | {_fmt_pct(row.get('extreme_corr_share'))} | "
        f"{_fmt_pct(row.get('warn_10d_mean'))} | {_fmt(row.get('max_abs_turnover_delta'))} | {row.get('readiness')} |"
    )


def _strip_grid_row(row: Dict[str, Any]) -> Dict[str, Any]:
    warn_10d = row.get("warn_forward_stats", {}).get("10", {})
    return {
        "threshold": row.get("threshold"),
        "penalty": row.get("penalty"),
        "review_score": row.get("review_score"),
        "readiness": row.get("readiness"),
        "warn_share": row.get("warn_share"),
        "extreme_corr_share": row.get("extreme_corr_share"),
        "warn_10d_mean": warn_10d.get("mean"),
        "max_abs_turnover_delta": row.get("max_abs_turnover_delta"),
        "r3_violations": row.get("r3_violations"),
        "gate_counts": row.get("gate_counts"),
    }


def _find_scenario(scenarios: List[Dict[str, Any]], threshold: float, penalty: float) -> Optional[Dict[str, Any]]:
    for row in scenarios:
        if abs(float(row.get("threshold")) - float(threshold)) < 1e-9 and abs(float(row.get("penalty")) - float(penalty)) < 1e-9:
            return row
    return None


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _parse_float_list(raw: str) -> List[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def _parse_int_list(raw: str) -> List[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--all", action="store_true", help="Evaluate all rows after date filtering instead of tail --days")
    parser.add_argument("--thresholds", default="100,110,120,130,140,150")
    parser.add_argument("--penalties", default="0.70,0.80,0.90,1.00")
    parser.add_argument("--lookaheads", default="1,5,10")
    parser.add_argument("--suffix", default="")
    args = parser.parse_args()
    run_phase3_warn_sensitivity(
        backtest_path=Path(args.backtest) if args.backtest else None,
        start=args.start,
        end=args.end,
        days=None if args.all else args.days,
        thresholds=_parse_float_list(args.thresholds),
        penalties=_parse_float_list(args.penalties),
        lookaheads=_parse_int_list(args.lookaheads),
        suffix=args.suffix,
    )
