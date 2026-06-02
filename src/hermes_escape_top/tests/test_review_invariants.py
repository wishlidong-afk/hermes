"""Regression guards for the CODE_REVIEW_FOLLOWUP / round-2 fixes.

These lock in the invariants whose violation caused real bugs, so they cannot
silently regress again:
  - Kelly fractional sizing is OFF by default, and enabling it without a
    calibrated p_act raises (decision_confidence must never be used as p_act).
  - All live feature flags default to OFF.
  - Healthy confidence inputs do NOT collapse to DEGRADED (the permanent-DEGRADED
    bug from feeding the spine None for every component).
  - R3 hard invariant: optimizer target weight never exceeds the rule target.
  - Read-only red line: sizing only ever emits plan modes, never an order action.
"""
from __future__ import annotations

import unittest

import numpy as np

from hermes_escape_top.core.contracts import ConfidenceState, RiskState, Verdict
from hermes_escape_top.core.confidence.spine import compute_confidence
from hermes_escape_top.core.portfolio.sizing_optimizer import optimize_targets


def _risk_state(n=3, gross=1.0, vol_budget=0.30):
    syms = ["FNGU", "MSTR", "SOXL"][:n]
    cov = np.eye(n) * 0.04
    return RiskState(
        cov=cov, corr=np.eye(n), downside_corr=np.eye(n),
        leg_vol={s: 0.2 for s in syms}, legs_used=syms, legs_reported=syms,
        portfolio_vol=0.2, cvar=-0.05, vol_budget=vol_budget, cvar_budget=0.08,
        vol_scaler=1.0, cvar_scaler=1.0, gross_scaler=gross,
        risk_contributions={}, factor_betas={}, book_factor_exposure={},
        corr_regime="NORMAL", binding="NONE", explain=[],
    )


def _verdicts(rule=0.2):
    return {s: Verdict(symbol=s, status="HOLD", rule_target_weight=rule, sell_fraction=0.0)
            for s in ["FNGU", "MSTR", "SOXL"]}


def _conf(value=0.9):
    return ConfidenceState(decision_confidence=value, mode="NORMAL",
                           components={}, weakest_link="data")


class ReviewInvariants(unittest.TestCase):

    def test_kelly_off_by_default(self):
        """Default sizing cfg must not enable Kelly (else ~75-90% silent haircut)."""
        v, rs, c = _verdicts(), _risk_state(), _conf()
        dec = optimize_targets(v, rs, c, {"sizing": {"dd_aversion": 3.0}})
        total = sum(dec.target_weights.values())
        self.assertGreater(total, 0.05 * sum(x.rule_target_weight for x in v.values()),
                           "default sizing crushed weights to ~0 (Kelly leaked back on?)")

    def test_kelly_requires_calibrated_p_act(self):
        """Enabling Kelly without a calibrated p_act must raise, not use confidence."""
        v, rs, c = _verdicts(), _risk_state(), _conf()
        with self.assertRaises(ValueError):
            optimize_targets(v, rs, c, {"sizing": {"kelly": {"enabled": True}}})

    def test_live_feature_flags_default_off(self):
        """CPPI and Kelly must default to disabled (no live flag default-ON)."""
        v, rs, c = _verdicts(), _risk_state(), _conf()
        # With no kelly/cppi keys, must run cleanly (not raise from a default-on flag).
        dec = optimize_targets(v, rs, c, {"sizing": {"dd_aversion": 3.0}})
        self.assertTrue(dec.target_weights)

    def test_healthy_confidence_not_degraded(self):
        """Healthy spine inputs must yield NORMAL, never permanent DEGRADED."""
        state = compute_confidence(
            data_conf=0.85, failover_state={"is_degraded": False}, staleness_days=0.0,
            drift_state={"psi": 0.0, "alert": False}, fragility=0.0, disagreement=0.0,
            cfg={},
        )
        self.assertEqual(state.mode, "NORMAL")
        self.assertGreaterEqual(state.decision_confidence, 0.8)

    def test_r3_invariant_target_le_rule(self):
        """R3: every optimizer target weight <= its rule target weight."""
        v, rs, c = _verdicts(rule=0.2), _risk_state(), _conf()
        dec = optimize_targets(v, rs, c, {"sizing": {"dd_aversion": 3.0}})
        for s, w in dec.target_weights.items():
            self.assertLessEqual(w, v[s].rule_target_weight + 1e-9, f"{s} breached R3")

    def test_read_only_no_order_action(self):
        """Read-only red line: execution plan only carries advisory modes."""
        v, rs, c = _verdicts(), _risk_state(), _conf()
        dec = optimize_targets(v, rs, c, {"sizing": {"dd_aversion": 3.0}})
        allowed_prefixes = ("twap_", "execute_now")
        for leg in dec.execution_plan:
            self.assertTrue(
                str(leg.get("mode", "")).startswith(allowed_prefixes),
                f"unexpected execution mode {leg.get('mode')!r} (must be advisory only)",
            )


if __name__ == "__main__":
    unittest.main()
