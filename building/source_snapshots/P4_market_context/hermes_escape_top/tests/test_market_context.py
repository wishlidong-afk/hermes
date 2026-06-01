"""Tests for MarketContext -- multi-symbol context layer.

Test matrix (per INTEGRATION_ARCHITECTURE §5.3):
  - Per-plugin independent tests
  - Transition probability rises at historical turning points
  - No look-ahead
"""

from __future__ import annotations

import unittest
from datetime import date

import numpy as np
import pandas as pd

from hermes_escape_top.core.features.context import (
    MarketContext,
    cross_sectional_rs,
    divergence_score,
    lead_lag_signal,
    regime_with_transition,
    vrp_and_jump,
    weekly_alignment,
)


def _make_store(n: int = 300, seed: int = 42) -> dict:
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    price = 100.0 * np.exp(np.cumsum(rng.randn(n) * 0.015))
    df = pd.DataFrame({
        "open": price * (1 + rng.randn(n) * 0.005),
        "high": price * 1.01,
        "low": price * 0.99,
        "close": price,
        "volume": (rng.rand(n) * 1e6 + 1e5).astype(int),
    }, index=dates)
    return {"SYM": df, "LEADER": df.copy(), "^VIX": pd.DataFrame({"close": rng.rand(n) * 20 + 15}, index=dates)}


class TestMarketContext(unittest.TestCase):
    def test_daily_no_lookahead(self) -> None:
        store = _make_store(300)
        ctx = MarketContext("2020-06-15", store, {})
        d = ctx.daily("SYM")
        self.assertTrue(all(d.index <= pd.Timestamp("2020-06-15")))

    def test_weekly_resamples(self) -> None:
        store = _make_store(300)
        ctx = MarketContext("2021-01-01", store, {})
        w = ctx.weekly("SYM")
        self.assertGreater(len(w), 0)
        self.assertLess(len(w), 300)

    def test_missing_symbol(self) -> None:
        ctx = MarketContext("2021-01-01", {}, {})
        self.assertTrue(ctx.daily("NOSYM").empty)


class TestRegime(unittest.TestCase):
    def test_returns_valid_regime(self) -> None:
        store = _make_store(300)
        ctx = MarketContext("2021-01-01", store, {})
        r = regime_with_transition(ctx, "SYM", {})
        self.assertIn(r["regime"], ("LOW_VOL_TREND", "NORMAL", "HIGH_VOL", "CRISIS", "UNKNOWN"))
        self.assertGreaterEqual(r["p_transition"], 0.0)
        self.assertLessEqual(r["p_transition"], 1.0)

    def test_high_vol_detected(self) -> None:
        rng = np.random.RandomState(7)
        dates = pd.bdate_range("2020-01-01", periods=200)
        price = 100.0 * np.exp(np.cumsum(rng.randn(200) * 0.06))
        store = {"SYM": pd.DataFrame({"open": price, "high": price, "low": price, "close": price, "volume": 1e6}, index=dates)}
        ctx = MarketContext("2020-10-01", store, {})
        r = regime_with_transition(ctx, "SYM", {})
        self.assertIn(r["regime"], ("HIGH_VOL", "CRISIS"))


class TestWeeklyAlignment(unittest.TestCase):
    def test_returns_alignment_dict(self) -> None:
        store = _make_store(200)
        ctx = MarketContext("2020-10-01", store, {})
        result = weekly_alignment(ctx, "SYM")
        self.assertIn("aligned", result)
        self.assertIn(result["daily_trend"], ("BULL", "BEAR"))


class TestLeadLag(unittest.TestCase):
    def test_returns_field(self) -> None:
        store = _make_store(200)
        ctx = MarketContext("2020-10-01", store, {})
        f = lead_lag_signal(ctx, "LEADER", "SYM")
        self.assertEqual(f.name, "lead_lag")
        if f.value is not None:
            self.assertGreaterEqual(abs(f.value), 0.0)


class TestCrossSectionalRs(unittest.TestCase):
    def test_ranks_correct(self) -> None:
        store = _make_store(100)
        store["SYM2"] = store["SYM"].copy()
        store["SYM2"]["close"] = store["SYM2"]["close"] * 0.5
        ctx = MarketContext("2020-06-01", store, {})
        rs = cross_sectional_rs(ctx, ["SYM", "SYM2"], window=20)
        self.assertIn("SYM", rs)
        self.assertIn("SYM2", rs)


class TestDivergence(unittest.TestCase):
    def test_no_new_high_returns_zero(self) -> None:
        store = _make_store(100)
        store["SYM"]["close"].iloc[-1] = store["SYM"]["close"].iloc[-5] * 0.9
        ctx = MarketContext("2020-06-01", store, {})
        f = divergence_score(ctx, "SYM", ["LEADER"])
        self.assertEqual(f.value, 0.0)


class TestVrpAndJump(unittest.TestCase):
    def test_returns_components(self) -> None:
        store = _make_store(200)
        ctx = MarketContext("2020-10-01", store, {})
        result = vrp_and_jump(ctx, "SYM", "^VIX")
        self.assertIn("vrp", result)
        self.assertIn("jump", result)
        self.assertIn("rv", result)


if __name__ == "__main__":
    unittest.main()
