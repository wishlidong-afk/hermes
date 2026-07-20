#!/usr/bin/env python3
"""Reprice recorded next-open decisions across a transaction-cost curve."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from hermes_escape_top.core.backtest.execution import (
    ExecutionTiming,
    simulate_execution_timing,
)
from hermes_escape_top.core.backtest.run_full import _load_histories
from hermes_escape_top.core.backtest.simulator import DayDecision, SimulationResult
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.routing.leg_proxy import leg_price_frame


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "building/reports/current_baseline/CURRENT_BASELINE_FULL.json.gz"
DEFAULT_CONFIG = REPO_ROOT / "building/reports/current_baseline/CURRENT_BASELINE_CONFIG.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "building/reports/current_baseline/cost_robustness"
DEFAULT_BPS_LEVELS = (0.0, 5.0, 10.0, 25.0, 50.0)
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from execution_timing_sensitivity import build_execution_config, extract_decisions  # noqa: E402


def build_cost_curve(
    decisions: list[DayDecision],
    price_frames: dict[str, Any],
    cfg: dict[str, Any],
    *,
    bps_levels: Iterable[float] = DEFAULT_BPS_LEVELS,
) -> list[dict[str, Any]]:
    curve: list[dict[str, Any]] = []
    for raw_bps in bps_levels:
        bps = float(raw_bps)
        if bps < 0:
            raise ValueError("cost-curve bps levels must be non-negative")
        result = simulate_execution_timing(
            decisions,
            price_frames,
            cfg,
            timing=ExecutionTiming.NEXT_OPEN,
            extra_slippage_bps=bps,
        )
        curve.append(
            {
                "extra_slippage_bps": bps,
                "metrics": dict(result.metrics),
                "turnover": result.turnover,
                "executed_rebalances": sum(
                    1 for row in result.rows if float(row.get("turnover", 0.0) or 0.0) > 0
                ),
                "base_cost": round(
                    sum(float(row.get("base_cost", 0.0) or 0.0) for row in result.rows),
                    6,
                ),
                "extra_slippage_cost": round(
                    sum(float(row.get("slippage_cost", 0.0) or 0.0) for row in result.rows),
                    6,
                ),
            }
        )
    return curve


def build_turnover_attribution(result: SimulationResult) -> dict[str, Any]:
    previous: dict[str, float] = {}
    by_leg: dict[str, float] = {}
    by_mechanism: dict[str, float] = {}
    transitions: dict[tuple[str, str], dict[str, Any]] = {}
    switch_days: list[dict[str, Any]] = []
    for row in result.rows:
        weights = {
            str(leg): float(weight)
            for leg, weight in dict(row.get("weights") or {}).items()
            if float(weight) > 1e-12
        }
        turnover = float(row.get("turnover", 0.0) or 0.0)
        if turnover > 1e-12:
            for leg in set(previous) | set(weights):
                by_leg[leg] = by_leg.get(leg, 0.0) + abs(
                    weights.get(leg, 0.0) - previous.get(leg, 0.0)
                )
            key = (_route_label(previous), _route_label(weights))
            if not previous:
                mechanism = "INITIAL_ALLOCATION"
            elif set(previous) == set(weights):
                mechanism = "WEIGHT_REBALANCE"
            else:
                mechanism = "ROUTE_SET_CHANGE"
            by_mechanism[mechanism] = by_mechanism.get(mechanism, 0.0) + turnover
            transition = transitions.setdefault(
                key,
                {
                    "from": key[0],
                    "to": key[1],
                    "mechanism": mechanism,
                    "count": 0,
                    "turnover": 0.0,
                },
            )
            transition["count"] += 1
            transition["turnover"] += turnover
            switch_days.append(
                {
                    "date": str(row.get("date") or ""),
                    "from": key[0],
                    "to": key[1],
                    "mechanism": mechanism,
                    "turnover": turnover,
                }
            )
        previous = weights
    total = round(float(result.turnover), 6)
    leg_rows = [
        {
            "leg": leg,
            "turnover": round(value, 6),
            "share": round(value / total, 8) if total else 0.0,
        }
        for leg, value in by_leg.items()
    ]
    leg_rows.sort(key=lambda row: (-float(row["turnover"]), str(row["leg"])))
    transition_rows = list(transitions.values())
    for row in transition_rows:
        row["turnover"] = round(float(row["turnover"]), 6)
    transition_rows.sort(
        key=lambda row: (-float(row["turnover"]), str(row["from"]), str(row["to"]))
    )
    attributed = round(sum(float(row["turnover"]) for row in leg_rows), 6)
    mechanism_rows = [
        {
            "mechanism": mechanism,
            "turnover": round(value, 6),
            "share": round(value / total, 8) if total else 0.0,
        }
        for mechanism, value in by_mechanism.items()
    ]
    mechanism_rows.sort(key=lambda row: (-float(row["turnover"]), str(row["mechanism"])))
    return {
        "total_turnover": total,
        "attributed_turnover": attributed,
        "reconciled": abs(attributed - total) <= 1e-6,
        "switch_days": len(switch_days),
        "by_leg": leg_rows,
        "by_mechanism": mechanism_rows,
        "top_transitions": transition_rows[:20],
        "top_switch_days": sorted(
            switch_days,
            key=lambda row: (-float(row["turnover"]), str(row["date"])),
        )[:20],
    }


def run(
    source_path: Path = DEFAULT_SOURCE,
    config_path: Path = DEFAULT_CONFIG,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    bps_levels: Iterable[float] = DEFAULT_BPS_LEVELS,
) -> dict[str, Any]:
    source_bytes = _read_source_bytes(source_path)
    source = json.loads(source_bytes)
    decisions = extract_decisions(source)
    dates = [decision.date for decision in decisions]
    legs = sorted({leg for decision in decisions for leg in decision.target_weights})
    cfg = build_execution_config(config_path)
    store = LocalStore(cfg)
    histories = _load_histories(store, cfg)
    for leg in legs:
        if leg not in histories:
            histories[leg] = store.load_history(leg)
    price_frames = {leg: leg_price_frame(leg, dates, histories) for leg in legs}
    curve = build_cost_curve(decisions, price_frames, cfg, bps_levels=bps_levels)
    base_result = simulate_execution_timing(
        decisions,
        price_frames,
        cfg,
        timing=ExecutionTiming.NEXT_OPEN,
    )
    attribution = build_turnover_attribution(base_result)
    if not attribution["reconciled"]:
        raise ValueError("turnover attribution does not reconcile to the simulator")
    artifact = {
        "schema_version": "cost-robustness-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_role": "SENSITIVITY_OF_RECORDED_BASELINE",
        "authorization": "NO_CONFIG_FLIP",
        "source": {
            "path": str(Path(source_path).resolve()),
            "payload_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "provenance": dict(source.get("provenance") or {}),
        },
        "cost_curve": curve,
        "turnover_attribution": attribution,
        "notes": [
            "All rows reuse the recorded baseline decisions and next-open execution prices.",
            "Extra slippage is charged on absolute turnover in addition to configured base costs.",
            "This report is sensitivity evidence only and does not authorize a config or feature change.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "COST_ROBUSTNESS.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "COST_ROBUSTNESS.md").write_text(render_report(artifact), encoding="utf-8")
    return artifact


def render_report(artifact: Mapping[str, Any]) -> str:
    lines = [
        "# Cost Robustness and Turnover Attribution",
        "",
        f"Evidence role: `{artifact.get('evidence_role')}`",
        "Authorization: `NO_CONFIG_FLIP`",
        "",
        "## Cost Curve",
        "",
        "| Extra slippage | CAGR | MaxDD | Sharpe | Final value | Extra cost |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in artifact.get("cost_curve", []):
        metrics = row.get("metrics", {})
        lines.append(
            f"| {_num(row.get('extra_slippage_bps'))} bps | {_pct(metrics.get('cagr'))} | "
            f"{_pct(metrics.get('max_drawdown'))} | {_num(metrics.get('sharpe'))} | "
            f"{_money(metrics.get('final_value'))} | {_money(row.get('extra_slippage_cost'))} |"
        )
    attribution = artifact.get("turnover_attribution", {})
    lines.extend(
        [
            "",
            "## Turnover by Leg",
            "",
            f"Total turnover: `{_num(attribution.get('total_turnover'))}`; reconciled: `{attribution.get('reconciled')}`",
            "",
            "| Leg | Turnover | Share |",
            "|---|---:|---:|",
        ]
    )
    for row in attribution.get("by_leg", []):
        lines.append(
            f"| {row.get('leg')} | {_num(row.get('turnover'))} | {_pct(row.get('share'))} |"
        )
    lines.extend(
        [
            "",
            "## Turnover by Mechanism",
            "",
            "| Mechanism | Turnover | Share |",
            "|---|---:|---:|",
        ]
    )
    for row in attribution.get("by_mechanism", []):
        lines.append(
            f"| {row.get('mechanism')} | {_num(row.get('turnover'))} | {_pct(row.get('share'))} |"
        )
    lines.extend(["", "## Largest Route Transitions", "", "| From | To | Mechanism | Count | Turnover |", "|---|---|---|---:|---:|"])
    for row in attribution.get("top_transitions", [])[:10]:
        lines.append(
            f"| {row.get('from')} | {row.get('to')} | {row.get('mechanism')} | "
            f"{row.get('count')} | {_num(row.get('turnover'))} |"
        )
    lines.extend(["", "## Notes", ""])
    for note in artifact.get("notes", []):
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def _route_label(weights: Mapping[str, float]) -> str:
    active = sorted(leg for leg, weight in weights.items() if float(weight) > 1e-12)
    return "+".join(active) if active else "CASH"


def _read_source_bytes(path: Path) -> bytes:
    raw = Path(path).read_bytes()
    return gzip.decompress(raw) if Path(path).suffix == ".gz" else raw


def _num(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "n/a"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bps", default="0,5,10,25,50")
    args = parser.parse_args()
    levels = tuple(float(value.strip()) for value in args.bps.split(",") if value.strip())
    run(args.source, args.config, args.output_dir, bps_levels=levels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
