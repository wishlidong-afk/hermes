"""Tests for E9 Drift Monitor."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hermes_escape_top.core.monitor.drift import (
    DriftMonitor,
    compute_psi,
    compute_rolling_precision,
)


class TestComputePsi(unittest.TestCase):
    def test_same_distribution_low_psi(self) -> None:
        rng = np.random.RandomState(42)
        a = rng.randn(500)
        b = rng.randn(500)
        psi = compute_psi(a, b)
        self.assertLess(psi, 0.10)

    def test_shifted_distribution_high_psi(self) -> None:
        rng = np.random.RandomState(42)
        a = rng.randn(500)
        b = rng.randn(500) + 3.0
        psi = compute_psi(a, b)
        self.assertGreater(psi, 0.25)

    def test_short_series(self) -> None:
        psi = compute_psi(np.array([1, 2, 3]), np.array([4, 5, 6]))
        self.assertEqual(psi, 0.0)


class TestDriftMonitor(unittest.TestCase):
    def test_no_drift_no_alert(self) -> None:
        rng = np.random.RandomState(42)
        mon = DriftMonitor({})
        result = mon.evaluate(rng.randn(200), rng.randn(200))
        self.assertFalse(result["alert"])

    def test_score_drift_triggers_alert(self) -> None:
        rng = np.random.RandomState(42)
        mon = DriftMonitor({"psi_threshold": 0.25})
        result = mon.evaluate(rng.randn(200), rng.randn(200) + 5.0)
        self.assertTrue(result["alert"])
        self.assertGreater(result["psi"], 0.25)

    def test_precision_drop_triggers_alert(self) -> None:
        mon = DriftMonitor({"precision_drop_threshold": 0.10})
        result = mon.evaluate(
            np.random.randn(200), np.random.randn(200),
            train_precision=0.65, live_precision=0.50,
        )
        self.assertTrue(result["precision_alert"])
        self.assertTrue(result["alert"])

    def test_ic_decay_triggers_alert(self) -> None:
        mon = DriftMonitor({"ic_decay_threshold": 0.50})
        result = mon.evaluate(
            np.random.randn(200), np.random.randn(200),
            train_ic={"A1": 0.20, "C1": 0.15},
            live_ic={"A1": 0.05, "C1": 0.14},
        )
        self.assertTrue(result["ic_decay_alert"])
        self.assertTrue(result["alert"])

    def test_recommendations_populated(self) -> None:
        rng = np.random.RandomState(42)
        mon = DriftMonitor({"psi_threshold": 0.25})
        result = mon.evaluate(rng.randn(200), rng.randn(200) + 5.0)
        self.assertGreater(len(result["recommendations"]), 0)


class TestRollingPrecision(unittest.TestCase):
    def test_returns_series(self) -> None:
        df = pd.DataFrame({
            "status": ["TRIM"] * 50 + ["HOLD"] * 50,
            "fwd_max_dd": [-0.08] * 50 + [0.02] * 50,
        })
        prec = compute_rolling_precision(df, window=30)
        self.assertGreater(len(prec), 0)

    def test_empty_input(self) -> None:
        prec = compute_rolling_precision(pd.DataFrame())
        self.assertEqual(len(prec), 0)


if __name__ == "__main__":
    unittest.main()
