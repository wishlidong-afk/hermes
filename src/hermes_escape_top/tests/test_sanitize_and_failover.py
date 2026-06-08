"""Tests for E1 Data Sanitization and E30 Failover Source.

Sanitize tests:
  - Bad tick (zero vol + extreme move) flagged HIGH
  - Real crash (high vol + big move) NOT flagged as bad tick
  - Stale data detected
  - Cross-source divergence flagged
  - Suspect dates populated for HIGH anomalies

Failover tests:
  - Primary healthy → no degradation
  - Primary down → fallback to secondary with is_degraded=True
  - All sources down → graceful empty result
  - Health check failure → skip source
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hermes_escape_top.core.data.sanitize import sanitize_ohlcv, Anomaly
from hermes_escape_top.core.data.failover import FailoverSource, SourceSpec, FailoverResult


def _make_normal_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    price = 100 * np.exp(np.cumsum(rng.randn(n) * 0.01))
    return pd.DataFrame({
        "open": price * (1 + rng.randn(n) * 0.003),
        "high": price * 1.005,
        "low": price * 0.995,
        "close": price,
        "volume": (rng.rand(n) * 1e6 + 1e5).astype(int),
    }, index=dates)


class TestSanitizeBadTick(unittest.TestCase):
    def test_zero_vol_extreme_move_flagged(self) -> None:
        df = _make_normal_df()
        df.loc[df.index[50], "volume"] = 0
        df.loc[df.index[50], "close"] = df.loc[df.index[49], "close"] * 1.20
        result = sanitize_ohlcv(df, {"bad_tick_ret_threshold": 0.15})
        bad_ticks = [a for a in result.anomalies if a.kind == "BAD_TICK"]
        self.assertGreater(len(bad_ticks), 0)
        self.assertIn(str(df.index[50].date()), result.suspect_dates)

    def test_real_crash_not_flagged(self) -> None:
        df = _make_normal_df()
        df.loc[df.index[50], "volume"] = 5_000_000
        df.loc[df.index[50], "close"] = df.loc[df.index[49], "close"] * 0.80
        result = sanitize_ohlcv(df, {"bad_tick_ret_threshold": 0.15})
        bad_ticks = [a for a in result.anomalies if a.kind == "BAD_TICK"]
        self.assertEqual(len(bad_ticks), 0)

    def test_chronic_zero_volume_series_not_flagged(self) -> None:
        """ETN-style series with structurally-absent volume (e.g. FNGU ~85% zero):
        a real big move must NOT be flagged BAD_TICK, since zero-volume there is
        uninformative (it would wrongly hold a hard valve on a real crash)."""
        df = _make_normal_df()
        df["volume"] = 0  # whole series unreported volume
        df.loc[df.index[50], "close"] = df.loc[df.index[49], "close"] * 0.80  # real crash
        result = sanitize_ohlcv(df, {"bad_tick_ret_threshold": 0.15})
        bad_ticks = [a for a in result.anomalies if a.kind == "BAD_TICK"]
        self.assertEqual(len(bad_ticks), 0)


class TestSanitizeStale(unittest.TestCase):
    def test_stale_detected(self) -> None:
        df = _make_normal_df()
        for i in range(40, 45):
            df.loc[df.index[i], "close"] = 100.0
        result = sanitize_ohlcv(df, {"stale_days_threshold": 3})
        stale = [a for a in result.anomalies if a.kind == "STALE"]
        self.assertGreater(len(stale), 0)


class TestSanitizeCrossSource(unittest.TestCase):
    def test_divergence_flagged(self) -> None:
        df = _make_normal_df()
        cross = df.copy()
        cross.loc[cross.index[50], "close"] = df.loc[df.index[50], "close"] * 1.10
        result = sanitize_ohlcv(df, {"cross_source_tolerance": 0.02}, cross_source=cross)
        xs = [a for a in result.anomalies if a.kind == "CROSS_SOURCE"]
        self.assertGreater(len(xs), 0)


class TestSanitizeConfidence(unittest.TestCase):
    def test_clean_data_high_confidence(self) -> None:
        df = _make_normal_df()
        result = sanitize_ohlcv(df, {})
        self.assertGreater(result.data_confidence, 0.9)

    def test_empty_df(self) -> None:
        result = sanitize_ohlcv(pd.DataFrame(), {})
        self.assertEqual(result.data_confidence, 0.0)


class TestFailoverPrimary(unittest.TestCase):
    def test_primary_healthy(self) -> None:
        primary_data = _make_normal_df(30)
        fs = FailoverSource("test", [
            SourceSpec("primary", fetch_fn=lambda **kw: primary_data, health_fn=lambda: True),
            SourceSpec("backup", fetch_fn=lambda **kw: _make_normal_df(20)),
        ])
        result = fs.fetch(as_of="2020-03-01")
        self.assertFalse(result.is_degraded)
        self.assertEqual(result.active_source, "primary")
        self.assertEqual(result.active_rank, 1)

    def test_primary_down_fallback(self) -> None:
        backup_data = _make_normal_df(30)
        fs = FailoverSource("test", [
            SourceSpec("primary", fetch_fn=lambda **kw: (_ for _ in ()).throw(ConnectionError("down")), health_fn=lambda: True),
            SourceSpec("backup", fetch_fn=lambda **kw: backup_data, health_fn=lambda: True),
        ])
        result = fs.fetch(as_of="2020-03-01")
        self.assertTrue(result.is_degraded)
        self.assertEqual(result.active_source, "backup")
        self.assertEqual(result.active_rank, 2)

    def test_all_down(self) -> None:
        fs = FailoverSource("test", [
            SourceSpec("a", fetch_fn=lambda **kw: None, health_fn=lambda: True),
            SourceSpec("b", fetch_fn=lambda **kw: pd.DataFrame(), health_fn=lambda: True),
        ])
        result = fs.fetch(as_of="2020-03-01")
        self.assertTrue(result.is_degraded)
        self.assertIsNone(result.data)
        self.assertEqual(result.active_source, "NONE")

    def test_health_check_skip(self) -> None:
        backup_data = _make_normal_df(30)
        fs = FailoverSource("test", [
            SourceSpec("unhealthy", fetch_fn=lambda **kw: _make_normal_df(30), health_fn=lambda: False),
            SourceSpec("healthy", fetch_fn=lambda **kw: backup_data, health_fn=lambda: True),
        ])
        result = fs.fetch(as_of="2020-03-01")
        self.assertTrue(result.is_degraded)
        self.assertEqual(result.active_source, "healthy")


class TestFailoverConfidenceInput(unittest.TestCase):
    def test_to_confidence_input(self) -> None:
        fs = FailoverSource("test", [
            SourceSpec("src", fetch_fn=lambda **kw: _make_normal_df(30)),
        ])
        result = fs.fetch(as_of="2020-03-01")
        ci = fs.to_confidence_input(result)
        self.assertIn("is_degraded", ci)
        self.assertIn("active_source_rank", ci)


if __name__ == "__main__":
    unittest.main()
