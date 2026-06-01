import unittest

from hermes_escape_top.scripts.phase3_dry_run_compare import (
    _dict_deltas,
    _gate_row,
    _max_abs_delta,
    _normalize_route_weights,
    _old_targets,
    _turnover,
)


class Phase3DryRunCompareTests(unittest.TestCase):
    def test_old_targets_reads_backtest_sizing(self):
        row = {
            "sizing": {
                "MSTR": {"target_weight": 0.12},
                "FNGU": {"target_weight": 0.05},
            }
        }

        out = _old_targets(row, ["MSTR", "FNGU", "SOXL"])

        self.assertEqual(out, {"MSTR": 0.12, "FNGU": 0.05, "SOXL": 0.0})

    def test_route_normalization_preserves_sub_one_cash_gap(self):
        out = _normalize_route_weights({"MSTR": 0.15, "BOXX": 0.70})

        self.assertAlmostEqual(out["MSTR"], 0.15)
        self.assertAlmostEqual(out["BOXX"], 0.70)

    def test_route_normalization_scales_over_one(self):
        out = _normalize_route_weights({"MSTR": 0.7, "BOXX": 0.7})

        self.assertAlmostEqual(out["MSTR"], 0.5)
        self.assertAlmostEqual(out["BOXX"], 0.5)

    def test_delta_and_turnover_helpers(self):
        deltas = _dict_deltas({"A": 0.2, "B": 0.1}, {"A": 0.05, "C": 0.4}, ["A", "B", "C"])

        self.assertEqual(deltas, {"A": -0.15, "B": -0.1, "C": 0.4})
        self.assertAlmostEqual(_max_abs_delta(deltas), 0.4)
        self.assertAlmostEqual(_turnover({"A": 0.2, "B": 0.1}, {"A": 0.05, "C": 0.4}), 0.65)

    def test_gate_blocks_r3_and_route_gross_breaks(self):
        gate = _gate_row(
            r3_violations=1,
            route_gross=1.0,
            max_symbol_delta=0.0,
            max_leg_delta=0.0,
            turnover_delta=0.0,
            risk_binding="NONE",
            corr_regime="NORMAL",
            scenario_gross=1.0,
        )

        self.assertEqual(gate["status"], "BLOCK")
        self.assertIn("R3 violations=1", gate["reasons"])

        gate = _gate_row(
            r3_violations=0,
            route_gross=0.98,
            max_symbol_delta=0.0,
            max_leg_delta=0.0,
            turnover_delta=0.0,
            risk_binding="NONE",
            corr_regime="NORMAL",
            scenario_gross=1.0,
        )

        self.assertEqual(gate["status"], "BLOCK")

    def test_gate_warns_on_material_drift_and_extreme_corr(self):
        gate = _gate_row(
            r3_violations=0,
            route_gross=1.0,
            max_symbol_delta=0.12,
            max_leg_delta=0.0,
            turnover_delta=0.11,
            risk_binding="EXTREME_CORR",
            corr_regime="EXTREME",
            scenario_gross=0.62,
        )

        self.assertEqual(gate["status"], "WARN")
        self.assertTrue(any("max symbol delta" in reason for reason in gate["reasons"]))
        self.assertTrue(any("EXTREME_CORR" in reason for reason in gate["reasons"]))

    def test_gate_passes_quiet_rows(self):
        gate = _gate_row(
            r3_violations=0,
            route_gross=1.0,
            max_symbol_delta=0.02,
            max_leg_delta=0.03,
            turnover_delta=0.01,
            risk_binding="NONE",
            corr_regime="NORMAL",
            scenario_gross=0.9,
        )

        self.assertEqual(gate["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
