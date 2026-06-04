from __future__ import annotations

import unittest

from hermes_escape_top.config import load_config
from hermes_escape_top.core.decision.verdict import VerdictInput, at_least, make_verdict, upgrade_one


class Phase5VerdictTest(unittest.TestCase):
    def test_hard_valve_bypasses_confirmation(self) -> None:
        config = load_config()
        verdict = make_verdict(
            VerdictInput(symbol="MSTR", score=10, module_scores={}, hard_valve_hits=["H-M1"], previous_status="HOLD"),
            config,
            require_confirmation=True,
        )
        self.assertEqual(verdict.status, "EXIT")
        self.assertEqual(verdict.sell_fraction, 1.0)
        self.assertFalse(verdict.confirmation_required)

    def test_missing_blind_spot_upgrades_one_level(self) -> None:
        config = load_config()
        verdict = make_verdict(VerdictInput(symbol="SOXL", score=21, module_scores={}, missing_weight=42), config)
        self.assertEqual(verdict.status, "TRIM")

    def test_c_module_floor_sets_minimum_reduce(self) -> None:
        config = load_config()
        verdict = make_verdict(VerdictInput(symbol="MSTR", score=25, module_scores={"C": 18}, missing_weight=0), config)
        self.assertEqual(verdict.status, "REDUCE")

    def test_soft_upgrade_confirmation_can_hold_at_watch(self) -> None:
        config = load_config()
        verdict = make_verdict(
            VerdictInput(symbol="FNGU", score=55, module_scores={}, previous_status="HOLD"),
            config,
            require_confirmation=True,
        )
        self.assertEqual(verdict.status, "WATCH")
        self.assertTrue(verdict.confirmation_required)

    def test_ladder_helpers(self) -> None:
        self.assertEqual(at_least("WATCH", "REDUCE"), "REDUCE")
        self.assertEqual(at_least("EXIT", "REDUCE"), "EXIT")
        self.assertEqual(upgrade_one("WATCH"), "TRIM")
        self.assertEqual(upgrade_one("EXIT"), "EXIT")


if __name__ == "__main__":
    unittest.main()
