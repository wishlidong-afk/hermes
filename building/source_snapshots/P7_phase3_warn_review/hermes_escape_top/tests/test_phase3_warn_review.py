import unittest

import pandas as pd

from hermes_escape_top.scripts.phase3_warn_review import (
    _categorize_reasons,
    _forward_weighted_return,
    _month_key,
    _series_stats,
    _top_delta_dict,
)


class Phase3WarnReviewTests(unittest.TestCase):
    def test_categorize_reasons_maps_known_warns(self):
        categories = _categorize_reasons(
            [
                "max symbol delta=0.1200",
                "turnover delta=-0.2500",
                "risk binding=EXTREME_CORR",
                "corr regime=EXTREME",
                "scenario gross=0.5800",
            ]
        )

        self.assertEqual(
            categories,
            ["EXTREME_CORR", "EXTREME_REGIME", "LOW_GROSS", "SYMBOL_DELTA", "TURNOVER_DELTA"],
        )

    def test_categorize_reasons_defaults_to_tolerance(self):
        self.assertEqual(_categorize_reasons(["within dry-run tolerance"]), ["TOLERANCE"])

    def test_forward_weighted_return_uses_horizon_prices(self):
        frame = pd.DataFrame(
            {
                "A": [100.0, 110.0, 121.0],
                "B": [100.0, 100.0, 90.0],
            },
            index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
        )

        one_day = _forward_weighted_return({"A": 0.5, "B": 0.5}, frame, "2026-01-01", 1)
        two_day = _forward_weighted_return({"A": 0.5, "B": 0.5}, frame, "2026-01-01", 2)

        self.assertAlmostEqual(one_day, 0.05)
        self.assertAlmostEqual(two_day, 0.055)
        self.assertIsNone(_forward_weighted_return({"A": 1.0}, frame, "2026-01-03", 1))

    def test_series_stats_and_helpers(self):
        stats = _series_stats([0.01, -0.02, 0.03])

        self.assertEqual(stats["count"], 3)
        self.assertAlmostEqual(stats["mean"], 0.006667)
        self.assertAlmostEqual(stats["median"], 0.01)
        self.assertAlmostEqual(stats["positive_share"], 2 / 3, places=6)
        self.assertEqual(_month_key("2026-05-29"), "2026-05")
        self.assertEqual(_top_delta_dict({"A": 0.1, "B": -0.2, "C": 0.0}, 2), {"B": -0.2, "A": 0.1})


if __name__ == "__main__":
    unittest.main()
