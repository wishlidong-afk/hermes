"""Tests for Governance -- disagreement, fragility, attribution, champion-challenger.

Test matrix (per INTEGRATION_ARCHITECTURE §8):
  - Strong disagreement → REVIEW_REQUIRED level
  - Low confidence → DEGRADED (via ConfidenceSpine integration)
  - Fragility near threshold → high flip rate
  - Attribution sums correctly
  - Champion always authoritative; promotion requires human gate
"""

from __future__ import annotations

import unittest

from hermes_escape_top.core.governance.governance import (
    ChampionChallenger,
    attribute,
    decision_fragility,
    detect_disagreement,
)


class TestDisagreement(unittest.TestCase):
    def test_all_agree_low(self) -> None:
        d = detect_disagreement("EXIT", 0.95, "RISK_WARNING", {})
        self.assertLess(d, 0.3)

    def test_strong_disagreement(self) -> None:
        d = detect_disagreement("EXIT", 0.1, "STRONG_TREND", {})
        self.assertGreater(d, 0.3)

    def test_single_source_zero(self) -> None:
        d = detect_disagreement("HOLD", None, None, {})
        self.assertEqual(d, 0.0)


class TestFragility(unittest.TestCase):
    def test_stable_decision_low_fragility(self) -> None:
        def scorer(snap):
            return "EXIT" if snap.get("total", 0) > 80 else "HOLD"
        frag = decision_fragility({"total": 95.0}, scorer, eps=0.02, n_perturb=50)
        self.assertLess(frag, 0.2)

    def test_knife_edge_high_fragility(self) -> None:
        def scorer(snap):
            return "EXIT" if snap.get("total", 0) > 80 else "HOLD"
        frag = decision_fragility({"total": 80.0}, scorer, eps=0.02, n_perturb=50)
        self.assertGreater(frag, 0.2)


class TestAttribution(unittest.TestCase):
    def test_contributions_sum(self) -> None:
        components = {"A": 20, "B": 15, "C": 30, "D": 10}
        total = sum(components.values())
        attr = attribute(components, total)
        contrib_sum = sum(c for _, c, _ in attr)
        self.assertAlmostEqual(contrib_sum, 1.0, places=3)

    def test_counterfactual_correct(self) -> None:
        components = {"A": 20, "B": 15}
        total = 35
        attr = attribute(components, total)
        for name, contrib, counterfactual in attr:
            self.assertAlmostEqual(counterfactual, total - components[name], places=3)

    def test_zero_total(self) -> None:
        attr = attribute({"A": 0, "B": 0}, 0)
        self.assertEqual(len(attr), 2)


class TestChampionChallenger(unittest.TestCase):
    def test_champion_authoritative(self) -> None:
        cc = ChampionChallenger(
            {"name": "champ", "param": 1},
            [{"name": "chal_a", "param": 2}],
        )
        result = cc.ensemble_decision(
            lambda snap: {"score": snap.get("param", 0) * 10},
            {},
        )
        self.assertEqual(result["authoritative"], "champion")
        self.assertIn("champion", result)
        self.assertGreater(len(result["challengers"]), 0)

    def test_promotion_requires_human_gate(self) -> None:
        cc = ChampionChallenger({"name": "champ"}, [{"name": "chal"}])
        evaluation = cc.evaluate_promotion(
            champion_oos=[0.3, 0.4, 0.35],
            challenger_oos={"chal": [0.5, 0.6, 0.55]},
        )
        self.assertTrue(evaluation["requires_human_gate"])
        self.assertEqual(evaluation["suggestion"], "promote")

    def test_no_improvement_retain(self) -> None:
        cc = ChampionChallenger({"name": "champ"}, [])
        evaluation = cc.evaluate_promotion(
            champion_oos=[0.5, 0.6],
            challenger_oos={},
        )
        self.assertEqual(evaluation["suggestion"], "retain_champion")
        self.assertTrue(evaluation["requires_human_gate"])


if __name__ == "__main__":
    unittest.main()
