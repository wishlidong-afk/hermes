"""Phase III dry-run comparator for the scaler migration.

This is a read-only human-gate artifact.  It replays the historical scoring
rows, applies the Phase II review candidate to the new unified pipeline, and
compares the candidate daily targets/routes/turnover with the old backtest
chain.  It never changes live config, feature flags, account state, or signal
journal files.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

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


DEFAULT_THRESHOLD = 110.0
DEFAULT_PENALTY = 0.70
DEFAULT_DAYS = 252


def run_phase3_dry_run_compare(
    *,
    backtest_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    days: Optional[int] = DEFAULT_DAYS,
    threshold: float = DEFAULT_THRESHOLD,
    penalty: float = DEFAULT_PENALTY,
    suffix: str = "",
) -> Dict[str, Any]:
    out_dir = out_dir or HERMES_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    backtest_path = backtest_path or out_dir / "Backtest_FULL_2018_2026.json"

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

    daily: List[Dict[str, Any]] = []
    gate_counts: Counter = Counter()
    binding_counts: Counter = Counter()
    corr_counts: Counter = Counter()
    r3_violations = 0
    max_abs_symbol_delta = 0.0
    max_abs_leg_delta = 0.0
    max_abs_turnover_delta = 0.0
    symbol_delta_samples: List[float] = []
    turnover_delta_samples: List[float] = []
    old_turnover_samples: List[float] = []
    new_turnover_samples: List[float] = []

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
        r3_violations += len(daily_r3)

        max_symbol_delta = _max_abs_delta(symbol_deltas)
        max_leg_delta = _max_abs_delta(leg_deltas)
        gate = _gate_row(
            r3_violations=len(daily_r3),
            route_gross=route_gross,
            max_symbol_delta=max_symbol_delta,
            max_leg_delta=max_leg_delta,
            turnover_delta=turnover_delta,
            risk_binding=risk_binding,
            corr_regime=corr_regime,
            scenario_gross=scenario_gross,
        )
        gate_counts[gate["status"]] += 1
        binding_counts[risk_binding] += 1
        corr_counts[corr_regime] += 1
        max_abs_symbol_delta = max(max_abs_symbol_delta, max_symbol_delta)
        max_abs_leg_delta = max(max_abs_leg_delta, max_leg_delta)
        max_abs_turnover_delta = max(max_abs_turnover_delta, abs(turnover_delta))
        symbol_delta_samples.append(max_symbol_delta)
        turnover_delta_samples.append(abs(turnover_delta))
        old_turnover_samples.append(old_turnover)
        new_turnover_samples.append(new_turnover)

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

    artifact = {
        "schema_version": "phase3-dry-run-comparator-v1",
        "source_backtest": str(backtest_path),
        "rows_loaded": len(rows),
        "rows_evaluated": len(daily),
        "date_filter": {"start": start, "end": end, "days": days},
        "candidate": {"threshold": float(threshold), "penalty": float(penalty)},
        "errors": errors,
        "summary": {
            "gate_counts": dict(gate_counts),
            "binding_counts": dict(binding_counts),
            "corr_regime_counts": dict(corr_counts),
            "r3_violations": int(r3_violations),
            "max_abs_symbol_delta": round(float(max_abs_symbol_delta), 6),
            "avg_max_abs_symbol_delta": round(_mean(symbol_delta_samples), 6),
            "max_abs_route_leg_delta": round(float(max_abs_leg_delta), 6),
            "avg_abs_turnover_delta": round(_mean(turnover_delta_samples), 6),
            "max_abs_turnover_delta": round(float(max_abs_turnover_delta), 6),
            "avg_old_turnover": round(_mean(old_turnover_samples), 6),
            "avg_new_turnover": round(_mean(new_turnover_samples), 6),
        },
        "human_gate_thresholds": {
            "block_on_r3_violation": True,
            "route_gross_tolerance": 0.0001,
            "warn_max_symbol_delta": 0.10,
            "warn_max_route_leg_delta": 0.15,
            "warn_abs_turnover_delta": 0.10,
            "warn_scenario_gross_below": 0.65,
            "warn_risk_binding": ["EXTREME_CORR"],
        },
        "live_effect": "none",
        "daily_rows": daily,
        "notes": [
            "Read-only dry run; no live config, feature flag, account state, or signal journal is changed.",
            "Old route weights come from cached backtest rows; new route weights use the Phase II review candidate and cached routing decision.",
            "BLOCK means invariant failure; WARN means human review required before any scaler migration; PASS is informational only.",
            "The candidate remains shadow-only until daily comparator, turnover review, and human gate all pass.",
        ],
    }

    safe_suffix = _safe_suffix(suffix)
    json_path = out_dir / f"PhaseIII_Dry_Run_Comparator{safe_suffix}.json"
    md_path = out_dir / f"PhaseIII_Dry_Run_Comparator{safe_suffix}.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_report(artifact, md_path)
    print(f"Phase III dry-run comparator artifact: {json_path}")
    print(f"Phase III dry-run comparator report: {md_path}")
    return artifact


def _old_targets(source_row: Dict[str, Any], symbols: List[str]) -> Dict[str, float]:
    sizing = source_row.get("sizing", {})
    return {
        sym: round(float(sizing.get(sym, {}).get("target_weight", 0.0) or 0.0), 6)
        for sym in symbols
    }


def _normalize_route_weights(weights: Dict[str, Any]) -> Dict[str, float]:
    cleaned = {str(leg): max(0.0, float(weight or 0.0)) for leg, weight in dict(weights or {}).items()}
    gross = sum(cleaned.values())
    if gross <= 0:
        return {}
    if gross > 1.0 + 1e-8:
        cleaned = {leg: weight / gross for leg, weight in cleaned.items()}
    return {leg: round(float(weight), 8) for leg, weight in sorted(cleaned.items()) if weight > 1e-12}


def _dict_deltas(old: Dict[str, Any], new: Dict[str, Any], keys: List[str]) -> Dict[str, float]:
    return {
        str(key): round(float(new.get(key, 0.0) or 0.0) - float(old.get(key, 0.0) or 0.0), 6)
        for key in keys
    }


def _max_abs_delta(deltas: Dict[str, float]) -> float:
    return max((abs(float(value)) for value in deltas.values()), default=0.0)


def _turnover(previous: Dict[str, Any], current: Dict[str, Any]) -> float:
    keys = set(previous) | set(current)
    return round(sum(abs(float(current.get(key, 0.0) or 0.0) - float(previous.get(key, 0.0) or 0.0)) for key in keys), 6)


def _gate_row(
    *,
    r3_violations: int,
    route_gross: float,
    max_symbol_delta: float,
    max_leg_delta: float,
    turnover_delta: float,
    risk_binding: str,
    corr_regime: str,
    scenario_gross: float,
) -> Dict[str, Any]:
    reasons: List[str] = []
    status = "PASS"
    if int(r3_violations) > 0:
        reasons.append(f"R3 violations={int(r3_violations)}")
        status = "BLOCK"
    if abs(float(route_gross) - 1.0) > 0.0001:
        reasons.append(f"route gross={route_gross:.6f}")
        status = "BLOCK"
    if status != "BLOCK":
        if float(max_symbol_delta) >= 0.10:
            reasons.append(f"max symbol delta={max_symbol_delta:.4f}")
        if float(max_leg_delta) >= 0.15:
            reasons.append(f"max route leg delta={max_leg_delta:.4f}")
        if abs(float(turnover_delta)) >= 0.10:
            reasons.append(f"turnover delta={turnover_delta:.4f}")
        if str(risk_binding) == "EXTREME_CORR":
            reasons.append("risk binding=EXTREME_CORR")
        if str(corr_regime) == "EXTREME":
            reasons.append("corr regime=EXTREME")
        if float(scenario_gross) < 0.65:
            reasons.append(f"scenario gross={scenario_gross:.4f}")
        if reasons:
            status = "WARN"
    if not reasons:
        reasons.append("within dry-run tolerance")
    return {"status": status, "reasons": reasons}


def _write_report(artifact: Dict[str, Any], path: Path) -> None:
    summary = artifact.get("summary", {})
    candidate = artifact.get("candidate", {})
    gate_counts = summary.get("gate_counts", {})
    daily_rows = artifact.get("daily_rows", [])
    lines = [
        "# Phase III Dry-run Comparator",
        "",
        f"Source: `{artifact['source_backtest']}`",
        f"Rows evaluated: {artifact['rows_evaluated']} / loaded {artifact['rows_loaded']}",
        f"Date filter: `{artifact.get('date_filter')}`",
        f"Candidate: threshold `{_fmt(candidate.get('threshold'))}`, penalty `{_fmt(candidate.get('penalty'))}`",
        f"Live effect: `{artifact.get('live_effect')}`",
        "",
        "## Human Gate Summary",
        "",
        "| Gate | Count |",
        "|---|---:|",
        f"| PASS | {int(gate_counts.get('PASS', 0))} |",
        f"| WARN | {int(gate_counts.get('WARN', 0))} |",
        f"| BLOCK | {int(gate_counts.get('BLOCK', 0))} |",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| R3 violations | {summary.get('r3_violations', 0)} |",
        f"| Max abs symbol delta | {_fmt(summary.get('max_abs_symbol_delta'))} |",
        f"| Avg max abs symbol delta | {_fmt(summary.get('avg_max_abs_symbol_delta'))} |",
        f"| Max abs route leg delta | {_fmt(summary.get('max_abs_route_leg_delta'))} |",
        f"| Avg abs turnover delta | {_fmt(summary.get('avg_abs_turnover_delta'))} |",
        f"| Max abs turnover delta | {_fmt(summary.get('max_abs_turnover_delta'))} |",
        f"| Avg old turnover | {_fmt(summary.get('avg_old_turnover'))} |",
        f"| Avg new turnover | {_fmt(summary.get('avg_new_turnover'))} |",
        "",
        "## Risk Regime Counts",
        "",
        "| Field | Counts |",
        "|---|---|",
        f"| Binding | `{summary.get('binding_counts', {})}` |",
        f"| Corr regime | `{summary.get('corr_regime_counts', {})}` |",
        "",
        "## Latest Daily Rows",
        "",
        "| Date | Gate | Gross | Binding | Max Symbol Δ | Turnover Old/New/Δ | Top Target Deltas | Reasons |",
        "|---|---|---:|---|---:|---:|---|---|",
    ]
    for row in daily_rows[-30:]:
        target_deltas = _top_deltas(row.get("target_deltas", {}), limit=3)
        turnover = row.get("turnover", {})
        risk = row.get("risk", {})
        gate = row.get("gate", {})
        lines.append(
            f"| {row.get('date')} | {gate.get('status')} | "
            f"{_fmt(risk.get('scenario_gross'))} | {risk.get('risk_binding')} | "
            f"{_fmt(_max_abs_delta(row.get('target_deltas', {})))} | "
            f"{_fmt(turnover.get('old'))}/{_fmt(turnover.get('new'))}/{_fmt(turnover.get('delta'))} | "
            f"{target_deltas} | {'; '.join(gate.get('reasons', []))} |"
        )

    top_rows = sorted(
        daily_rows,
        key=lambda item: (
            _max_abs_delta(item.get("target_deltas", {})),
            abs(float(item.get("turnover", {}).get("delta", 0.0) or 0.0)),
        ),
        reverse=True,
    )[:20]
    lines.extend(
        [
            "",
            "## Largest Difference Days",
            "",
            "| Date | Gate | Max Symbol Δ | Turnover Δ | Top Target Deltas | Reasons |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    for row in top_rows:
        gate = row.get("gate", {})
        turnover = row.get("turnover", {})
        lines.append(
            f"| {row.get('date')} | {gate.get('status')} | "
            f"{_fmt(_max_abs_delta(row.get('target_deltas', {})))} | "
            f"{_fmt(turnover.get('delta'))} | "
            f"{_top_deltas(row.get('target_deltas', {}), limit=4)} | "
            f"{'; '.join(gate.get('reasons', []))} |"
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


def _top_deltas(deltas: Dict[str, Any], *, limit: int = 3) -> str:
    ranked = sorted(deltas.items(), key=lambda item: abs(float(item[1])), reverse=True)
    picked = [f"{key}:{float(value):+.4f}" for key, value in ranked[:limit] if abs(float(value)) > 1e-9]
    return ", ".join(picked) if picked else "flat"


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--all", action="store_true", help="Evaluate all rows after date filtering instead of tail --days")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--penalty", type=float, default=DEFAULT_PENALTY)
    parser.add_argument("--suffix", default="")
    args = parser.parse_args()
    run_phase3_dry_run_compare(
        backtest_path=Path(args.backtest) if args.backtest else None,
        start=args.start,
        end=args.end,
        days=None if args.all else args.days,
        threshold=args.threshold,
        penalty=args.penalty,
        suffix=args.suffix,
    )
