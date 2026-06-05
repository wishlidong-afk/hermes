from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.portfolio.invariants import assert_not_more_aggressive
from hermes_escape_top.core.portfolio.sizing import size_position
from hermes_escape_top.pipeline import score_pipeline


def price_frame(returns: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=len(returns))
    close = 100.0 * (1.0 + pd.Series(returns, index=dates)).cumprod()
    return pd.DataFrame({"Close": close}, index=dates)


class Phase7SizingTest(unittest.TestCase):
    def test_invariant_blocks_more_aggressive_target(self) -> None:
        with self.assertRaises(AssertionError):
            assert_not_more_aggressive(0.20, 0.21)

    def test_high_volatility_reduces_target(self) -> None:
        config = load_config()
        low = [0.004, -0.003, 0.002, -0.002] * 70
        high = [0.05, -0.045, 0.04, -0.035] * 20
        decision = size_position("SOXL", price_frame(low + high), 0.30, 0.0, config)
        self.assertLess(decision.target_weight, 0.30)
        self.assertTrue(decision.clamp_applied)

    def test_sold_position_sizes_to_zero(self) -> None:
        config = load_config()
        decision = size_position("MSTR", price_frame([0.01, -0.01] * 160), 0.15, 1.0, config)
        self.assertEqual(decision.target_weight, 0.0)

    def test_score_pipeline_includes_sizing(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        self.assertEqual(set(payload["sizing"]), {"FNGU", "MSTR", "SOXL"})
        self.assertEqual(payload["sizing"]["MSTR"]["target_weight"], 0.0)


if __name__ == "__main__":
    unittest.main()
