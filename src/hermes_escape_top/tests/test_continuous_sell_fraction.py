from __future__ import annotations

import copy
import unittest

from hermes_escape_top.config import load_config
from hermes_escape_top.core.decision.verdict import sell_fraction_for


def _cont_cfg():
    cfg = copy.deepcopy(load_config())
    cfg["sell_fraction_mode"] = "continuous"
    return cfg


class ContinuousSellFractionTest(unittest.TestCase):
    def test_step_mode_default_unchanged(self) -> None:
        cfg = load_config()  # step
        self.assertEqual(sell_fraction_for("FNGU", "REDUCE", cfg, score=69), 0.60)
        self.assertEqual(sell_fraction_for("FNGU", "DEFENSIVE_EXIT", cfg, score=70), 0.85)
        self.assertEqual(sell_fraction_for("MSTR", "TRIM", cfg, score=40), 0.25)

    def test_continuous_kills_the_69_70_cliff(self) -> None:
        cfg = _cont_cfg()
        # FNGU anchors: REDUCE(50→0.60), DEFENSIVE_EXIT(70→0.85). Score 69 should be
        # ~0.84 (just under 0.85), NOT a 0.60→0.85 jump.
        f69 = sell_fraction_for("FNGU", "REDUCE", cfg, score=69)
        f70 = sell_fraction_for("FNGU", "DEFENSIVE_EXIT", cfg, score=70)
        self.assertAlmostEqual(f69, 0.60 + (69 - 50) / (70 - 50) * (0.85 - 0.60), places=6)
        self.assertLess(f70 - f69, 0.02)  # the cliff is gone

    def test_continuous_is_monotonic_in_score(self) -> None:
        cfg = _cont_cfg()
        prev = -1.0
        for s in range(35, 80):
            # status derived loosely; use the natural rung so the floor never dominates.
            status = "EXIT" if s >= 75 else "DEFENSIVE_EXIT" if s >= 70 else "REDUCE" if s >= 50 else "TRIM"
            f = sell_fraction_for("FNGU", status, cfg, score=s)
            self.assertGreaterEqual(f + 1e-9, prev)
            prev = f

    def test_floor_preserves_module_forced_minimum(self) -> None:
        cfg = _cont_cfg()
        # Module-forced REDUCE at a low score (e.g. C>=18) must still sell >= step REDUCE.
        self.assertGreaterEqual(sell_fraction_for("FNGU", "REDUCE", cfg, score=25), 0.60)

    def test_watch_and_hold_never_sell(self) -> None:
        cfg = _cont_cfg()
        self.assertEqual(sell_fraction_for("FNGU", "WATCH", cfg, score=49), 0.0)
        self.assertEqual(sell_fraction_for("FNGU", "HOLD", cfg, score=10), 0.0)

    def test_no_score_falls_back_to_step(self) -> None:
        cfg = _cont_cfg()
        self.assertEqual(sell_fraction_for("FNGU", "REDUCE", cfg, score=None), 0.60)


if __name__ == "__main__":
    unittest.main()
