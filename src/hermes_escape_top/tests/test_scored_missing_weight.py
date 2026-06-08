from __future__ import annotations

import copy
import unittest

from hermes_escape_top.config import load_config
from hermes_escape_top.core.scoring.scorer import score_symbol

# Reuse the shared fixture from the phase-3 scoring tests.
from test_phase3_scoring import confidence_snapshots


class ScoredMissingWeightTest(unittest.TestCase):
    """F5/F6: when use_scored_missing_weight is on, permanently-unwired placeholders
    (A2 CNN, B5, D-M4, D-M5) no longer inflate the operational missing weight that
    drives blind-spot escalation and score scaling."""

    def test_default_off_uses_full_missing_weight(self) -> None:
        cfg = load_config()  # flag off
        result = score_symbol("MSTR", confidence_snapshots(), cfg).result
        # Full missing weight includes the non-scoring placeholders.
        self.assertGreater(result.missing_weight, result.confidence_missing_weight)

    def test_on_drops_placeholders_from_operational_weight(self) -> None:
        cfg = copy.deepcopy(load_config())
        cfg["features"]["use_scored_missing_weight"] = True
        result = score_symbol("MSTR", confidence_snapshots(), cfg).result
        # Operational missing weight now equals the scoring-only (confidence) weight.
        self.assertEqual(result.missing_weight, result.confidence_missing_weight)
        # Placeholders are still reported as non-scoring (transparency preserved).
        self.assertIn("A2 cnn_fear_greed", result.non_scoring_missing_fields)

    def test_on_lowers_or_equals_final_score(self) -> None:
        """Removing placeholder inflation can only reduce (never raise) the score,
        because effective_max grows when missing weight shrinks."""
        base = load_config()
        on = copy.deepcopy(base)
        on["features"]["use_scored_missing_weight"] = True
        snaps = confidence_snapshots()
        off_score = score_symbol("MSTR", snaps, base).result.final_score
        on_score = score_symbol("MSTR", confidence_snapshots(), on).result.final_score
        self.assertLessEqual(on_score, off_score + 1e-9)


if __name__ == "__main__":
    unittest.main()
