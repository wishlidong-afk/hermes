"""Tests for SizingOptimizer -- the single sizing entry point.

Test matrix (per INTEGRATION_ARCHITECTURE §7.3):
  1. R3 invariant: w_i <= rule_target_weight, 100%
  2. High vol → lower weights
  3. Infeasible → most conservative
  4. Binding constraints labeled correctly
  5. Grid fallback matches SLSQP (within tolerance)
  6. Hard valve → execute_now mode
  7. Confidence shrinkage applied
  8. Deterministic: same input → same output
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from hermes_escape_top.core.contracts import (
    ConfidenceState,
    RiskState,
    SizingDecision,
    Verdict,
)
from hermes_escape_top.core.portfolio.sizing_optimizer import (
    cppi_exposure_cap,
    dd_averse_utility,
    expected_leg_return,
    kelly_fraction,
    liquidity_cap,
    optimize_targets,
)


def _make_risk_state(
    vol: float = 0.3,
    n: int = 3,
    vol_budget: float = 0.35,
    cvar_budget: float = 0.08,
) -> RiskState:
    cov = np.eye(n) * (vol ** 2)
    return RiskState(
        cov=cov,
        corr=np.eye(n),
        downside_corr=np.eye(n),
        leg_vol={f"SYM_{i}": vol for i in range(n)},
        legs_used=[f"SYM_{i}" for i in range(n)],
        legs_reported=[f"SYM_{i}" for i in range(n)],
        portfolio_vol=vol,
        cvar=-0.05,
        vol_budget=vol_budget,
        cvar_budget=cvar_budget,
        vol_scaler=min(1.0, vol_budget / max(vol, 1e-9)),
        cvar_scaler=1.0,
        gross_scaler=min(1.0, vol_budget / max(vol, 1e-9)),
        risk_contributions={},
        factor_betas={},
        book_factor_exposure={},
        corr_regime="NORMAL",
        binding="NONE",
        explain=[],
    )


def _make_verdicts(n: int = 3, status: str = "HOLD", rule_weight: float = 0.2) -> dict:
    return {
        f"SYM_{i}": Verdict(
            symbol=f"SYM_{i}",
            status=status,
            rule_target_weight=rule_weight,
            sell_fraction=0.0,
            hard_valve_hits=[],
        )
        for i in range(n)
    }


def _make_confidence(conf: float = 1.0, mode: str = "NORMAL") -> ConfidenceState:
    return ConfidenceState(
        decision_confidence=conf,
        mode=mode,
        components={},
        weakest_link="data",
    )


def _base_cfg() -> dict:
    return {
        "sizing": {
            "dd_aversion": 3.0,
            "leverage_L": {"SYM_0": 3.0, "SYM_1": 3.0, "SYM_2": 1.0},
            "solver": "slsqp_or_grid",
            "exec_slices": 3,
        }
    }


class TestExpectedLegReturn(unittest.TestCase):
    def test_decay_reduces_return(self) -> None:
        mu_no_decay = expected_leg_return("X", 0.3, 1.0, 20, 0.1, {})
        mu_with_decay = expected_leg_return("X", 0.3, 3.0, 20, 0.1, {})
        self.assertLess(mu_with_decay, mu_no_decay)


class TestKellyFraction(unittest.TestCase):
    def test_positive_edge(self) -> None:
        f = kelly_fraction(0.6, 2.0, frac=0.3)
        self.assertGreater(f, 0.0)
        self.assertLessEqual(f, 1.0)

    def test_no_edge(self) -> None:
        f = kelly_fraction(0.3, 1.0, frac=0.3)
        self.assertEqual(f, 0.0)


class TestLiquidityCap(unittest.TestCase):
    def test_returns_reasonable_cap(self) -> None:
        cap = liquidity_cap(adv20=1_000_000, price=50, netliq=5_000_000, cfg={"max_liquidation_days": 3, "participation_rate": 0.10})
        self.assertGreater(cap, 0.0)
        self.assertLessEqual(cap, 1.0)

    def test_zero_adv_returns_zero(self) -> None:
        cap = liquidity_cap(adv20=0, price=50, netliq=5_000_000, cfg={})
        self.assertEqual(cap, 0.0)


class TestCppiExposureCap(unittest.TestCase):
    def test_positive_cushion(self) -> None:
        cap = cppi_exposure_cap(equity=1_000_000, floor=800_000, multiplier=3.0)
        self.assertAlmostEqual(cap, 600_000, places=0)

    def test_at_floor(self) -> None:
        cap = cppi_exposure_cap(equity=800_000, floor=800_000, multiplier=3.0)
        self.assertEqual(cap, 0.0)


class TestDdAverseUtility(unittest.TestCase):
    def test_higher_return_higher_utility(self) -> None:
        cov = np.eye(2) * 0.04
        u1 = dd_averse_utility(np.array([0.3, 0.3]), np.array([0.05, 0.05]), cov, 3.0)
        u2 = dd_averse_utility(np.array([0.3, 0.3]), np.array([0.10, 0.10]), cov, 3.0)
        self.assertGreater(u2, u1)


class TestOptimizeTargets(unittest.TestCase):
    def test_r3_invariant(self) -> None:
        """w_i <= rule_target_weight for ALL i, always."""
        verdicts = _make_verdicts(3, rule_weight=0.15)
        risk = _make_risk_state(vol=0.2)
        conf = _make_confidence(1.0)
        result = optimize_targets(verdicts, risk, conf, _base_cfg())
        for sym, w in result.target_weights.items():
            self.assertLessEqual(w, 0.15 + 1e-6, f"R3 violated for {sym}")
            self.assertGreaterEqual(w, 0.0)

    def test_high_vol_reduces_weights(self) -> None:
        verdicts = _make_verdicts(3, rule_weight=0.3)
        risk_low = _make_risk_state(vol=0.1)
        risk_high = _make_risk_state(vol=0.8)
        conf = _make_confidence(1.0)
        r_low = optimize_targets(verdicts, risk_low, conf, _base_cfg())
        r_high = optimize_targets(verdicts, risk_high, conf, _base_cfg())
        total_low = sum(r_low.target_weights.values())
        total_high = sum(r_high.target_weights.values())
        self.assertLessEqual(total_high, total_low + 0.01)

    def test_confidence_shrinkage(self) -> None:
        verdicts = _make_verdicts(3, rule_weight=0.2)
        risk = _make_risk_state(vol=0.2)
        conf_full = _make_confidence(1.0)
        conf_low = _make_confidence(0.3, mode="DEGRADED")
        r_full = optimize_targets(verdicts, risk, conf_full, _base_cfg())
        r_low = optimize_targets(verdicts, risk, conf_low, _base_cfg())
        total_full = sum(r_full.target_weights.values())
        total_low = sum(r_low.target_weights.values())
        self.assertLess(total_low, total_full)
        self.assertIn("DEGRADED", " ".join(r_low.notes))

    def test_hard_valve_execute_now(self) -> None:
        verdicts = {
            "SYM_0": Verdict("SYM_0", "EXIT", 0.0, 1.0, hard_valve_hits=["H-M1"]),
            "SYM_1": Verdict("SYM_1", "HOLD", 0.2, 0.0, hard_valve_hits=[]),
        }
        risk = _make_risk_state(vol=0.2, n=2)
        conf = _make_confidence(1.0)
        result = optimize_targets(verdicts, risk, conf, _base_cfg())
        for plan in result.execution_plan:
            if plan["symbol"] == "SYM_0":
                self.assertEqual(plan["mode"], "execute_now")
            else:
                self.assertIn("twap", plan["mode"])

    def test_empty_verdicts(self) -> None:
        result = optimize_targets({}, _make_risk_state(), _make_confidence(1.0), _base_cfg())
        self.assertEqual(len(result.target_weights), 0)
        self.assertIn("no symbols", " ".join(result.notes))

    def test_deterministic(self) -> None:
        verdicts = _make_verdicts(3, rule_weight=0.2)
        risk = _make_risk_state(vol=0.25)
        conf = _make_confidence(0.8, "CAUTION")
        r1 = optimize_targets(verdicts, risk, conf, _base_cfg())
        r2 = optimize_targets(verdicts, risk, conf, _base_cfg())
        self.assertEqual(r1.target_weights, r2.target_weights)
        self.assertEqual(r1.expected_utility, r2.expected_utility)

    def test_binding_constraints_labeled(self) -> None:
        verdicts = _make_verdicts(3, rule_weight=0.2)
        risk = _make_risk_state(vol=0.2)
        conf = _make_confidence(1.0)
        result = optimize_targets(verdicts, risk, conf, _base_cfg())
        for sym in result.binding_constraint:
            self.assertIn(
                result.binding_constraint[sym],
                ("R3_RULE", "CONFIDENCE", "VOL_BUDGET", "ZERO", "NONE"),
            )


if __name__ == "__main__":
    unittest.main()
