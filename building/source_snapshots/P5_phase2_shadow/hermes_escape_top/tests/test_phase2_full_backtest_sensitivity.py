import unittest
from types import SimpleNamespace

import pandas as pd

from hermes_escape_top.core.contracts import ConfidenceState, Verdict
from hermes_escape_top.core.backtest.simulator import DayDecision
from hermes_escape_top.scripts.phase2_full_backtest_sensitivity import (
    _fast_project_targets,
    _returns_from_price_panel,
    _route_shadow_weights,
    _scenario_gross,
    _simulate_fast_decisions,
)


class Phase2FullBacktestSensitivityTests(unittest.TestCase):
    def test_scenario_gross_applies_extreme_penalty(self):
        gross, regime, binding = _scenario_gross(0.9, 125.0, 110.0, 0.7)

        self.assertAlmostEqual(gross, 0.63)
        self.assertEqual(regime, "EXTREME")
        self.assertEqual(binding, "EXTREME_CORR")

    def test_scenario_gross_keeps_pre_gross_when_not_extreme(self):
        gross, regime, binding = _scenario_gross(0.82, 105.0, 110.0, 0.7)

        self.assertAlmostEqual(gross, 0.82)
        self.assertEqual(regime, "ELEVATED")
        self.assertEqual(binding, "VOL")

    def test_route_shadow_weights_uses_cached_routing_for_residual(self):
        weights = _route_shadow_weights(
            ["MSTR", "FNGU", "SOXL"],
            {"MSTR": 0.15, "FNGU": 0.20, "SOXL": 0.30},
            {"MSTR": 0.0, "FNGU": 0.10, "SOXL": 0.30},
            {
                "MSTR": {"applies": True, "weights": {"BRK.B": 1.0}},
                "FNGU": {"applies": True, "weights": {"QQQ": 1.0}},
                "SOXL": {"applies": False, "weights": {}},
            },
        )

        self.assertAlmostEqual(weights["BRK.B"], 0.15)
        self.assertAlmostEqual(weights["QQQ"], 0.10)
        self.assertAlmostEqual(weights["FNGU"], 0.10)
        self.assertAlmostEqual(weights["SOXL"], 0.30)
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertGreater(weights["BOXX"], 0.0)

    def test_fast_projection_respects_r3_confidence_and_risk_gross(self):
        result = SimpleNamespace(
            confidence=ConfidenceState(0.8, "NORMAL", {}, "data"),
            verdicts={
                "MSTR": Verdict("MSTR", "HOLD", 0.15, 0.0, []),
                "FNGU": Verdict("FNGU", "EXIT", 0.0, 1.0, ["H-F1"]),
            },
        )

        targets, bindings = _fast_project_targets(result, 0.5)

        self.assertAlmostEqual(targets["MSTR"], 0.06)
        self.assertEqual(bindings["MSTR"], "RISK_GROSS")
        self.assertEqual(targets["FNGU"], 0.0)
        self.assertEqual(bindings["FNGU"], "ZERO")

    def test_fast_simulator_uses_previous_day_weights(self):
        idx = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])
        returns = _returns_from_price_panel(
            {
                "A": pd.Series([100.0, 110.0, 99.0], index=idx),
                "BOXX": pd.Series([100.0, 100.0, 100.0], index=idx),
            }
        )
        sim = _simulate_fast_decisions(
            [
                DayDecision("2026-01-01", {"A": 1.0}),
                DayDecision("2026-01-02", {"A": 0.5, "BOXX": 0.5}),
                DayDecision("2026-01-03", {"A": 0.5, "BOXX": 0.5}),
            ],
            returns,
            {"costs": {"round_trip_bps": 0.0}},
        )

        self.assertAlmostEqual(sim["equity_curve"]["2026-01-02"], 110000.0)
        self.assertAlmostEqual(sim["equity_curve"]["2026-01-03"], 104500.0)


if __name__ == "__main__":
    unittest.main()
