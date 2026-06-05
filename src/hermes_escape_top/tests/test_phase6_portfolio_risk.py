from __future__ import annotations

import unittest
from unittest import mock

import numpy as np
import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.portfolio.risk_budget import compute_portfolio_risk, shrink_correlation
from hermes_escape_top.pipeline import score_pipeline


def price_frame(returns: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=len(returns))
    close = 100.0 * (1.0 + pd.Series(returns, index=dates)).cumprod()
    return pd.DataFrame({"Close": close}, index=dates)


class Phase6PortfolioRiskTest(unittest.TestCase):
    def test_high_corr_high_vol_reduces_gross(self) -> None:
        config = load_config()
        base = [0.06, -0.055, 0.05, -0.045] * 80
        histories = {
            "MSTR": price_frame(base),
            "FNGU": price_frame([x * 0.9 for x in base]),
            "SOXL": price_frame([x * 1.1 for x in base]),
        }
        state = compute_portfolio_risk(histories, {"MSTR": 0.15, "FNGU": 0.20, "SOXL": 0.30}, config, feature_enabled=True)
        self.assertLess(state.gross_scaler, 1.0)
        self.assertTrue(state.portfolio_risk_cap_active)

    def test_no_active_legs_returns_neutral(self) -> None:
        config = load_config()
        histories = {"MSTR": price_frame([0.01, -0.01] * 40)}
        state = compute_portfolio_risk(histories, {"MSTR": 0.0}, config)
        self.assertEqual(state.binding_constraint, "NO_ACTIVE_LEGS")
        self.assertEqual(state.gross_scaler, 1.0)

    def test_insufficient_common_history_is_unknown(self) -> None:
        config = load_config()
        histories = {
            "MSTR": price_frame([0.01, -0.01] * 10),
            "SOXL": price_frame([0.02, -0.02] * 10),
        }
        state = compute_portfolio_risk(histories, {"MSTR": 0.15, "SOXL": 0.30}, config)
        self.assertIn(state.binding_constraint, {"NO_ACTIVE_LEGS", "INSUFFICIENT_COMMON_HISTORY"})
        self.assertEqual(state.effective_gross_scaler, 1.0)

    def test_correlation_shrinkage_moves_matrix_toward_identity(self) -> None:
        corr = pd.DataFrame([[1.0, 0.99], [0.99, 1.0]], columns=["A", "B"], index=["A", "B"])
        shrunk = shrink_correlation(corr, shrinkage=0.10)
        self.assertLess(shrunk.loc["A", "B"], corr.loc["A", "B"])
        self.assertEqual(shrunk.loc["A", "A"], 1.0)

    def test_score_pipeline_includes_portfolio_risk_state(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        risk = payload["portfolio_risk"]
        self.assertIn("legs_reported", risk)
        self.assertIn("gross_scaler", risk)
        self.assertIn("MSTR", risk["target_weights"])


if __name__ == "__main__":
    unittest.main()
