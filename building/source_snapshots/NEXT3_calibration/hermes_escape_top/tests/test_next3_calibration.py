from __future__ import annotations

import unittest

from hermes_escape_top.scripts.calibrate_next3_v2 import (
    _fixed_rank_profiles,
    pbo_from_rank_percentiles,
    rank_percentile,
    threshold_grid,
)


class Next3CalibrationHelpersTest(unittest.TestCase):
    def test_rank_percentile_treats_best_as_one(self) -> None:
        self.assertAlmostEqual(rank_percentile([1.0, 3.0, 2.0], 1), 1.0)
        self.assertAlmostEqual(rank_percentile([1.0, 3.0, 2.0], 0), 0.0)

    def test_pbo_counts_train_selected_under_median_oos(self) -> None:
        self.assertAlmostEqual(pbo_from_rank_percentiles([1.0, 0.75, 0.25, 0.0]), 0.5)

    def test_threshold_grid_respects_ordering(self) -> None:
        combos = threshold_grid(exit_vals=(80,), def_exit_vals=(60, 85), reduce_vals=(55, 65))
        self.assertEqual(len(combos), 1)
        self.assertEqual(combos[0].key(), "E80_D60_R55")

    def test_fixed_rank_profiles_prefers_low_below_median_rate(self) -> None:
        combos = threshold_grid(exit_vals=(80,), def_exit_vals=(60,), reduce_vals=(45, 50))
        ranks = {
            "E80_D60_R45": [0.40, 0.60, 0.90],
            "E80_D60_R50": [0.55, 0.60, 0.65],
        }
        profiles = _fixed_rank_profiles(combos, ranks)
        self.assertEqual(profiles[0]["combo"], "E80_D60_R50")
        self.assertAlmostEqual(profiles[0]["fixed_pbo"], 0.0)


if __name__ == "__main__":
    unittest.main()
