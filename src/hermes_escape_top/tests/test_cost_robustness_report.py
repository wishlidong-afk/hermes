from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

from hermes_escape_top.core.backtest.execution import ExecutionTiming, simulate_execution_timing
from hermes_escape_top.core.backtest.simulator import DayDecision


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "cost_robustness_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("cost_robustness_report", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prices() -> dict[str, pd.DataFrame]:
    index = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
    return {
        "RISK": pd.DataFrame(
            {"Open": [100.0, 101.0, 102.0, 103.0], "Close": [100.5, 101.5, 102.5, 103.5]},
            index=index,
        ),
        "SAFE": pd.DataFrame(
            {"Open": [100.0, 100.0, 100.0, 100.0], "Close": [100.0, 100.0, 100.0, 100.0]},
            index=index,
        ),
    }


def _decisions() -> list[DayDecision]:
    return [
        DayDecision("2026-01-05", {"RISK": 1.0}),
        DayDecision("2026-01-06", {"SAFE": 1.0}),
        DayDecision("2026-01-07", {"RISK": 0.5, "SAFE": 0.5}),
        DayDecision("2026-01-08", {"SAFE": 1.0}),
    ]


def test_cost_curve_is_monotonic_and_keeps_explicit_bps_grid():
    mod = _load_module()

    curve = mod.build_cost_curve(
        _decisions(),
        _prices(),
        {"costs": {"round_trip_bps": 10.0}},
        bps_levels=(0.0, 5.0, 10.0, 25.0, 50.0),
    )

    assert [row["extra_slippage_bps"] for row in curve] == [0.0, 5.0, 10.0, 25.0, 50.0]
    finals = [row["metrics"]["final_value"] for row in curve]
    assert finals == sorted(finals, reverse=True)
    assert all(row["turnover"] == curve[0]["turnover"] for row in curve)


def test_turnover_attribution_reconciles_to_simulator_total():
    mod = _load_module()
    result = simulate_execution_timing(
        _decisions(),
        _prices(),
        {"costs": {"round_trip_bps": 10.0}},
        timing=ExecutionTiming.NEXT_OPEN,
    )

    attribution = mod.build_turnover_attribution(result)

    assert attribution["reconciled"] is True
    assert attribution["total_turnover"] == result.turnover
    assert round(sum(row["turnover"] for row in attribution["by_leg"]), 6) == result.turnover
    assert round(sum(row["turnover"] for row in attribution["by_mechanism"]), 6) == result.turnover
    assert {row["mechanism"] for row in attribution["by_mechanism"]} == {
        "INITIAL_ALLOCATION",
        "ROUTE_SET_CHANGE",
    }
    assert attribution["switch_days"] == 3
    assert attribution["top_transitions"][0]["from"] == "RISK"
    assert attribution["top_transitions"][0]["to"] == "SAFE"
