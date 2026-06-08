from __future__ import annotations

import copy
import unittest

from hermes_escape_top.config import load_config
from hermes_escape_top.core.decision.verdict import (
    VerdictInput,
    make_verdict,
    status_from_score,
)


def _stab_config():
    cfg = copy.deepcopy(load_config())
    cfg.setdefault("features", {})["use_decision_stabilizer"] = True
    return cfg


class StatusHysteresisTest(unittest.TestCase):
    def test_default_off_is_byte_identical(self) -> None:
        cfg = load_config()
        # previous_status given but hysteresis off → flat thresholds.
        for score in (19, 20, 34, 35, 49, 50, 70, 75):
            self.assertEqual(
                status_from_score(score, cfg, previous_status="REDUCE", hysteresis=False),
                status_from_score(score, cfg),
            )

    def test_enter_threshold_unchanged_coming_from_below(self) -> None:
        cfg = _stab_config()
        # Coming from HOLD, score 34 stays below TRIM enter(35).
        self.assertEqual(status_from_score(34, cfg, previous_status="HOLD", hysteresis=True), "WATCH")
        self.assertEqual(status_from_score(35, cfg, previous_status="HOLD", hysteresis=True), "TRIM")

    def test_exit_is_sticky_when_already_elevated(self) -> None:
        cfg = _stab_config()
        # Already at REDUCE; score 45 is below REDUCE enter(50) but above exit(42)
        # → stays REDUCE (anti-chatter). Flat thresholds would drop it to TRIM.
        self.assertEqual(status_from_score(45, cfg, previous_status="REDUCE", hysteresis=True), "REDUCE")
        self.assertEqual(status_from_score(45, cfg), "TRIM")
        # Below the exit threshold it finally de-escalates.
        self.assertEqual(status_from_score(41, cfg, previous_status="REDUCE", hysteresis=True), "TRIM")


class ConfirmationTest(unittest.TestCase):
    def test_soft_upgrade_holds_then_confirms(self) -> None:
        cfg = _stab_config()
        # First close: HOLD → REDUCE is a soft upgrade → held (at least WATCH), pending.
        first = make_verdict(VerdictInput(symbol="FNGU", score=55, module_scores={}, previous_status="HOLD"), cfg)
        self.assertTrue(first.confirmation_required)
        self.assertEqual(first.status, "WATCH")
        # Second close with the prior status now REDUCE-confirmed → no longer an upgrade.
        second = make_verdict(VerdictInput(symbol="FNGU", score=55, module_scores={}, previous_status="REDUCE"), cfg)
        self.assertFalse(second.confirmation_required)
        self.assertEqual(second.status, "REDUCE")

    def test_confirmation_does_not_deescalate_existing_sell_state(self) -> None:
        cfg = _stab_config()
        # Was REDUCE, signal jumps to DEFENSIVE_EXIT (upgrade) → hold pending, but
        # must NOT drop below the already-confirmed REDUCE.
        v = make_verdict(VerdictInput(symbol="MSTR", score=72, module_scores={}, previous_status="REDUCE"), cfg)
        self.assertTrue(v.confirmation_required)
        self.assertEqual(v.status, "REDUCE")

    def test_hard_valve_bypasses_stabilizer(self) -> None:
        cfg = _stab_config()
        v = make_verdict(
            VerdictInput(symbol="MSTR", score=10, module_scores={}, hard_valve_hits=["H-M1"], previous_status="HOLD"),
            cfg,
        )
        self.assertEqual(v.status, "EXIT")
        self.assertFalse(v.confirmation_required)


if __name__ == "__main__":
    unittest.main()
