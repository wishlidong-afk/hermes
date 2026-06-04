"""Tests for integration config -- ensures all parameters present and phased rollout correct."""

from __future__ import annotations

import unittest

from hermes_escape_top.integration_config import (
    default_integration_config,
    phase_ii_overrides,
    phase_iii_overrides,
    phase_iv_overrides,
)


class TestDefaultConfig(unittest.TestCase):
    def test_all_sections_present(self) -> None:
        cfg = default_integration_config()
        required = [
            "symbols", "sleeve_caps", "thresholds", "confidence", "risk_engine",
            "sizing", "governance", "validation", "drift", "regime", "sanitize",
            "features", "leader_map",
        ]
        for key in required:
            self.assertIn(key, cfg, f"Missing config section: {key}")

    def test_all_features_off_by_default(self) -> None:
        cfg = default_integration_config()
        for key, val in cfg["features"].items():
            self.assertFalse(val, f"Feature {key} should be OFF by default")

    def test_calibration_thresholds_match_next3(self) -> None:
        cfg = default_integration_config()
        self.assertEqual(cfg["thresholds"]["exit"], 75)
        self.assertEqual(cfg["thresholds"]["defensive_exit"], 65)
        self.assertEqual(cfg["thresholds"]["reduce"], 50)
        self.assertEqual(cfg["thresholds"]["trim"], 35)
        self.assertEqual(cfg["thresholds"]["watch"], 20)


class TestPhasedRollout(unittest.TestCase):
    def test_phase_ii_enables_risk_not_sizing(self) -> None:
        overrides = phase_ii_overrides()
        self.assertTrue(overrides["features"]["use_risk_engine"])
        self.assertNotIn("use_sizing_optimizer", overrides["features"])

    def test_phase_iii_enables_sizing(self) -> None:
        overrides = phase_iii_overrides()
        self.assertTrue(overrides["features"]["use_sizing_optimizer"])
        self.assertTrue(overrides["features"]["use_governance"])

    def test_phase_iv_all_enabled(self) -> None:
        overrides = phase_iv_overrides()
        features = overrides["features"]
        enabled = [k for k, v in features.items() if v]
        self.assertGreaterEqual(len(enabled), 8)
        self.assertFalse(features.get("use_meta_label", False))


if __name__ == "__main__":
    unittest.main()
