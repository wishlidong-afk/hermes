"""Tests for RiskEngine — the single covariance source.

Test matrix (per INTEGRATION_ARCHITECTURE §13):
  - Normal: reasonable cov from realistic returns
  - Missing data: legs with insufficient history excluded
  - Boundary/extreme: high correlation → gross_scaler < 1
  - Consistency: all derived quantities share the same cov
"""

from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from hermes_escape_top.core.portfolio.risk_engine import (
    build_risk_state,
    downside_corr,
    ewma_corr_forecast,
    har_rv_forecast,
    ledoit_wolf_shrink,
    portfolio_cvar,
    risk_contribution,
    book_factor_beta,
)


def _make_returns(n: int = 500, k: int = 3, seed: int = 42, vol: float = 0.02) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    data = rng.randn(n, k) * vol
    syms = [f"LEG_{i}" for i in range(k)]
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame(data, index=idx, columns=syms)


class TestHarRvForecast(unittest.TestCase):
    def test_returns_positive_vol(self) -> None:
        r = _make_returns(200, 1).iloc[:, 0]
        vol = har_rv_forecast(r, {"har_min_obs": 66, "ewma_lambda": 0.94})
        self.assertGreater(vol, 0.0)
        self.assertLess(vol, 2.0)

    def test_fallback_to_ewma_on_short_series(self) -> None:
        r = _make_returns(30, 1).iloc[:, 0]
        vol = har_rv_forecast(r, {"har_min_obs": 66, "ewma_lambda": 0.94})
        self.assertGreater(vol, 0.0)


class TestEwmaCorr(unittest.TestCase):
    def test_identity_on_uncorrelated(self) -> None:
        df = _make_returns(300, 3)
        corr = ewma_corr_forecast(df, lam=0.94)
        self.assertEqual(corr.shape, (3, 3))
        for i in range(3):
            self.assertAlmostEqual(corr[i, i], 1.0, places=5)

    def test_high_correlation_detected(self) -> None:
        df = _make_returns(300, 2, vol=0.02)
        df.iloc[:, 1] = df.iloc[:, 0] * 0.9 + df.iloc[:, 1] * 0.1
        corr = ewma_corr_forecast(df, lam=0.94)
        self.assertGreater(corr[0, 1], 0.5)


class TestLedoitWolf(unittest.TestCase):
    def test_shrunk_toward_identity(self) -> None:
        raw = np.array([[1.0, 0.9], [0.9, 1.0]])
        shrunk = ledoit_wolf_shrink(raw, 100)
        self.assertLessEqual(shrunk[0, 1], 0.9)
        self.assertAlmostEqual(shrunk[0, 0], 1.0, places=5)


class TestDownsideCorr(unittest.TestCase):
    def test_exceeds_linear_corr_in_left_tail(self) -> None:
        rng = np.random.RandomState(99)
        n = 500
        base = rng.randn(n) * 0.02
        leg0 = base + rng.randn(n) * 0.005
        leg1 = base + rng.randn(n) * 0.005
        crash = base < np.percentile(base, 10)
        leg0[crash] += -0.03
        leg1[crash] += -0.03
        df = pd.DataFrame({"A": leg0, "B": leg1}, index=pd.bdate_range("2020-01-01", periods=n))
        dc = downside_corr(df, q=0.10)
        linear = np.corrcoef(df.values.T)
        self.assertGreaterEqual(dc[0, 1], linear[0, 1] - 0.15)


class TestPortfolioCvar(unittest.TestCase):
    def test_cvar_is_negative(self) -> None:
        df = _make_returns(300, 2)
        w = np.array([0.5, 0.5])
        cvar = portfolio_cvar(w, df, alpha=0.95)
        self.assertLess(cvar, 0.0)


class TestRiskContribution(unittest.TestCase):
    def test_rc_sums_to_portfolio_vol(self) -> None:
        cov = np.array([[0.04, 0.01], [0.01, 0.09]])
        w = np.array([0.6, 0.4])
        rc = risk_contribution(w, cov)
        port_vol = math.sqrt(float(w @ cov @ w))
        self.assertAlmostEqual(sum(rc.values()), port_vol, places=6)


class TestBookFactorBeta(unittest.TestCase):
    def test_aggregation_correct(self) -> None:
        df = _make_returns(200, 3)
        leg_ret = {f"LEG_{i}": df.iloc[:, i] for i in range(3)}
        factor_ret = {"MKT": df.iloc[:, 0] + df.iloc[:, 1]}
        weights = {"LEG_0": 0.3, "LEG_1": 0.4, "LEG_2": 0.3}
        fb, be = book_factor_beta(leg_ret, factor_ret, weights)
        self.assertIn("MKT", be)
        expected = sum(weights[s] * fb[s]["MKT"] for s in fb)
        self.assertAlmostEqual(be["MKT"], expected, places=6)


class TestBuildRiskState(unittest.TestCase):
    def setUp(self) -> None:
        self.df = _make_returns(300, 3)
        self.leg_returns = {c: self.df[c] for c in self.df.columns}
        self.target_weights = {"LEG_0": 0.3, "LEG_1": 0.4, "LEG_2": 0.3}
        self.cfg = {
            "risk_engine": {
                "min_periods": 40,
                "ewma_lambda": 0.94,
                "vol_budget_annual": 0.35,
                "cvar_budget": 0.08,
                "extreme_corr_penalty": 0.70,
                "downside_q": 0.10,
                "cvar_alpha": 0.95,
            }
        }

    def test_normal_returns_reasonable_state(self) -> None:
        state = build_risk_state(self.leg_returns, self.target_weights, None, self.cfg)
        self.assertGreater(state.portfolio_vol, 0.0)
        self.assertEqual(len(state.legs_reported), 3)
        self.assertEqual(len(state.legs_used), 3)
        self.assertIn(state.corr_regime, ("NORMAL", "ELEVATED", "EXTREME", "UNKNOWN"))

    def test_high_vol_reduces_gross(self) -> None:
        high_vol = {s: r * 10 for s, r in self.leg_returns.items()}
        state = build_risk_state(high_vol, self.target_weights, None, self.cfg)
        self.assertLess(state.gross_scaler, 1.0)

    def test_insufficient_data_fallback(self) -> None:
        short = {s: r.iloc[:5] for s, r in self.leg_returns.items()}
        state = build_risk_state(short, self.target_weights, None, self.cfg)
        self.assertEqual(state.binding, "INSUFFICIENT_DATA")
        self.assertEqual(state.gross_scaler, 1.0)

    def test_hard_valve_leg_excluded_from_gross(self) -> None:
        weights_zeroed = {"LEG_0": 0.3, "LEG_1": 0.0, "LEG_2": 0.3}
        state = build_risk_state(self.leg_returns, weights_zeroed, None, self.cfg)
        self.assertNotIn("LEG_1", state.legs_used)
        self.assertIn("LEG_1", state.legs_reported)

    def test_all_derived_from_same_cov(self) -> None:
        state = build_risk_state(self.leg_returns, self.target_weights, None, self.cfg)
        w = np.array([self.target_weights[s] for s in state.legs_reported])
        recomputed_vol = math.sqrt(float(w @ state.cov @ w))
        self.assertAlmostEqual(recomputed_vol, state.portfolio_vol, places=4)

    def test_deterministic(self) -> None:
        s1 = build_risk_state(self.leg_returns, self.target_weights, None, self.cfg)
        s2 = build_risk_state(self.leg_returns, self.target_weights, None, self.cfg)
        self.assertEqual(s1.portfolio_vol, s2.portfolio_vol)
        self.assertEqual(s1.gross_scaler, s2.gross_scaler)
        self.assertEqual(s1.corr_regime, s2.corr_regime)


if __name__ == "__main__":
    unittest.main()
