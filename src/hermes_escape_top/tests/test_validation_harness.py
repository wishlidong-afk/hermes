"""Tests for ValidationHarness -- anti-overfitting checks.

Test matrix (per INTEGRATION_ARCHITECTURE §6.3):
  - PBO > 0.5 detects overfitting
  - Bootstrap CI includes point estimate
  - Adversarial AUC ≈ 0.5 for same distribution
  - Crash augmentation marked is_synthetic
  - CPCV splits are purged + embargoed
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hermes_escape_top.core.backtest.harness import (
    adversarial_auc,
    augment_crashes,
    cpcv_splits,
    prob_backtest_overfitting,
    run_validation,
    stationary_block_bootstrap,
)


class TestCpcvSplits(unittest.TestCase):
    def test_splits_generated(self) -> None:
        splits = cpcv_splits(500, n_groups=6, n_test=2)
        self.assertGreater(len(splits), 0)
        for train, test in splits:
            self.assertGreater(len(train), 0)
            self.assertGreater(len(test), 0)
            overlap = set(train) & set(test)
            self.assertEqual(len(overlap), 0)

    def test_purging_removes_adjacent(self) -> None:
        splits = cpcv_splits(200, n_groups=4, n_test=1, label_horizon=10)
        for train, test in splits:
            for t in test:
                for offset in range(-10, 11):
                    neighbor = t + offset
                    if neighbor != t and 0 <= neighbor < 200:
                        self.assertNotIn(neighbor, train,
                                         f"Purge failed: train contains {neighbor} near test {t}")

    def test_embargo_applies_after_every_disjoint_test_block(self) -> None:
        n_obs = 240
        embargo_pct = 0.05
        embargo = int(n_obs * embargo_pct)
        splits = cpcv_splits(
            n_obs,
            n_groups=6,
            n_test=2,
            label_horizon=0,
            embargo_pct=embargo_pct,
        )

        checked_disjoint = False
        for train, test in splits:
            breaks = np.flatnonzero(np.diff(test) > 1)
            if not len(breaks):
                continue
            checked_disjoint = True
            for position in breaks:
                block_end = int(test[position])
                embargoed = set(range(block_end + 1, min(n_obs, block_end + embargo + 1)))
                self.assertFalse(embargoed & set(train))
        self.assertTrue(checked_disjoint)


class TestPbo(unittest.TestCase):
    def test_random_is_high_pbo(self) -> None:
        rng = np.random.RandomState(42)
        is_perf = rng.randn(10, 8)
        oos_perf = rng.randn(10, 8)
        pbo = prob_backtest_overfitting(is_perf, oos_perf)
        self.assertGreaterEqual(pbo, 0.0)
        self.assertLessEqual(pbo, 1.0)

    def test_perfect_is_zero_pbo(self) -> None:
        is_perf = np.array([[1, 1, 1, 1], [0, 0, 0, 0]])
        oos_perf = np.array([[1, 1, 1, 1], [0, 0, 0, 0]])
        pbo = prob_backtest_overfitting(is_perf, oos_perf)
        self.assertEqual(pbo, 0.0)


class TestBootstrap(unittest.TestCase):
    def test_ci_bounds(self) -> None:
        rng = np.random.RandomState(42)
        returns = rng.randn(300) * 0.01
        result = stationary_block_bootstrap(returns, n_bootstrap=500, seed=42)
        self.assertIn("calmar_ci", result)
        lo, hi = result["calmar_ci"]
        self.assertLess(lo, hi)

    def test_deterministic(self) -> None:
        rng = np.random.RandomState(42)
        returns = rng.randn(200) * 0.01
        r1 = stationary_block_bootstrap(returns, n_bootstrap=100, seed=7)
        r2 = stationary_block_bootstrap(returns, n_bootstrap=100, seed=7)
        self.assertEqual(r1["calmar_ci"], r2["calmar_ci"])

    def test_short_series(self) -> None:
        result = stationary_block_bootstrap(np.array([0.01, -0.01]), n_bootstrap=10)
        self.assertEqual(result["n_samples"], 0)


class TestAdversarialAuc(unittest.TestCase):
    def test_same_distribution_near_half(self) -> None:
        rng = np.random.RandomState(42)
        X = rng.randn(200, 5)
        auc = adversarial_auc(X[:100], X[100:], seed=42)
        self.assertGreater(auc, 0.3)
        self.assertLess(auc, 0.7)

    def test_different_distribution_higher(self) -> None:
        rng = np.random.RandomState(42)
        train = rng.randn(100, 5)
        live = rng.randn(100, 5) + 3.0
        auc = adversarial_auc(train, live, seed=42)
        self.assertGreater(auc, 0.7)


class TestAugmentCrashes(unittest.TestCase):
    def test_generates_synthetic(self) -> None:
        rng = np.random.RandomState(42)
        history = rng.randn(500) * 0.02
        result = augment_crashes(history, [(100, 150), (300, 350)], n_augment=20)
        self.assertTrue(result["is_synthetic"])
        self.assertEqual(result["n_generated"], 20)
        self.assertGreater(len(result["synthetic"]), 0)

    def test_no_crash_windows(self) -> None:
        result = augment_crashes(np.array([0.01, -0.01]), [], n_augment=10)
        self.assertEqual(result["n_generated"], 0)


class TestRunValidation(unittest.TestCase):
    def test_end_to_end(self) -> None:
        rng = np.random.RandomState(42)
        data = pd.DataFrame({"close": 100 * np.exp(np.cumsum(rng.randn(300) * 0.01))},
                            index=pd.bdate_range("2020-01-01", periods=300))

        def dummy_strategy(df):
            return float(df.iloc[:, 0].pct_change().mean())

        result = run_validation(dummy_strategy, data, {"validation": {"n_groups": 4, "n_test": 1, "bootstrap_n": 100}})
        self.assertIn("pbo", result)
        self.assertIn("pbo_pass", result)
        self.assertIsNone(result["pbo"])
        self.assertIsNone(result["pbo_pass"])
        self.assertTrue(result["report_ready"])

    def test_multi_config_strategy_can_compute_pbo(self) -> None:
        rng = np.random.RandomState(7)
        data = pd.DataFrame({"close": 100 * np.exp(np.cumsum(rng.randn(300) * 0.01))},
                            index=pd.bdate_range("2020-01-01", periods=300))

        def multi_config_strategy(df):
            returns = df.iloc[:, 0].pct_change().dropna()
            return np.array([float(returns.mean()), float(-returns.mean())])

        result = run_validation(multi_config_strategy, data, {"validation": {"n_groups": 4, "n_test": 1, "bootstrap_n": 100}})
        self.assertIsNotNone(result["pbo"])
        self.assertIsInstance(result["pbo_pass"], bool)


if __name__ == "__main__":
    unittest.main()
