from __future__ import annotations

import unittest

import pandas as pd

from hermes_escape_top.core.backtest.metrics import equity_metrics, max_drawdown
from hermes_escape_top.core.backtest.replay import available_replay_dates, run_score_replay
from hermes_escape_top.core.backtest.run_full import route_leg_weights, run_full_backtest


class Phase11BacktestTest(unittest.TestCase):
    def test_max_drawdown_period(self) -> None:
        equity = pd.Series([100, 120, 90, 130], index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"]))
        dd, start, end = max_drawdown(equity)
        self.assertAlmostEqual(dd, -0.25)
        self.assertEqual(start, "2026-01-02")
        self.assertEqual(end, "2026-01-05")

    def test_equity_metrics(self) -> None:
        equity = pd.Series([100, 101, 99, 105], index=pd.bdate_range("2026-01-01", periods=4))
        metrics = equity_metrics(equity)
        self.assertEqual(metrics.final_value, 105.0)
        self.assertLess(metrics.max_drawdown, 0)

    def test_score_replay_is_deterministic_for_small_window(self) -> None:
        dates = available_replay_dates("2026-05-28", "2026-05-29")
        first = run_score_replay(dates, limit=2)
        second = run_score_replay(dates, limit=2)
        self.assertEqual(first, second)
        self.assertEqual(len(first["rows"]), len(first["dates"]) * 3)

    def test_route_leg_weights_and_full_backtest_smoke(self) -> None:
        config = {
            "symbols": {
                "MSTR": {"sleeve_cap": 0.15},
                "FNGU": {"sleeve_cap": 0.20},
                "SOXL": {"sleeve_cap": 0.30},
            }
        }
        weights = route_leg_weights(
            config,
            {
                "MSTR": {"target_weight": 0.0},
                "FNGU": {"target_weight": 0.20},
                "SOXL": {"target_weight": 0.15},
            },
            {
                "MSTR": {"applies": True, "weights": {"BRK.B": 1.0}},
                "FNGU": {"applies": False, "weights": {}},
                "SOXL": {"applies": True, "weights": {"SOXX": 1.0}},
            },
        )
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertAlmostEqual(weights["BRK.B"], 0.15)
        self.assertIn("BOXX", weights)
        report = run_full_backtest("2026-05-28", "2026-05-29", limit=2)
        payload = report.to_dict()
        self.assertEqual(payload["schema_version"], "escape-top-greenfield-full-backtest-v1")
        self.assertIn("data_manifest_id", payload)
        self.assertTrue(payload["dates"])
        self.assertIn("simulation", payload)


if __name__ == "__main__":
    unittest.main()
