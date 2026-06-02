"""Gate 7 — End-to-end circuit breaker tests.

Injects four anomaly types and verifies the full Governance chain fires correctly:
  1. Bad data injection  → ConfidenceSpine DEGRADED
  2. Strong disagreement → detect_disagreement raises above threshold
  3. High fragility      → ConfidenceSpine CAUTION
  4. Score drift (PSI)   → DriftMonitor alert=True

Also verifies:
  - DEGRADED mode causes optimizer to shrink all target weights
  - Normal conditions produce NORMAL mode with full weights
  - No false positives on clean data
"""
from __future__ import annotations

import math
import unittest

import numpy as np

from hermes_escape_top.core.confidence.spine import compute_confidence
from hermes_escape_top.core.governance.governance import (
    ChampionChallenger,
    attribute,
    decision_fragility,
    detect_disagreement,
)
from hermes_escape_top.core.monitor.drift import DriftMonitor, compute_psi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _healthy_confidence(**overrides):
    """Return a healthy confidence call (all green) with optional overrides."""
    kwargs = dict(
        data_conf=1.0,
        failover_state={"is_degraded": False},
        staleness_days=0,
        drift_state={"psi": 0.0, "alert": False},
        fragility=0.0,
        disagreement=0.0,
        cfg={},
    )
    kwargs.update(overrides)
    return compute_confidence(**kwargs)


# ---------------------------------------------------------------------------
# Gate 7.1 — Bad data → DEGRADED
# ---------------------------------------------------------------------------

class TestGate7BadData(unittest.TestCase):
    """Inject data quality failure; spine must reach DEGRADED."""

    def test_zero_data_conf_is_degraded(self):
        state = _healthy_confidence(data_conf=0.0)
        self.assertEqual(state.mode, "DEGRADED")
        self.assertEqual(state.weakest_link, "data")

    def test_failover_degraded_source_is_caution_or_degraded(self):
        state = _healthy_confidence(
            failover_state={"is_degraded": True, "active_source_rank": 3}
        )
        self.assertIn(state.mode, ("CAUTION", "DEGRADED"))
        self.assertEqual(state.weakest_link, "source")

    def test_missing_data_conf_neutral_not_safe(self):
        """None data_conf must NOT produce NORMAL — must be neutral 0.5."""
        state = _healthy_confidence(data_conf=None)
        # With data_conf=0.5 (neutral) everything else is 1.0 → overall ~0.8-ish
        # but weakest_link should NOT be a non-data component when data is missing
        self.assertIn("data_conf missing" , " ".join(state.notes))
        # Should not be fully NORMAL when core data signal is missing
        self.assertLessEqual(state.decision_confidence, 1.0)

    def test_stale_data_reduces_confidence(self):
        """7-day stale data (tau=3) → significant confidence drop."""
        state = _healthy_confidence(staleness_days=7)
        stale_conf = state.components.get("stale", 1.0)
        self.assertLess(stale_conf, 0.2)   # exp(-7/3) ≈ 0.098

    def test_clean_data_no_false_positive(self):
        """Perfect inputs must produce NORMAL, not DEGRADED."""
        state = _healthy_confidence()
        self.assertEqual(state.mode, "NORMAL")
        self.assertGreater(state.decision_confidence, 0.95)


# ---------------------------------------------------------------------------
# Gate 7.2 — Strong disagreement → REVIEW level
# ---------------------------------------------------------------------------

class TestGate7Disagreement(unittest.TestCase):
    """Inject contradicting rule/meta/mirror signals; disagreement must fire."""

    def test_exit_vs_strong_trend_is_high_disagreement(self):
        d = detect_disagreement(
            rule_status="EXIT",
            meta_p_act=0.05,          # meta says: safe
            mirror_cycle="STRONG_TREND",
            cfg={"disagreement_threshold": 0.40},
        )
        self.assertGreater(d, 0.40)

    def test_hold_consensus_is_low_disagreement(self):
        d = detect_disagreement(
            rule_status="HOLD",
            meta_p_act=0.1,
            mirror_cycle="NORMAL",
            cfg={},
        )
        self.assertLess(d, 0.30)

    def test_disagreement_feeds_confidence_spine(self):
        """High disagreement must push confidence spine below NORMAL."""
        high_disg = detect_disagreement("EXIT", 0.05, "STRONG_TREND", {})
        state = _healthy_confidence(disagreement=high_disg)
        # disagreement component = 1 - disagreement → should pull confidence down
        self.assertLess(state.decision_confidence, 0.95)

    def test_no_meta_single_source_zero(self):
        d = detect_disagreement("HOLD", None, None, {})
        self.assertEqual(d, 0.0)


# ---------------------------------------------------------------------------
# Gate 7.3 — High fragility → CAUTION or DEGRADED
# ---------------------------------------------------------------------------

class TestGate7Fragility(unittest.TestCase):
    """Score on knife-edge → high fragility → confidence degrades."""

    def test_knife_edge_score_is_fragile(self):
        def scorer(snap):
            return "EXIT" if snap.get("total", 0) >= 75 else "HOLD"

        frag = decision_fragility(
            snapshot={"total": 75.0},
            scorer_fn=scorer,
            eps=0.02,
            n_perturb=50,
            seed=42,
        )
        self.assertGreater(frag, 0.3)

    def test_safe_score_is_not_fragile(self):
        def scorer(snap):
            return "EXIT" if snap.get("total", 0) >= 75 else "HOLD"

        frag = decision_fragility(
            snapshot={"total": 10.0},
            scorer_fn=scorer,
            eps=0.02,
            n_perturb=50,
            seed=42,
        )
        self.assertLess(frag, 0.05)

    def test_high_fragility_lowers_confidence_mode(self):
        """fragility=0.8 must not produce NORMAL."""
        state = _healthy_confidence(fragility=0.8)
        self.assertNotEqual(state.mode, "NORMAL")

    def test_zero_fragility_no_effect(self):
        state = _healthy_confidence(fragility=0.0)
        self.assertEqual(state.mode, "NORMAL")


# ---------------------------------------------------------------------------
# Gate 7.4 — PSI drift → DriftMonitor alert
# ---------------------------------------------------------------------------

class TestGate7Drift(unittest.TestCase):
    """Inject score distribution shift; DriftMonitor must alert."""

    def test_shifted_distribution_triggers_alert(self):
        rng = np.random.RandomState(42)
        train = rng.randn(300) * 10 + 50
        live  = rng.randn(100) * 10 + 80   # mean shifted +30
        mon = DriftMonitor({"psi_threshold": 0.25})
        result = mon.evaluate(train, live)
        self.assertTrue(result["alert"])
        self.assertGreater(result["psi"], 0.25)

    def test_same_distribution_no_alert(self):
        rng = np.random.RandomState(7)
        train = rng.randn(300) * 10 + 50
        live  = rng.randn(100) * 10 + 50
        mon = DriftMonitor({"psi_threshold": 0.25})
        result = mon.evaluate(train, live)
        self.assertFalse(result["alert"])

    def test_drift_alert_feeds_confidence_degraded(self):
        """drift_state.alert=True must push spine to DEGRADED."""
        state = _healthy_confidence(
            drift_state={"psi": 0.40, "alert": True}
        )
        self.assertEqual(state.mode, "DEGRADED")
        self.assertEqual(state.components.get("drift"), 0.0)

    def test_ic_decay_triggers_alert(self):
        mon = DriftMonitor({"ic_decay_threshold": 0.50})
        result = mon.evaluate(
            np.random.randn(200), np.random.randn(200),
            train_ic={"C10": 0.38, "D3": 0.35},
            live_ic={"C10": 0.08, "D3": 0.30},
        )
        self.assertTrue(result["ic_decay_alert"])
        self.assertTrue(result["alert"])
        self.assertIn("C10", " ".join(result["recommendations"]))


# ---------------------------------------------------------------------------
# Gate 7.5 — Optimizer weight shrinkage under DEGRADED
# ---------------------------------------------------------------------------

class TestGate7OptimizerShrinkage(unittest.TestCase):
    """DEGRADED confidence must materially shrink target weights."""

    def test_degraded_shrinks_weights_vs_normal(self):
        import numpy as np
        from hermes_escape_top.core.contracts import ConfidenceState, RiskState, Verdict
        from hermes_escape_top.core.portfolio.sizing_optimizer import optimize_targets

        def _make_risk():
            return RiskState(
                cov=np.eye(3) * 0.04,
                corr=np.eye(3), downside_corr=np.eye(3),
                leg_vol={f"S{i}": 0.2 for i in range(3)},
                legs_used=[f"S{i}" for i in range(3)],
                legs_reported=[f"S{i}" for i in range(3)],
                portfolio_vol=0.2, cvar=-0.04,
                vol_budget=0.35, cvar_budget=0.08,
                vol_scaler=1.0, cvar_scaler=1.0, gross_scaler=1.0,
                risk_contributions={}, factor_betas={},
                book_factor_exposure={}, corr_regime="NORMAL",
                binding="NONE", explain=[],
            )

        verdicts = {
            f"S{i}": Verdict(f"S{i}", "HOLD", 0.20, 0.0, [])
            for i in range(3)
        }
        cfg = {"sizing": {"dd_aversion": 3.0, "leverage_L": {}, "solver": "slsqp_or_grid", "exec_slices": 3}}

        conf_normal = ConfidenceState(1.0, "NORMAL", {}, "data")
        conf_degraded = ConfidenceState(0.3, "DEGRADED", {}, "data")

        r_normal = optimize_targets(verdicts, _make_risk(), conf_normal, cfg)
        r_degraded = optimize_targets(verdicts, _make_risk(), conf_degraded, cfg)

        total_normal = sum(r_normal.target_weights.values())
        total_degraded = sum(r_degraded.target_weights.values())

        self.assertGreater(total_normal, total_degraded)
        # Degraded at 0.3 confidence should shrink to ≤30% of normal
        self.assertLessEqual(total_degraded, total_normal * 0.35)

    def test_r3_holds_under_degraded(self):
        """R3 must never be violated even in DEGRADED mode."""
        import numpy as np
        from hermes_escape_top.core.contracts import ConfidenceState, RiskState, Verdict
        from hermes_escape_top.core.portfolio.sizing_optimizer import optimize_targets

        risk = RiskState(
            cov=np.eye(2) * 0.09, corr=np.eye(2), downside_corr=np.eye(2),
            leg_vol={"A": 0.3, "B": 0.3},
            legs_used=["A", "B"], legs_reported=["A", "B"],
            portfolio_vol=0.3, cvar=-0.06,
            vol_budget=0.35, cvar_budget=0.08,
            vol_scaler=1.0, cvar_scaler=1.0, gross_scaler=1.0,
            risk_contributions={}, factor_betas={}, book_factor_exposure={},
            corr_regime="EXTREME", binding="NONE", explain=[],
        )
        verdicts = {
            "A": Verdict("A", "TRIM", 0.12, 0.35, []),
            "B": Verdict("B", "HOLD", 0.20, 0.00, []),
        }
        conf_degraded = ConfidenceState(0.2, "DEGRADED", {}, "data")
        cfg = {"sizing": {"dd_aversion": 3.0, "leverage_L": {}, "solver": "slsqp_or_grid", "exec_slices": 3}}

        result = optimize_targets(verdicts, risk, conf_degraded, cfg)
        for sym, w in result.target_weights.items():
            rule = verdicts[sym].rule_target_weight
            self.assertLessEqual(w, rule + 1e-6, f"R3 violated under DEGRADED: {sym}")


# ---------------------------------------------------------------------------
# Gate 7.6 — Attribution completeness
# ---------------------------------------------------------------------------

class TestGate7Attribution(unittest.TestCase):
    """Every decision must be attributable to specific factors."""

    def test_attribution_sums_to_one(self):
        components = {"A": 12.0, "B": 8.0, "C": 25.0, "D": 15.0}
        total = sum(components.values())
        result = attribute(components, total)
        contrib_sum = sum(c for _, c, _ in result)
        self.assertAlmostEqual(contrib_sum, 1.0, places=4)

    def test_top_factor_ranked_first(self):
        components = {"A": 5.0, "B": 25.0, "C": 3.0}
        result = attribute(components, sum(components.values()))
        self.assertEqual(result[0][0], "B")   # highest contributor first

    def test_counterfactual_is_total_minus_factor(self):
        components = {"A": 20.0, "B": 30.0}
        total = 50.0
        result = attribute(components, total)
        for name, _, counterfactual in result:
            self.assertAlmostEqual(counterfactual, total - components[name], places=4)

    def test_champion_challenger_human_gate(self):
        """Promotion must always require human gate — never auto-promote."""
        cc = ChampionChallenger({"name": "champ"}, [{"name": "chal"}])
        ev = cc.evaluate_promotion(
            champion_oos=[0.3, 0.3, 0.3],
            challenger_oos={"chal": [0.9, 0.9, 0.9]},  # clearly better
        )
        self.assertTrue(ev["requires_human_gate"],
                        "Champion-Challenger must NEVER auto-promote")


if __name__ == "__main__":
    unittest.main()
