from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from hermes_escape_top.core.data.market import MarketData, _INDICATOR_FRAME_CACHE
from hermes_escape_top.core.data.store import LocalStore


def _write_history(path: Path) -> None:
    path.write_text(
        "date,open,high,low,close,volume\n"
        "2026-01-01,10,11,9,10,100\n"
        "2026-01-02,11,12,10,11,100\n"
        "2026-01-05,12,13,11,12,100\n",
        encoding="utf-8",
    )


class MarketIndicatorCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        _INDICATOR_FRAME_CACHE.clear()

    def tearDown(self) -> None:
        _INDICATOR_FRAME_CACHE.clear()

    def test_indicator_cache_flag_off_keeps_uncached_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_history(root / "AAA.csv")
            cfg = {
                "paths": {"history_dir": str(root), "legacy_history_dir": str(root), "archive_dir": str(root / "archive")},
                "features": {"use_indicator_cache": False},
                "atr": {},
            }
            market = MarketData(cfg, LocalStore(cfg))

            def fake_indicator(frame: pd.DataFrame, **_: object) -> pd.DataFrame:
                return frame.copy()

            with mock.patch("hermes_escape_top.core.data.market.indicator_frame", side_effect=fake_indicator) as patched:
                market.snapshot("AAA", "2026-01-02")
                market.snapshot("AAA", "2026-01-05")

            self.assertEqual(patched.call_count, 2)
            self.assertEqual(_INDICATOR_FRAME_CACHE, {})

    def test_indicator_cache_flag_on_reuses_history_frame_across_as_of_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_history(root / "AAA.csv")
            cfg = {
                "paths": {"history_dir": str(root), "legacy_history_dir": str(root), "archive_dir": str(root / "archive")},
                "features": {"use_indicator_cache": True},
                "atr": {},
            }
            market = MarketData(cfg, LocalStore(cfg))

            def fake_indicator(frame: pd.DataFrame, **_: object) -> pd.DataFrame:
                return frame.copy()

            with mock.patch("hermes_escape_top.core.data.market.indicator_frame", side_effect=fake_indicator) as patched:
                first = market.snapshot("AAA", "2026-01-02")
                second = market.snapshot("AAA", "2026-01-05")

            self.assertEqual(patched.call_count, 1)
            self.assertEqual(first.field("close").value, 11.0)
            self.assertEqual(second.field("close").value, 12.0)


if __name__ == "__main__":
    unittest.main()
