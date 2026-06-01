import unittest

from hermes_escape_top.scripts.phase3_warn_sensitivity import (
    _find_scenario,
    _parse_float_list,
    _parse_int_list,
    _pick_review_candidates,
    _rows_for_price_frame,
    _scenario_readiness,
    _scenario_review_score,
)


class Phase3WarnSensitivityTests(unittest.TestCase):
    def test_parse_lists(self):
        self.assertEqual(_parse_float_list("100, 110,120"), [100.0, 110.0, 120.0])
        self.assertEqual(_parse_int_list("1,5, 10"), [1, 5, 10])

    def test_review_score_blocks_invariant_failures(self):
        score = _scenario_review_score({"r3_violations": 1, "gate_counts": {}, "warn_forward_stats": {}})

        self.assertEqual(score, 999.0)

    def test_review_score_penalizes_low_defense_and_negative_drag(self):
        summary = {
            "r3_violations": 0,
            "gate_counts": {"BLOCK": 0},
            "warn_forward_stats": {"10": {"mean": -0.01}},
            "warn_share": 0.6,
            "extreme_corr_share": 0.1,
            "max_abs_turnover_delta": 0.35,
        }

        score = _scenario_review_score(summary)

        self.assertGreater(score, 1.0)

    def test_readiness_states(self):
        self.assertEqual(_scenario_readiness({"r3_violations": 1, "gate_counts": {}}), "BLOCKED")
        self.assertEqual(
            _scenario_readiness({"r3_violations": 0, "gate_counts": {"BLOCK": 0}, "max_abs_turnover_delta": 0.4}),
            "REVIEW_REQUIRED",
        )
        self.assertEqual(
            _scenario_readiness({"r3_violations": 0, "gate_counts": {"BLOCK": 0}, "max_abs_turnover_delta": 0.1, "extreme_corr_share": 0.1}),
            "TOO_RELAXED_REVIEW",
        )
        self.assertEqual(
            _scenario_readiness({"r3_violations": 0, "gate_counts": {"BLOCK": 0}, "max_abs_turnover_delta": 0.1, "extreme_corr_share": 0.3, "penalty": 1.0}),
            "NO_PENALTY_REVIEW",
        )
        self.assertEqual(
            _scenario_readiness({"r3_violations": 0, "gate_counts": {"BLOCK": 0}, "max_abs_turnover_delta": 0.1, "extreme_corr_share": 0.3, "penalty": 0.9}),
            "REVIEW_READY",
        )

    def test_pick_review_candidates(self):
        scenarios = [
            {
                "threshold": 110.0,
                "penalty": 0.7,
                "review_score": 0.5,
                "warn_share": 0.4,
                "extreme_corr_share": 0.4,
                "warn_forward_stats": {"10": {"mean": -0.002}},
                "max_abs_turnover_delta": 0.2,
                "r3_violations": 0,
                "gate_counts": {"BLOCK": 0},
                "readiness": "REVIEW_READY",
            },
            {
                "threshold": 150.0,
                "penalty": 1.0,
                "review_score": 0.1,
                "warn_share": 0.05,
                "extreme_corr_share": 0.05,
                "warn_forward_stats": {"10": {"mean": 0.0}},
                "max_abs_turnover_delta": 0.1,
                "r3_violations": 0,
                "gate_counts": {"BLOCK": 0},
                "readiness": "TOO_RELAXED_REVIEW",
            },
        ]

        picks = _pick_review_candidates(scenarios)

        self.assertEqual(picks["current_110_070"]["threshold"], 110.0)
        self.assertEqual(picks["balanced_lowest_score"]["threshold"], 110.0)
        self.assertEqual(picks["lowest_warn_share"]["threshold"], 150.0)
        self.assertIs(_find_scenario(scenarios, 999.0, 0.7), None)

    def test_rows_for_price_frame_merges_duplicate_dates(self):
        rows = [
            {"date": "2026-01-01", "old_route_leg_weights": {"A": 1.0}, "new_route_leg_weights": {"B": 1.0}},
            {"date": "2026-01-01", "old_route_leg_weights": {"C": 1.0}, "new_route_leg_weights": {"D": 1.0}},
            {"date": "2026-01-02", "old_route_leg_weights": {"A": 1.0}, "new_route_leg_weights": {"B": 1.0}},
        ]

        merged = _rows_for_price_frame(rows)

        self.assertEqual([row["date"] for row in merged], ["2026-01-01", "2026-01-02"])
        self.assertEqual(set(merged[0]["old_route_leg_weights"]), {"A", "C"})
        self.assertEqual(set(merged[0]["new_route_leg_weights"]), {"B", "D"})


if __name__ == "__main__":
    unittest.main()
