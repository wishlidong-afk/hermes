from __future__ import annotations

import unittest

import pandas as pd

from hermes_escape_top.core.backtest.execution import (
    ExecutionTiming,
    execution_timing_sensitivity,
    simulate_execution_timing,
    summarize_open_quality,
)
from hermes_escape_top.core.backtest.simulator import DayDecision, simulate
from hermes_escape_top.core.routing.leg_proxy import leg_price_frame


DATES = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
NO_COSTS = {"costs": {"round_trip_bps": 0.0, "fixed_slippage_bps": 0.0}}


def _bars(opens: list[float], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Open": opens, "Close": closes}, index=DATES[: len(opens)])


class ExecutionTimingTests(unittest.TestCase):
    def test_legacy_close_is_byte_equivalent_to_existing_simulator(self) -> None:
        frames = {
            "A": _bars([100.0, 108.0, 100.0], [100.0, 110.0, 99.0]),
            "BOXX": _bars([100.0, 100.0, 100.0], [100.0, 100.0, 100.0]),
        }
        decisions = [
            DayDecision("2026-01-05", {"A": 1.0}),
            DayDecision("2026-01-06", {"A": 0.5, "BOXX": 0.5}),
            DayDecision("2026-01-07", {"A": 0.5, "BOXX": 0.5}),
        ]
        old = simulate(decisions, {leg: frame["Close"] for leg, frame in frames.items()}, NO_COSTS)

        new = simulate_execution_timing(decisions, frames, NO_COSTS, timing=ExecutionTiming.LEGACY_CLOSE)

        self.assertEqual(new.equity_curve, old.equity_curve)
        self.assertEqual(new.turnover, old.turnover)
        self.assertEqual(new.metrics, old.metrics)

    def test_next_open_keeps_post_signal_gap_on_old_weights(self) -> None:
        frames = {
            "A": _bars([100.0, 100.0, 80.0], [100.0, 100.0, 80.0]),
            "BOXX": _bars([100.0, 100.0, 100.0], [100.0, 100.0, 100.0]),
        }
        decisions = [
            DayDecision("2026-01-05", {"A": 1.0}),
            DayDecision("2026-01-06", {"BOXX": 1.0}),
            DayDecision("2026-01-07", {"BOXX": 1.0}),
        ]

        legacy = simulate_execution_timing(decisions, frames, NO_COSTS, timing=ExecutionTiming.LEGACY_CLOSE)
        next_open = simulate_execution_timing(decisions, frames, NO_COSTS, timing=ExecutionTiming.NEXT_OPEN)

        self.assertAlmostEqual(legacy.equity_curve["2026-01-07"], 100000.0)
        self.assertAlmostEqual(next_open.equity_curve["2026-01-07"], 80000.0)
        self.assertAlmostEqual(next_open.rows[-1]["overnight_return"], -0.20)
        self.assertEqual(next_open.rows[-1]["executed_signal_date"], "2026-01-06")
        self.assertEqual(next_open.rows[-1]["weights"], {"BOXX": 1.0})

    def test_next_open_earns_only_post_open_intraday_move(self) -> None:
        frames = {
            "A": _bars([100.0, 100.0, 80.0], [100.0, 100.0, 100.0]),
            "BOXX": _bars([100.0, 100.0, 100.0], [100.0, 100.0, 100.0]),
        }
        decisions = [
            DayDecision("2026-01-05", {"BOXX": 1.0}),
            DayDecision("2026-01-06", {"A": 1.0}),
            DayDecision("2026-01-07", {"A": 1.0}),
        ]

        legacy = simulate_execution_timing(decisions, frames, NO_COSTS, timing=ExecutionTiming.LEGACY_CLOSE)
        next_open = simulate_execution_timing(decisions, frames, NO_COSTS, timing=ExecutionTiming.NEXT_OPEN)
        next_close = simulate_execution_timing(decisions, frames, NO_COSTS, timing=ExecutionTiming.NEXT_CLOSE)

        self.assertAlmostEqual(legacy.equity_curve["2026-01-07"], 100000.0)
        self.assertAlmostEqual(next_open.equity_curve["2026-01-07"], 125000.0)
        self.assertAlmostEqual(next_close.equity_curve["2026-01-07"], 100000.0)
        self.assertAlmostEqual(next_open.rows[-1]["intraday_return"], 0.25)

    def test_next_open_extra_slippage_is_charged_on_executed_turnover(self) -> None:
        frames = {"A": _bars([100.0, 100.0], [100.0, 100.0])}
        decisions = [
            DayDecision("2026-01-05", {"A": 1.0}),
            DayDecision("2026-01-06", {"A": 1.0}),
        ]

        result = simulate_execution_timing(
            decisions,
            frames,
            NO_COSTS,
            timing=ExecutionTiming.NEXT_OPEN,
            extra_slippage_bps=25.0,
        )

        self.assertAlmostEqual(result.equity_curve["2026-01-06"], 99750.0)
        self.assertAlmostEqual(result.rows[-1]["slippage_cost"], 250.0)
        self.assertAlmostEqual(result.rows[-1]["turnover"], 1.0)

    def test_next_open_rejects_missing_open_instead_of_falling_back_to_close(self) -> None:
        frames = {"A": _bars([100.0, float("nan")], [100.0, 100.0])}
        decisions = [
            DayDecision("2026-01-05", {"A": 1.0}),
            DayDecision("2026-01-06", {"A": 1.0}),
        ]

        with self.assertRaisesRegex(ValueError, "A.*Open.*2026-01-06"):
            simulate_execution_timing(decisions, frames, NO_COSTS, timing=ExecutionTiming.NEXT_OPEN)

    def test_proxy_ohlc_marks_zero_volume_flat_bars_as_modeled_open(self) -> None:
        dates = DATES[:2]
        synthetic = pd.DataFrame(
            {
                "Open": [100.0, 121.0],
                "High": [100.0, 121.0],
                "Low": [100.0, 121.0],
                "Close": [100.0, 121.0],
                "Volume": [0.0, 0.0],
            },
            index=dates,
        )

        frame = leg_price_frame("A", dates, {"A": synthetic})

        self.assertAlmostEqual(float(frame.loc[dates[1], "Open"]), 110.0)
        self.assertAlmostEqual(float(frame.loc[dates[1], "Close"]), 121.0)
        self.assertEqual(frame.loc[dates[1], "open_quality"], "MODELED_SYNTHETIC_MIDPOINT")

    def test_sensitivity_names_next_open_as_headline_and_legacy_as_upper_bound(self) -> None:
        frames = {
            "A": _bars([100.0, 100.0, 80.0], [100.0, 100.0, 80.0]).assign(open_quality="OBSERVED"),
            "BOXX": _bars([100.0, 100.0, 100.0], [100.0, 100.0, 100.0]).assign(open_quality="OBSERVED"),
        }
        decisions = [
            DayDecision("2026-01-05", {"A": 1.0}),
            DayDecision("2026-01-06", {"BOXX": 1.0}),
            DayDecision("2026-01-07", {"BOXX": 1.0}),
        ]

        artifact = execution_timing_sensitivity(decisions, frames, NO_COSTS, stress_slippage_bps=25.0)
        scenarios = {row["scenario_id"]: row for row in artifact["scenarios"]}

        self.assertEqual(artifact["headline_scenario"], "next_open")
        self.assertEqual(scenarios["legacy_close"]["role"], "HISTORICAL_THEORETICAL_UPPER_BOUND")
        self.assertEqual(scenarios["next_open"]["role"], "PRIMARY_REALISTIC")
        self.assertEqual(scenarios["next_close"]["timing"], "next_close")
        self.assertEqual(scenarios["next_open_stress"]["extra_slippage_bps"], 25.0)
        self.assertLess(scenarios["next_open_stress"]["metrics"]["final_value"], scenarios["next_open"]["metrics"]["final_value"])

    def test_open_quality_summary_keeps_modeled_rows_visible(self) -> None:
        frames = {
            "A": pd.DataFrame(
                {
                    "Open": [100.0, 110.0, float("nan")],
                    "Close": [100.0, 121.0, 121.0],
                    "open_quality": ["OBSERVED", "MODELED_SYNTHETIC_MIDPOINT", "MISSING"],
                },
                index=DATES,
            )
        }

        summary = summarize_open_quality(frames)

        self.assertEqual(summary["total_rows"], 3)
        self.assertEqual(summary["counts"]["OBSERVED"], 1)
        self.assertEqual(summary["modeled_rows"], 1)
        self.assertEqual(summary["missing_rows"], 1)
        self.assertAlmostEqual(summary["observed_share"], 1.0 / 3.0)

    def test_open_quality_separates_unused_panel_gap_from_execution_requirements(self) -> None:
        frames = {
            "A": _bars([100.0, 100.0, 100.0], [100.0, 100.0, 100.0]).assign(
                open_quality="OBSERVED"
            ),
            "BTC-USD": _bars(
                [float("nan"), 100.0, 101.0], [100.0, 100.0, 101.0]
            ).assign(open_quality=["MISSING", "OBSERVED", "OBSERVED"]),
        }
        decisions = [
            DayDecision("2026-01-05", {"A": 1.0}),
            DayDecision("2026-01-06", {"BTC-USD": 1.0}),
            DayDecision("2026-01-07", {"BTC-USD": 1.0}),
        ]

        summary = summarize_open_quality(frames, decisions)

        self.assertEqual(summary["missing_rows"], 1)
        self.assertEqual(summary["required_missing_rows"], 0)
        self.assertEqual(summary["required_total_rows"], 3)

    def test_open_quality_counts_missing_open_when_target_needs_it(self) -> None:
        frames = {
            "A": _bars([100.0, float("nan"), 100.0], [100.0, 100.0, 100.0]).assign(
                open_quality=["OBSERVED", "MISSING", "OBSERVED"]
            )
        }
        decisions = [
            DayDecision("2026-01-05", {"A": 1.0}),
            DayDecision("2026-01-06", {"A": 1.0}),
            DayDecision("2026-01-07", {"A": 1.0}),
        ]

        summary = summarize_open_quality(frames, decisions)

        self.assertEqual(summary["required_missing_rows"], 1)


if __name__ == "__main__":
    unittest.main()
