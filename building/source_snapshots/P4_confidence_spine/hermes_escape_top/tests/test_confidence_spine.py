from __future__ import annotations

import unittest

from hermes_escape_top.core.confidence import compute_confidence
from hermes_escape_top.core.contracts import ConfidenceState


class ConfidenceSpineTest(unittest.TestCase):
    def test_healthy_inputs_are_normal(self) -> None:
        state = compute_confidence(
            data_conf=1.0,
            failover_state={"is_degraded": False},
            staleness_days=0,
            drift_state={"psi": 0.0, "alert": False},
            fragility=0.0,
            disagreement=0.0,
            cfg={},
        )
        self.assertIsInstance(state, ConfidenceState)
        self.assertEqual(state.mode, "NORMAL")
        self.assertAlmostEqual(state.decision_confidence, 1.0)
        self.assertEqual(state.weakest_link, "data")

    def test_source_failover_moves_to_caution(self) -> None:
        state = compute_confidence(
            data_conf=1.0,
            failover_state={"is_degraded": True, "active_source_rank": 2},
            staleness_days=0,
            drift_state={"psi": 0.0, "alert": False},
            fragility=0.0,
            disagreement=0.0,
            cfg={},
        )
        self.assertEqual(state.mode, "CAUTION")
        self.assertEqual(state.weakest_link, "source")
        self.assertIn("source failover active; rank=2", state.notes)

    def test_drift_alert_forces_degraded(self) -> None:
        state = compute_confidence(
            data_conf=1.0,
            failover_state={"is_degraded": False},
            staleness_days=0,
            drift_state={"psi": 0.01, "alert": True},
            fragility=0.0,
            disagreement=0.0,
            cfg={},
        )
        self.assertEqual(state.mode, "DEGRADED")
        self.assertEqual(state.components["drift"], 0.0)
        self.assertEqual(state.weakest_link, "drift")

    def test_missing_subsignals_are_neutral_not_safe(self) -> None:
        state = compute_confidence(
            data_conf=None,
            failover_state=None,
            staleness_days=None,
            drift_state=None,
            fragility=None,
            disagreement=None,
            cfg={},
        )
        self.assertEqual(state.mode, "DEGRADED")
        self.assertTrue(any("missing" in note for note in state.notes))
        self.assertLess(state.decision_confidence, 0.55)


if __name__ == "__main__":
    unittest.main()
