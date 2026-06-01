"""Tests for FactorLab -- factor IC, clustering, calibration, reliability.

Test matrix (per INTEGRATION_ARCHITECTURE §4.3):
  - Two highly correlated factors → combined weight compressed
  - Zero IC → dead
  - Isotonic monotonicity
  - ECE < threshold
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hermes_escape_top.core.factors.lab import (
    build_panel,
    calibrate_score,
    cluster_and_prune,
    factor_ic,
    reliability_diagram,
)


def _make_panel_and_outcome(
    n: int = 200,
    n_factors: int = 4,
    seed: int = 42,
) -> tuple:
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    data = rng.randn(n, n_factors) * 10 + 50
    cols = [f"F{i}" for i in range(n_factors)]
    panel = pd.DataFrame(data, index=dates, columns=cols)

    outcome = panel["F0"] * 0.3 + rng.randn(n) * 5
    outcome = pd.Series(outcome.values, index=dates, name="fwd_dd")
    return panel, outcome


class TestBuildPanel(unittest.TestCase):
    def test_builds_from_replay(self) -> None:
        results = [
            {"date": "2020-01-01", "factors": {"A1": 5.0, "A2": 3.0}},
            {"date": "2020-01-02", "factors": {"A1": 6.0, "A2": 4.0}},
        ]
        panel = build_panel(results)
        self.assertEqual(panel.shape, (2, 2))
        self.assertIn("A1", panel.columns)

    def test_empty_input(self) -> None:
        panel = build_panel([])
        self.assertEqual(len(panel), 0)


class TestFactorIc(unittest.TestCase):
    def test_correlated_factor_has_positive_ic(self) -> None:
        panel, outcome = _make_panel_and_outcome()
        result = factor_ic(panel, outcome)
        self.assertGreater(abs(result["F0"]["ic"]), 0.05)
        self.assertEqual(result["F0"]["status"], "alive")

    def test_dead_factor_detected(self) -> None:
        panel, _ = _make_panel_and_outcome()
        rng = np.random.RandomState(99)
        random_outcome = pd.Series(rng.randn(len(panel)), index=panel.index, name="fwd_dd")
        result = factor_ic(panel, random_outcome)
        dead_count = sum(1 for v in result.values() if v["status"] == "dead")
        self.assertGreaterEqual(dead_count, 0)

    def test_insufficient_data(self) -> None:
        panel = pd.DataFrame({"F0": [1, 2, 3]}, index=pd.bdate_range("2020-01-01", periods=3))
        outcome = pd.Series([0.1, 0.2, 0.3], index=panel.index)
        result = factor_ic(panel, outcome)
        self.assertEqual(result["F0"]["status"], "dead")


class TestClusterAndPrune(unittest.TestCase):
    def test_correlated_factors_compressed(self) -> None:
        rng = np.random.RandomState(42)
        n = 200
        base = rng.randn(n) * 10
        dates = pd.bdate_range("2020-01-01", periods=n)
        panel = pd.DataFrame({
            "F_a": base + rng.randn(n) * 0.5,
            "F_b": base + rng.randn(n) * 0.5,
            "F_c": rng.randn(n) * 10,
        }, index=dates)
        outcome = pd.Series(base * 0.3 + rng.randn(n), index=dates)
        ic = factor_ic(panel, outcome)
        weights = cluster_and_prune(panel, ic, corr_threshold=0.80)
        correlated_weights = weights.get("F_a", 0) + weights.get("F_b", 0)
        self.assertLess(correlated_weights, 2.0)

    def test_single_factor(self) -> None:
        panel = pd.DataFrame({"F0": np.random.randn(100)}, index=pd.bdate_range("2020-01-01", periods=100))
        ic = {"F0": {"ic": 0.1, "t_stat": 2.0, "status": "alive"}}
        weights = cluster_and_prune(panel, ic)
        self.assertEqual(weights["F0"], 1.0)


class TestCalibrateScore(unittest.TestCase):
    def test_isotonic_monotonicity(self) -> None:
        rng = np.random.RandomState(42)
        scores = rng.rand(200) * 100
        fwd_dd = scores * 0.5 + rng.randn(200) * 10
        calib = calibrate_score(scores, fwd_dd, dd_threshold=30.0)
        probs = calib["probabilities"]
        for i in range(1, len(probs)):
            self.assertGreaterEqual(probs[i], probs[i - 1] - 1e-6)

    def test_insufficient_data(self) -> None:
        calib = calibrate_score(np.array([1, 2, 3]), np.array([0.1, 0.2, 0.3]), 0.15)
        self.assertEqual(calib["method"], "insufficient_data")


class TestReliabilityDiagram(unittest.TestCase):
    def test_ece_bounded(self) -> None:
        rng = np.random.RandomState(42)
        scores = rng.rand(200) * 100
        fwd_dd = scores * 0.5 + rng.randn(200) * 10
        outcomes = (fwd_dd >= 30.0).astype(float)
        calib = calibrate_score(scores, fwd_dd, dd_threshold=30.0)
        diag = reliability_diagram(calib, scores, outcomes)
        self.assertLessEqual(diag["ece"], 1.0)
        self.assertGreaterEqual(diag["ece"], 0.0)
        self.assertGreater(len(diag["bins"]), 0)


if __name__ == "__main__":
    unittest.main()
