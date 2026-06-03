"""Regression guards for the round-2 follow-up review fixes.

Two governance signals were silently dead before these fixes; both feed the
ConfidenceSpine, so their failure quietly disabled designed safety guards:

  - detect_disagreement ignored its `disagreement_threshold` because the old
    expression `max_gap / threshold * threshold` cancels to `max_gap`. The knob
    must now actually change the output.
  - The pipeline's fragility wrapper closed over the loop symbol and re-scored the
    ORIGINAL inputs, ignoring the perturbed snapshot, so decision_fragility always
    returned 0.0 and the spine's fragility component was pinned at 1.0 forever.
    A knife-edge verdict must now produce non-zero fragility that reaches the spine.
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hermes_escape_top.core.governance.governance import detect_disagreement
from hermes_escape_top.core.pipeline import score_pipeline


class DisagreementThreshold(unittest.TestCase):

    def test_threshold_is_an_effective_knob(self):
        """A smaller disagreement_threshold must yield a larger (more sensitive)
        disagreement for the same raw gap — it must not be ignored."""
        # rule=HOLD(0.0) vs meta_p_act=0.45 -> raw max gap = 0.45
        loose = detect_disagreement("HOLD", 0.45, None, {"disagreement_threshold": 0.9})
        tight = detect_disagreement("HOLD", 0.45, None, {"disagreement_threshold": 0.45})
        self.assertLess(loose, tight, "threshold has no effect (regressed to max_gap)")
        self.assertAlmostEqual(loose, 0.5, places=4)   # 0.45 / 0.9
        self.assertAlmostEqual(tight, 1.0, places=4)   # 0.45 / 0.45, saturated

    def test_full_agreement_is_zero(self):
        self.assertEqual(detect_disagreement("HOLD", 0.0, None, {}), 0.0)


class FragilityReachesSpine(unittest.TestCase):

    @staticmethod
    def _store():
        idx = pd.date_range("2025-01-01", periods=300, freq="B")
        def mk(seed):
            rng = np.random.default_rng(seed)
            close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, len(idx)))
            return pd.DataFrame(
                {"close": close, "high": close * 1.01, "low": close * 0.99,
                 "volume": rng.integers(1_000_000, 5_000_000, len(idx))}, index=idx)
        return {s: mk(i) for i, s in enumerate(["MSTR", "FNGU", "SOXL"])}

    def test_knife_edge_verdict_is_fragile(self):
        """A total one point under the EXIT threshold must register fragility;
        a comfortable verdict must not. Before the fix every value was 0.0."""
        def scorer(sym, store, ctx, cfg):
            if sym == "MSTR":
                return {"A": 37.0, "B": 37.0, "total": 74.0}   # 1 pt under default exit=75
            return {"A": 5.0, "B": 5.0, "total": 10.0}
        res = score_pipeline("2026-02-01", self._store(),
                             {"symbols": ["MSTR", "FNGU", "SOXL"]}, scorer_fn=scorer)
        self.assertGreater(res.fragility["MSTR"], 0.0, "fragility still dead")
        self.assertEqual(res.fragility["SOXL"], 0.0, "comfortable verdict must not be fragile")
        # And it must actually flow into the confidence spine's components.
        self.assertIn("fragility", res.confidence.components)
        self.assertLess(res.confidence.components["fragility"], 1.0,
                        "fragility component pinned at 1.0 -> guard inert")


if __name__ == "__main__":
    unittest.main()
